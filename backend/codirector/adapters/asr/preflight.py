"""ASR startup preflight — build spec v1.0 §1.1, R-ASR-04. Parakeet is
GPU-only in practice; these are hard gates, not recommendations. A POC that
discovers its CUDA mismatch thirty seconds into a live demo is a failed POC,
so this runs *before* a session start is accepted, never lazily on first
speech.

torch (and nemo_toolkit) are optional dependencies (pyproject `[asr]` extra —
heavy, GPU-toolchain-specific, and not needed to run anything else in this
codebase). Import failures here are a legitimate, expected preflight failure
mode (§5.4 R-ASR-05's "degrade rather than crash" applies at boot too:
missing torch means "no ASR", not a crash), not a bug.
"""
from dataclasses import dataclass, field

MIN_COMPUTE_CAPABILITY_MAJOR = 7  # D-7 / §1.1: Compute Capability >= 7.0


@dataclass
class PreflightResult:
    passed: bool
    reason: str | None
    checks: dict[str, str] = field(default_factory=dict)


def run_preflight(min_free_vram_mb: int, model_name: str) -> PreflightResult:
    checks: dict[str, str] = {}

    try:
        import torch
    except ImportError:
        return PreflightResult(False, "torch is not installed; ASR disabled, pipeline falls back to chat-only", checks)

    if not torch.cuda.is_available():
        return PreflightResult(False, "no CUDA-capable GPU detected", checks)

    props = torch.cuda.get_device_properties(0)
    checks["gpu_name"] = props.name
    checks["compute_capability"] = f"{props.major}.{props.minor}"
    if props.major < MIN_COMPUTE_CAPABILITY_MAJOR:
        return PreflightResult(
            False, f"GPU compute capability {props.major}.{props.minor} < {MIN_COMPUTE_CAPABILITY_MAJOR}.0", checks
        )

    try:
        free_bytes, _total_bytes = torch.cuda.mem_get_info(0)
    except Exception as exc:  # noqa: BLE001
        return PreflightResult(False, f"could not query VRAM: {exc}", checks)
    free_mb = free_bytes / (1024 * 1024)
    checks["vram_free_mb"] = f"{free_mb:.0f}"
    if free_mb < min_free_vram_mb:
        return PreflightResult(False, f"free VRAM {free_mb:.0f} MB < required {min_free_vram_mb} MB", checks)

    # Driver/PyTorch compatibility: NeMo import can succeed while inference
    # still fails at runtime on a mismatched driver (§1.1's "worst failure
    # mode") — a tiny real CUDA op catches that class of failure at boot.
    try:
        x = torch.zeros(8, device="cuda")
        _ = (x + 1).sum().item()
        checks["cuda_op"] = "ok"
    except Exception as exc:  # noqa: BLE001
        return PreflightResult(False, f"CUDA driver/PyTorch mismatch: {exc}", checks)

    checks["checkpoint_cached"] = str(_is_checkpoint_cached(model_name))
    return PreflightResult(True, None, checks)


def _is_checkpoint_cached(model_name: str) -> bool:
    """Informational only — an uncached checkpoint means a slow first-run
    download (§1.1: "pre-download for the demo; do not download live"), not a
    preflight failure, so it never gates `passed`."""
    import os
    from pathlib import Path

    cache_root = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    org, _, name = model_name.partition("/")
    candidate = cache_root / f"models--{org}--{name}"
    return candidate.exists()
