"""R-ASR-04, against the real preflight module. This session's sandbox does
have a real NVIDIA GPU + torch install (see CLAUDE.md), so the "passes"
branch below is genuinely exercised on hardware, not just mocked."""
from unittest.mock import patch

from codirector.adapters.asr.preflight import run_preflight


def test_preflight_passes_on_this_machine():
    result = run_preflight(min_free_vram_mb=2500, model_name="nvidia/parakeet-unified-en-0.6b")
    assert result.passed is True
    assert "compute_capability" in result.checks


def test_preflight_gates_session_start_on_insufficient_vram():
    with patch("torch.cuda.is_available", return_value=True), patch(
        "torch.cuda.mem_get_info", return_value=(100 * 1024 * 1024, 16 * 1024 * 1024 * 1024)
    ):
        result = run_preflight(min_free_vram_mb=2500, model_name="nvidia/parakeet-unified-en-0.6b")
    assert result.passed is False
    assert "VRAM" in result.reason


def test_preflight_gates_session_start_on_no_gpu():
    with patch("torch.cuda.is_available", return_value=False):
        result = run_preflight(min_free_vram_mb=2500, model_name="nvidia/parakeet-unified-en-0.6b")
    assert result.passed is False
    assert "no CUDA" in result.reason


def test_preflight_fails_closed_without_torch():
    with patch.dict("sys.modules", {"torch": None}):
        result = run_preflight(min_free_vram_mb=2500, model_name="nvidia/parakeet-unified-en-0.6b")
    assert result.passed is False
