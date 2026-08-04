"""R-SAF-02: only PolicyEngine may call OBSOrchestrator.execute(). Enforced by
grepping the production source tree (codirector/, not tests/ or tools/, both
of which legitimately exercise OBSOrchestrator directly in isolation) for the
call pattern and asserting it appears in exactly one file."""
import re
from pathlib import Path

CODIRECTOR_ROOT = Path(__file__).resolve().parents[2] / "codirector"
_EXECUTE_CALL_RE = re.compile(r"\bself\._orchestrator\.execute\(|\borchestrator\.execute\(")


def test_single_execute_caller():
    call_sites = []
    for path in CODIRECTOR_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if _EXECUTE_CALL_RE.search(text):
            call_sites.append(path.relative_to(CODIRECTOR_ROOT))

    assert call_sites == [Path("policy") / "engine.py"], (
        f"OBSOrchestrator.execute() must only be called from policy/engine.py, "
        f"found call sites in: {call_sites}"
    )
