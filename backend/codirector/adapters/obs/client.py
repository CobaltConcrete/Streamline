"""Real OBS adapter — build spec v1.0 §5.2. obsws-python is a synchronous,
blocking client; every call is wrapped in asyncio.to_thread so it never stalls
the event loop (same discipline as the ASR worker thread, R-ASR-06's rationale
applied here for the same reason: a blocked loop would also stall the kill
switch).

obsws_python.ReqClient performs the identify/authenticate handshake
synchronously inside its own constructor and raises on failure — so "no
request is sent before authentication succeeds" (R-OBS-01) falls out of the
library's own behaviour: we only ever hold a client instance if construction
(and therefore auth) already succeeded.
"""
import asyncio
import time
import uuid
from collections.abc import Callable

import obsws_python as obs

from codirector.core.events import HealthEvent, OBSStateEvent

_MAX_BACKOFF_S = 30.0


class OBSAdapter:
    def __init__(self, host: str, port: int, password: str | None, poll_interval_s: float = 1.0) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._poll_interval_s = poll_interval_s
        self._client: obs.ReqClient | None = None
        self._connected = False
        self._status: str = "down"
        self._detail: str = "not connected"
        self._last_emitted: OBSStateEvent | None = None
        self._poll_task: asyncio.Task | None = None
        self._stop_requested = False

    # -- connection -----------------------------------------------------
    async def connect(self) -> None:
        def _make_client() -> obs.ReqClient:
            return obs.ReqClient(host=self._host, port=self._port, password=self._password, timeout=5)

        self._client = await asyncio.to_thread(_make_client)
        self._connected = True
        self._status = "ok"
        self._detail = "connected"

    def _client_or_raise(self) -> obs.ReqClient:
        if not self._connected or self._client is None:
            raise RuntimeError("OBS adapter used before a successful authenticated connect()")
        return self._client

    # -- OBSProvider protocol --------------------------------------------
    async def get_state(self) -> OBSStateEvent:
        client = self._client_or_raise()

        def _fetch():
            scenes_resp = client.get_scene_list()
            current = client.get_current_program_scene()
            stream_resp = client.get_stream_status()
            return scenes_resp, current, stream_resp

        scenes_resp, current, stream_resp = await asyncio.to_thread(_fetch)
        scenes = [s["sceneName"] for s in scenes_resp.scenes]
        now = time.monotonic()
        event = OBSStateEvent(
            event_id=str(uuid.uuid4()),
            event_time=now,
            ingest_time=now,
            wall_time="1970-01-01T00:00:00.000Z",
            trust="system",
            program_scene=current.current_program_scene_name,
            scenes=scenes,
            streaming=bool(stream_resp.output_active),
            dropped_frames=int(getattr(stream_resp, "output_skipped_frames", 0)),
        )
        return event

    async def set_scene(self, scene_name: str) -> None:
        client = self._client_or_raise()
        await asyncio.to_thread(client.set_current_program_scene, scene_name)

    async def set_input_text(self, input_name: str, text: str) -> None:
        client = self._client_or_raise()
        await asyncio.to_thread(client.set_input_settings, input_name, {"text": text}, True)

    async def set_item_visibility(self, scene: str, item_id: int, visible: bool) -> None:
        client = self._client_or_raise()
        await asyncio.to_thread(client.set_scene_item_enabled, scene, item_id, visible)

    async def set_filter_enabled(self, source: str, filter_name: str, enabled: bool) -> None:
        client = self._client_or_raise()
        await asyncio.to_thread(client.set_source_filter_enabled, source, filter_name, enabled)

    # -- inventory / prior-state helpers (adapter-specific, not in Protocol) --
    def list_inputs(self) -> list[str]:
        client = self._client_or_raise()
        return [i["inputName"] for i in client.get_input_list().inputs]

    def list_scene_items(self, scene: str) -> list[str]:
        client = self._client_or_raise()
        return [i["sourceName"] for i in client.get_scene_item_list(scene).scene_items]

    def list_filters(self, source: str) -> list[str]:
        client = self._client_or_raise()
        return [f["filterName"] for f in client.get_source_filter_list(source).filters]

    def resolve_item_id(self, scene: str, item_name: str) -> int:
        client = self._client_or_raise()
        return client.get_scene_item_id(scene, item_name).scene_item_id

    def get_input_text(self, input_name: str) -> str:
        client = self._client_or_raise()
        return client.get_input_settings(input_name).input_settings.get("text", "")

    def get_item_visibility(self, scene: str, item_name: str) -> bool:
        client = self._client_or_raise()
        item_id = self.resolve_item_id(scene, item_name)
        return bool(client.get_scene_item_enabled(scene, item_id).scene_item_enabled)

    def get_filter_enabled(self, source: str, filter_name: str) -> bool:
        client = self._client_or_raise()
        return bool(client.get_source_filter(source, filter_name).filter_enabled)

    # -- polling (R-OBS-02) + reconnect (R-OBS-04) -----------------------
    def start_polling(self, on_change: Callable[[OBSStateEvent], None]) -> None:
        self._stop_requested = False
        self._poll_task = asyncio.create_task(self._poll_loop(on_change))

    def stop_polling(self) -> None:
        self._stop_requested = True
        if self._poll_task is not None:
            self._poll_task.cancel()

    async def _poll_loop(self, on_change: Callable[[OBSStateEvent], None]) -> None:
        backoff = 1.0
        while not self._stop_requested:
            try:
                state = await self.get_state()
                if self._changed(state):
                    self._last_emitted = state
                    on_change(state)
                self._status = "ok"
                backoff = 1.0
                await asyncio.sleep(self._poll_interval_s)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — connection dropped, reconnect below
                self._connected = False
                self._status = "degraded"
                self._detail = f"disconnected: {exc}"
                await asyncio.sleep(backoff)
                try:
                    await self.connect()
                except Exception as reconnect_exc:  # noqa: BLE001
                    self._status = "down"
                    self._detail = f"reconnect failed: {reconnect_exc}"
                    backoff = min(backoff * 2, _MAX_BACKOFF_S)

    def _changed(self, state: OBSStateEvent) -> bool:
        if self._last_emitted is None:
            return True
        prev = self._last_emitted
        return (
            prev.program_scene != state.program_scene
            or prev.scenes != state.scenes
            or prev.streaming != state.streaming
            or prev.dropped_frames != state.dropped_frames
        )

    @property
    def health(self) -> HealthEvent:
        now = time.monotonic()
        return HealthEvent(
            event_id=str(uuid.uuid4()),
            event_time=now,
            ingest_time=now,
            wall_time="1970-01-01T00:00:00.000Z",
            trust="system",
            component="obs",
            status=self._status,
            detail=self._detail,
        )
