"""R-ASR-04 deterministic preflight tests; no real GPU or torch is required."""
import sys
from types import SimpleNamespace
from unittest.mock import patch

from codirector.adapters.asr.preflight import run_preflight


class _FakeTensor:
    def __add__(self, _value):
        return self

    def sum(self):
        return self

    def item(self):
        return 8


def _torch(*, available: bool = True, free_mb: int = 4096):
    properties = SimpleNamespace(name="Mock GPU", major=8, minor=0)
    cuda = SimpleNamespace(
        is_available=lambda: available,
        get_device_properties=lambda _index: properties,
        mem_get_info=lambda _index=0: (free_mb * 1024 * 1024, 16 * 1024**3),
    )
    return SimpleNamespace(cuda=cuda, zeros=lambda *_args, **_kwargs: _FakeTensor())


def test_preflight_passes_with_compatible_gpu():
    with patch.dict(sys.modules, {"torch": _torch()}):
        result = run_preflight(
            min_free_vram_mb=2500, model_name="nvidia/parakeet-unified-en-0.6b"
        )
    assert result.passed is True
    assert "compute_capability" in result.checks


def test_preflight_gates_session_start_on_insufficient_vram():
    with patch.dict(sys.modules, {"torch": _torch(free_mb=100)}):
        result = run_preflight(min_free_vram_mb=2500, model_name="nvidia/parakeet-unified-en-0.6b")
    assert result.passed is False
    assert "VRAM" in result.reason


def test_preflight_gates_session_start_on_no_gpu():
    with patch.dict(sys.modules, {"torch": _torch(available=False)}):
        result = run_preflight(min_free_vram_mb=2500, model_name="nvidia/parakeet-unified-en-0.6b")
    assert result.passed is False
    assert "no CUDA" in result.reason


def test_preflight_fails_closed_without_torch():
    with patch.dict("sys.modules", {"torch": None}):
        result = run_preflight(min_free_vram_mb=2500, model_name="nvidia/parakeet-unified-en-0.6b")
    assert result.passed is False
