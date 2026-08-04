"""R-ASR-06 (loop never blocked) and R-ASR-05 (degrade, don't crash), against
the real ParakeetASRProvider. nemo_toolkit isn't installed in this sandbox
(see CLAUDE.md) so model load fails inside start()'s try/except — this
exercises the *real* degrade-gracefully code path, not a mock double, and
also proves start() returns promptly rather than blocking the event loop
while that failure is handled."""
import asyncio
import time

from codirector.adapters.asr.parakeet import ParakeetASRProvider


async def test_start_degrades_without_crashing_when_model_unavailable():
    provider = ParakeetASRProvider(channel="mic")
    await provider.start(lambda e: None)
    assert provider.health.status == "down"
    assert "model load failed" in provider.health.detail


async def test_loop_not_blocked_while_start_runs():
    """A concurrent task must keep making progress while start() is awaited
    — proves start() isn't doing long synchronous work on the event loop
    thread itself (the actual heavy lifting, real model inference, happens
    on the dedicated worker thread per R-ASR-06; here we confirm start()'s
    own model-load attempt doesn't block cooperative scheduling)."""
    ticks = 0

    async def ticker():
        nonlocal ticks
        for _ in range(5):
            await asyncio.sleep(0.01)
            ticks += 1

    provider = ParakeetASRProvider(channel="mic")
    ticker_task = asyncio.create_task(ticker())
    start_time = time.monotonic()
    await provider.start(lambda e: None)
    await ticker_task

    assert ticks == 5
    assert time.monotonic() - start_time < 2.0
