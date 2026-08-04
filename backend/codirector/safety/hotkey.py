"""Global OS-level kill-switch hotkey — build spec v1.0 §5.11/R-SAF-04.
"Always-available" means it must work even when the browser tab (or any
window) doesn't have focus, which an in-page JS keydown listener alone can't
guarantee — the frontend has one too (App.tsx) as a same-tab convenience,
but this is the real, OS-wide binding.

`keyboard.add_hotkey`'s callback runs on the `keyboard` library's own
listener thread, never the asyncio loop — same discipline as the ASR worker
thread (R-ASR-06's rationale): cross via loop.call_soon_threadsafe so a slow
coroutine downstream can never delay the *registration* of the freeze.
"""
import asyncio
from collections.abc import Awaitable, Callable

import keyboard

DEFAULT_HOTKEY = "ctrl+alt+k"


class GlobalKillSwitchHotkey:
    def __init__(
        self,
        on_trigger: Callable[[], Awaitable[None]],
        loop: asyncio.AbstractEventLoop,
        hotkey: str = DEFAULT_HOTKEY,
    ) -> None:
        self._on_trigger = on_trigger
        self._loop = loop
        self._hotkey = hotkey
        self._registered = False

    def _handle(self) -> None:
        # Runs on keyboard's listener thread (R-SAF-04: must not block here).
        self._loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._on_trigger()))

    def start(self) -> None:
        keyboard.add_hotkey(self._hotkey, self._handle)
        self._registered = True

    def stop(self) -> None:
        if self._registered:
            keyboard.remove_hotkey(self._hotkey)
            self._registered = False
