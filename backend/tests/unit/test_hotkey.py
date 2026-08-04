"""R-SAF-04's global hotkey binding. `keyboard.add_hotkey`/`remove_hotkey`
are mocked — registering a real OS-wide hook has no place in an automated
test (§0: no real third-party/system dependency in tests)."""
import asyncio
from unittest.mock import patch

from codirector.safety.hotkey import GlobalKillSwitchHotkey


async def test_trigger_calls_callback_via_loop():
    triggered = []

    async def on_trigger():
        triggered.append(True)

    captured_callback = {}

    def fake_add_hotkey(hotkey, callback):
        captured_callback["fn"] = callback

    with patch("codirector.safety.hotkey.keyboard.add_hotkey", side_effect=fake_add_hotkey):
        loop = asyncio.get_running_loop()
        hk = GlobalKillSwitchHotkey(on_trigger=on_trigger, loop=loop)
        hk.start()

        # Simulate the OS delivering the hotkey on keyboard's own thread.
        captured_callback["fn"]()
        await asyncio.sleep(0.05)  # let call_soon_threadsafe's task run

    assert triggered == [True]


async def test_stop_removes_hotkey():
    async def on_trigger():
        pass

    with patch("codirector.safety.hotkey.keyboard.add_hotkey"), patch(
        "codirector.safety.hotkey.keyboard.remove_hotkey"
    ) as mock_remove:
        loop = asyncio.get_running_loop()
        hk = GlobalKillSwitchHotkey(on_trigger=on_trigger, loop=loop)
        hk.start()
        hk.stop()
        mock_remove.assert_called_once()
