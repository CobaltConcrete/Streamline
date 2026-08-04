"""Real ASR provider — build spec v1.0 §5.4. NVIDIA Parakeet
(nvidia/parakeet-unified-en-0.6b) via NeMo, in-process, cache-aware streaming.

nemo_toolkit is a heavy, GPU-toolchain-specific optional dependency
(pyproject `[asr]` extra) not installed in this sandboxed dev environment —
`nemo_toolkit[asr]`'s own dependency tree (lightning, transformers, wandb,
webdataset, several nv_one_logger_* packages, antlr4 needing a from-source
build...) hit a native build crash (exit 0xC0000005) partway through install
here, and is disproportionate to install just to prove this file imports.
torch itself *is* installed and its preflight (adapters/asr/preflight.py) was
verified for real against this machine's RTX 4090. This module is therefore
implemented faithfully to §5.4 but UNVERIFIED against a live model/microphone
— see CLAUDE.md's "Known limitations" section before relying on it.

Threading discipline (R-ASR-06): sounddevice's capture callback runs on its
own C thread; NeMo inference runs on a dedicated worker thread. Neither
touches the asyncio loop directly — every event crosses via
loop.call_soon_threadsafe, so a slow inference call can never stall OBS
polling or the kill switch.
"""
import queue
import threading
import time
import uuid
from collections.abc import Callable

import numpy as np
import sounddevice as sd
import webrtcvad

from codirector.core.events import HealthEvent, TranscriptEvent, Trust

MODEL_NAME = "nvidia/parakeet-unified-en-0.6b"
_SAMPLE_RATE = 16000
_FRAME_MS = 20  # webrtcvad requires 10/20/30ms frames
_FRAME_SAMPLES = _SAMPLE_RATE * _FRAME_MS // 1000
_SPEECH_GAP_MS_DEFAULT = 1200  # silence after a final before we call the utterance ended


class ParakeetASRProvider:
    def __init__(self, channel: str = "mic", device: str = "cuda", streaming_latency_ms: int = 160) -> None:
        if channel not in ("mic", "desktop"):
            raise ValueError("channel must be 'mic' or 'desktop'")
        self._channel = channel
        self._trust = Trust.CREATOR if channel == "mic" else Trust.VIEWER  # R-SAF-03
        self._device = device
        self._streaming_latency_ms = streaming_latency_ms

        self._status = "down"
        self._detail = "not started"
        self._stop_event = threading.Event()
        self._audio_queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream: sd.InputStream | None = None
        self._worker: threading.Thread | None = None
        self._loop = None
        self._on_event: Callable[[TranscriptEvent], None] | None = None
        self._model = None

    async def start(self, on_event: Callable[[TranscriptEvent], None]) -> None:
        import asyncio

        self._on_event = on_event
        self._loop = asyncio.get_running_loop()

        # Warm up before reporting healthy (§5.4: "do not lazy-load on first
        # speech"). Import is lazy: nemo_toolkit is an optional, heavy
        # dependency (see module docstring) not required by anything else.
        try:
            import nemo.collections.asr as nemo_asr

            self._model = nemo_asr.models.ASRModel.from_pretrained(MODEL_NAME)
            self._model = self._model.to(self._device)
            self._model.eval()
            silence = np.zeros(_SAMPLE_RATE, dtype=np.float32)  # 1s warm-up clip
            self._model.transcribe([silence])
        except Exception as exc:  # noqa: BLE001 — R-ASR-05: degrade, never crash the pipeline
            self._status = "down"
            self._detail = f"model load failed: {exc}"
            return

        self._stop_event.clear()
        self._worker = threading.Thread(target=self._inference_loop, daemon=True)
        self._worker.start()

        def _audio_callback(indata, frames, time_info, status):  # sounddevice capture thread
            self._audio_queue.put(indata[:, 0].copy())

        self._stream = sd.InputStream(
            samplerate=_SAMPLE_RATE, channels=1, dtype="float32",
            blocksize=_FRAME_SAMPLES, callback=_audio_callback,
        )
        self._stream.start()
        self._status = "ok"
        self._detail = "streaming"

    async def stop(self) -> None:
        self._stop_event.set()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
        if self._worker is not None:
            self._worker.join(timeout=2.0)
        self._status = "down"
        self._detail = "stopped"

    @property
    def health(self) -> HealthEvent:
        now = time.monotonic()
        return HealthEvent(
            event_id=str(uuid.uuid4()),
            event_time=now,
            ingest_time=now,
            wall_time="1970-01-01T00:00:00.000Z",
            trust=Trust.SYSTEM,
            component="asr",
            status=self._status,
            detail=self._detail,
        )

    def _emit(self, event: TranscriptEvent) -> None:
        if self._loop is not None and self._on_event is not None:
            self._loop.call_soon_threadsafe(self._on_event, event)

    def _make_event(self, event_type: str, text: str, confidence: float | None) -> TranscriptEvent:
        now = time.monotonic()
        return TranscriptEvent(
            event_id=str(uuid.uuid4()),
            event_time=now,
            ingest_time=now,
            wall_time="1970-01-01T00:00:00.000Z",
            trust=self._trust,
            type=event_type,
            text=text,
            channel=self._channel,
            asr_confidence=confidence,
        )

    def _inference_loop(self) -> None:
        """Runs on a dedicated worker thread (R-ASR-06) — never touches the
        asyncio loop directly. Uses NeMo's cache-aware streaming buffer so
        the model gets true incremental frames rather than a hand-rolled
        sliding window over transcribe() (§5.4: this is exactly the
        distinction that motivated pinning D-7 to the unified checkpoint)."""
        vad = webrtcvad.Vad(2)
        last_speech_time = time.monotonic()
        in_utterance = False
        partial_text = ""

        try:
            from nemo.collections.asr.parts.utils.streaming_utils import (
                CacheAwareStreamingAudioBuffer,
            )

            streaming_buffer = CacheAwareStreamingAudioBuffer(model=self._model, online_normalization=False)
        except Exception as exc:  # noqa: BLE001
            self._status = "down"
            self._detail = f"streaming buffer init failed: {exc}"
            return

        while not self._stop_event.is_set():
            try:
                frame = self._audio_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            frame_i16 = (frame * 32768.0).astype(np.int16).tobytes()
            is_speech = vad.is_speech(frame_i16, _SAMPLE_RATE)
            now = time.monotonic()

            try:
                streaming_buffer.append_audio(frame)
                hypothesis, _is_final_segment = streaming_buffer.get_hypothesis()
            except Exception as exc:  # noqa: BLE001 — R-ASR-05
                self._status = "down"
                self._detail = f"inference failure: {exc}"
                return

            if hypothesis:
                partial_text = hypothesis
                self._emit(self._make_event("transcript.partial", partial_text, None))

            if is_speech:
                last_speech_time = now
                in_utterance = True
            elif in_utterance and (now - last_speech_time) * 1000 >= _SPEECH_GAP_MS_DEFAULT:
                if partial_text:
                    self._emit(self._make_event("transcript.final", partial_text, 0.9))
                self._emit(self._make_event("transcript.speech_ended", "", None))
                partial_text = ""
                in_utterance = False
