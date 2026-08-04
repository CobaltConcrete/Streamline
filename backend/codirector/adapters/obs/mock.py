"""Deterministic in-memory OBS provider. Implements adapters.base.OBSProvider.
No I/O, no clock reads — state changes only in response to explicit calls, so
tests get identical results regardless of when/how fast they run."""
import time
import uuid

from codirector.core.events import HealthEvent, OBSStateEvent


class MockOBSProvider:
    def __init__(
        self,
        scenes: list[str] | None = None,
        program_scene: str = "Gameplay",
        scene_items: dict[str, dict[str, bool]] | None = None,
        known_inputs: list[str] | None = None,
        known_filters: dict[str, list[str]] | None = None,
    ) -> None:
        self._connected = False
        self.scenes = scenes or ["Gameplay", "BRB", "Starting Soon", "Ending"]
        self.program_scene = program_scene
        # scene -> {item_name: visible}
        self.scene_items = scene_items or {"Gameplay": {"CameraFrame": True}}
        # Inventory that pre-exists in OBS regardless of whether it's been
        # written to yet — distinct from input_text (values written so far).
        self._known_inputs = known_inputs or ["AI_Question_Text", "AI_Support_Text"]
        self._known_filters = known_filters or {"CameraFrame": ["HypeGlow"]}
        self.input_text: dict[str, str] = {}
        self.filter_enabled: dict[tuple[str, str], bool] = {}
        self.streaming = True
        self.dropped_frames = 0
        self.set_scene_calls: list[str] = []
        self.set_input_text_calls: list[tuple[str, str]] = []
        # (scene, item_name) -> numeric item id, assigned on first sight, so
        # the orchestrator can resolve the config's item_name to the
        # int-typed item_id the OBSProvider Protocol actually takes.
        self._item_ids: dict[tuple[str, str], int] = {}
        next_id = 1
        for scene, items in self.scene_items.items():
            for item_name in items:
                self._item_ids[(scene, item_name)] = next_id
                next_id += 1

    async def connect(self) -> None:
        self._connected = True

    async def get_state(self) -> OBSStateEvent:
        now = time.monotonic()
        return OBSStateEvent(
            event_id=str(uuid.uuid4()),
            event_time=now,
            ingest_time=now,
            wall_time="1970-01-01T00:00:00.000Z",
            trust="system",
            program_scene=self.program_scene,
            scenes=list(self.scenes),
            streaming=self.streaming,
            dropped_frames=self.dropped_frames,
        )

    async def set_scene(self, scene_name: str) -> None:
        if scene_name not in self.scenes:
            raise ValueError(f"unknown scene: {scene_name}")
        self.program_scene = scene_name
        self.set_scene_calls.append(scene_name)

    async def set_input_text(self, input_name: str, text: str) -> None:
        self.input_text[input_name] = text
        self.set_input_text_calls.append((input_name, text))

    async def set_item_visibility(self, scene: str, item_id: int, visible: bool) -> None:
        for (s, name), iid in self._item_ids.items():
            if s == scene and iid == item_id:
                self.scene_items.setdefault(scene, {})[name] = visible
                return
        raise ValueError(f"unknown item_id {item_id} in scene {scene!r}")

    def resolve_item_id(self, scene: str, item_name: str) -> int:
        if (scene, item_name) not in self._item_ids:
            raise KeyError(f"item {item_name!r} not found in scene {scene!r}")
        return self._item_ids[(scene, item_name)]

    # --- Prior-state getters used by orchestrator.rollback. Not part of
    # adapters.base.OBSProvider (which is set-only); reading current state
    # back is an adapter-specific extension every concrete provider offers.
    def get_input_text(self, input_name: str) -> str:
        return self.input_text.get(input_name, "")

    def get_item_visibility(self, scene: str, item_name: str) -> bool:
        return self.scene_items.get(scene, {}).get(item_name, True)

    def get_filter_enabled(self, source: str, filter_name: str) -> bool:
        return self.filter_enabled.get((source, filter_name), False)

    async def set_filter_enabled(self, source: str, filter_name: str, enabled: bool) -> None:
        self.filter_enabled[(source, filter_name)] = enabled

    # --- Inventory helpers used by policy.catalog.resolve_targets (R-OBS-03).
    # Not part of adapters.base.OBSProvider: that Protocol is the binding
    # execution surface; inventory discovery is adapter-specific.
    def list_inputs(self) -> list[str]:
        return list(self._known_inputs)

    def list_scene_items(self, scene: str) -> list[str]:
        return list(self.scene_items.get(scene, {}).keys())

    def list_filters(self, source: str) -> list[str]:
        return list(self._known_filters.get(source, []))

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
            status="ok" if self._connected else "down",
            detail="mock connected" if self._connected else "mock not connected",
        )
