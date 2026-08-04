"""R-OBS-04: reconnect with capped exponential backoff; health events emitted.
Uses real (small) wall-clock waits rather than patching asyncio.sleep —
patching the sleep used by the module under test also patches the *test's
own* sleep calls, since both import the same global asyncio module object,
which starves the event loop of yield points entirely."""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from codirector.adapters.obs.client import OBSAdapter


class _FlakyReqClient:
    """Fails to construct (auth/connect) the first `fail_connects_remaining`
    times, then behaves normally. Also fails get_scene_list once mid-session
    to trigger the reconnect path."""

    fail_connects_remaining = 1
    constructed_count = 0
    should_fail_state_once = True

    def __init__(self, **kwargs):
        type(self).constructed_count += 1
        if type(self).fail_connects_remaining > 0:
            type(self).fail_connects_remaining -= 1
            raise ConnectionError("obs not reachable yet")

    def get_scene_list(self):
        if type(self).should_fail_state_once:
            type(self).should_fail_state_once = False
            raise ConnectionError("connection dropped")
        return SimpleNamespace(scenes=[{"sceneName": "Gameplay"}])

    def get_current_program_scene(self):
        return SimpleNamespace(current_program_scene_name="Gameplay")

    def get_stream_status(self):
        return SimpleNamespace(output_active=True, output_skipped_frames=0)


async def test_backoff_and_health():
    with patch("codirector.adapters.obs.client.obs.ReqClient", _FlakyReqClient):
        adapter = OBSAdapter(host="127.0.0.1", port=4455, password="pw", poll_interval_s=0.05)

        # First connect attempt fails (fail_connects_remaining starts at 1).
        try:
            await adapter.connect()
        except ConnectionError:
            pass
        assert adapter.health.status == "down"

        adapter.start_polling(lambda _state: None)
        # The poll loop's own backoff is a real 1s sleep per failure. Two
        # failures happen in sequence (initial not-connected, then
        # get_scene_list's one-time drop), so budget ~2s of backoff plus
        # scheduling overhead.
        await asyncio.sleep(2.8)
        adapter.stop_polling()
        await asyncio.sleep(0)

        assert adapter.health.status == "ok"
        assert _FlakyReqClient.constructed_count >= 2  # initial failure + eventual success
