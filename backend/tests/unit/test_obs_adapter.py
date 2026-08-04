"""R-OBS-01 / R-OBS-02, exercised against the real adapter with obsws_python's
ReqClient replaced by a fake — no real OBS instance is ever contacted."""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from codirector.adapters.obs.client import OBSAdapter


class _FakeReqClient:
    """Stands in for obsws_python.ReqClient. Construction succeeding *is* the
    auth handshake succeeding — mirrors the real library's behaviour."""

    def __init__(self, **kwargs):
        if kwargs.get("password") == "wrong":
            raise ConnectionRefusedError("authentication failed")
        self.scenes = ["Gameplay", "BRB"]
        self.program_scene = "Gameplay"

    def get_scene_list(self):
        return SimpleNamespace(scenes=[{"sceneName": s} for s in self.scenes])

    def get_current_program_scene(self):
        return SimpleNamespace(current_program_scene_name=self.program_scene)

    def get_stream_status(self):
        return SimpleNamespace(output_active=True, output_skipped_frames=0)


async def test_no_request_before_auth():
    with patch("codirector.adapters.obs.client.obs.ReqClient", _FakeReqClient):
        adapter = OBSAdapter(host="127.0.0.1", port=4455, password="wrong")
        with pytest.raises(ConnectionRefusedError):
            await adapter.connect()

        # No client was ever installed, so any request-sending method must
        # refuse rather than silently no-op or crash with an AttributeError
        # deep inside a library call.
        with pytest.raises(RuntimeError):
            await adapter.get_state()

        adapter2 = OBSAdapter(host="127.0.0.1", port=4455, password="correct")
        await adapter2.connect()
        state = await adapter2.get_state()
        assert state.program_scene == "Gameplay"


async def test_state_emitted_on_change_only():
    with patch("codirector.adapters.obs.client.obs.ReqClient", _FakeReqClient):
        adapter = OBSAdapter(host="127.0.0.1", port=4455, password="correct", poll_interval_s=0.01)
        await adapter.connect()

        emissions = []
        adapter.start_polling(lambda state: emissions.append(state))
        await asyncio.sleep(0.05)  # several poll cycles, scene unchanged throughout
        assert len(emissions) == 1  # only the initial (first-ever) emission

        adapter._client.program_scene = "BRB"  # simulate a manual scene change
        await asyncio.sleep(0.05)
        adapter.stop_polling()
        await asyncio.sleep(0)  # let the cancellation propagate

        assert len(emissions) == 2
        assert emissions[-1].program_scene == "BRB"
