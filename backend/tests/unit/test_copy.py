"""R-CTX-07: no prompt, log, or UI string may claim gameplay awareness — D-3
removed gameplay capture entirely, so any such claim would be false
(marketing constraint arising from D-3, §1).

Scoped to actual *generated copy* (frontend UI strings, the reasoning
mock's rationale/response-angle templates, persona copy) rather than the
whole source tree — internal code comments and docstrings that explain
*why* gameplay support doesn't exist (this file included) legitimately use
these words and aren't user-facing claims.
"""
import re
from pathlib import Path

BANNED_TERMS = ("gameplay", "clutch", "in-game", "in game", "match state", "kill", "boss", "round")
# Two deliberate carve-outs: "kill switch" is this product's own safety
# feature name (unrelated to a gameplay kill-claim), and Python's builtin
# round(...) shows up throughout scoring/mock code as ordinary syntax, not
# copy. Both are excluded by pattern rather than by removing the term
# entirely, so a real "nice kill!"-style string would still be caught.
_WORD_RE = re.compile(
    r"\bkill\b(?![\s-]*switch)|\bround\b(?!\()|" + "|".join(re.escape(t) for t in BANNED_TERMS if t != "kill" and t != "round"),
    re.IGNORECASE,
)

REPO_ROOT = Path(__file__).resolve().parents[2].parent  # repository root
COPY_SOURCES = [
    *(REPO_ROOT / "frontend" / "src").rglob("*.tsx"),
    *(REPO_ROOT / "frontend" / "src").rglob("*.ts"),
    REPO_ROOT / "backend" / "codirector" / "adapters" / "reasoning" / "mock.py",
    *(REPO_ROOT / "config" / "personas").glob("*.yaml"),
]


def test_no_gameplay_claims_in_strings():
    offenders = []
    for path in COPY_SOURCES:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        matches = _WORD_RE.findall(text)
        if matches:
            offenders.append((str(path), matches))
    assert offenders == [], f"gameplay-awareness claim found in generated copy: {offenders}"
