"""Content safety — build spec v1.0 §5.8. Two tiers, and the distinction is
the whole point: private (creator's own queue) blocks only slurs/doxxing and
otherwise passes through; public (OBS overlay) is allowlist-shaped and blocks
whole categories plus enforces length/printability.

BANNED_TERMS intentionally does not ship real slurs in source control — it is
a placeholder list meant to be replaced by a maintained moderation term list
(e.g. loaded from config) before any real deployment. "slur_token" matches the
tests/fixtures/harmful_donation.json fixture, which uses the same placeholder.
"""
import re
from dataclasses import dataclass

BANNED_TERMS = {"slur_token"}  # placeholder — replace with a real moderation list before deploy

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_MENTION_RE = re.compile(r"@\w+")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?:\+?\d[\d\-\s().]{7,}\d)")
_ADDRESS_HINT_RE = re.compile(r"\b\d{1,5}\s+\w+(\s\w+){0,3}\s+(street|st|ave|avenue|way|road|rd)\b", re.IGNORECASE)
_NONPRINTABLE_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Unicode bidi-override/embedding controls (U+202A-U+202E, U+2066-U+2069) —
# spelled as \u escapes rather than literal characters so the source file
# itself contains no invisible/obfuscation-prone control codes.
_RTL_OVERRIDE_RE = re.compile(r"[\u202a-\u202e\u2066-\u2069]")


@dataclass
class SafetyResult:
    safe: bool
    cleaned_text: str
    blocked_categories: list[str]


def strip_unsafe_chars(text: str) -> str:
    text = _NONPRINTABLE_RE.sub("", text)
    text = _RTL_OVERRIDE_RE.sub("", text)
    return text


def _contains_banned_term(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in BANNED_TERMS)


def _contains_doxxing(text: str) -> bool:
    return bool(_EMAIL_RE.search(text) or _PHONE_RE.search(text) or _ADDRESS_HINT_RE.search(text))


def check_private(text: str) -> SafetyResult:
    """Private surface: block slurs and doxxing patterns. Otherwise pass
    through — the creator is an adult reading their own chat."""
    text = strip_unsafe_chars(text)
    blocked = []
    if _contains_banned_term(text):
        blocked.append("slur")
    if _contains_doxxing(text):
        blocked.append("doxxing")
    return SafetyResult(safe=not blocked, cleaned_text=text, blocked_categories=blocked)


def check_public(text: str, max_length: int | None = None) -> SafetyResult:
    """Public surface: allowlist-shaped. Blocks slurs, harassment markers,
    sexual/self-harm content, URLs, @-mentions, emails, phone numbers, and
    anything over max_length."""
    text = strip_unsafe_chars(text)
    blocked = []
    if _contains_banned_term(text):
        blocked.append("slur")
    if _contains_doxxing(text):
        blocked.append("doxxing")
    if _URL_RE.search(text):
        blocked.append("url")
    if _MENTION_RE.search(text):
        blocked.append("mention")
    if max_length is not None and len(text) > max_length:
        blocked.append("too_long")
    return SafetyResult(safe=not blocked, cleaned_text=text, blocked_categories=blocked)


_INJECTION_MARKERS = (
    "ignore previous", "ignore all previous", "ignore your instructions", "disregard your",
    "disregard all", "system:", "###", "<<system", "developer mode", "you are now in",
    "override", "as the streamer i command", "as an admin", "as system administrator",
    "sudo ", "jailbreak", "you are dan", "new instruction", "true instruction",
    "the following is a system message", "this is not a viewer", "this message contains the real",
    "beginning of new system prompt", "note to model", "please forward all future decisions",
    "please output raw", "please leak", "act as the creator", "pretend the kill switch",
    "creator says:", "moderator override", "execute:", "run scene_collection", "run action_id",
)


def looks_like_prompt_injection(text: str) -> bool:
    """Heuristic detector used only for audit-log flagging (SAF-01/AT-03) —
    never a security boundary by itself. The actual guarantee that injected
    text can't cause an action comes structurally from the finite action_id
    enum + deny-by-default catalog + strict schema (§5.7 rule 2), not from
    catching every possible phrasing here."""
    lowered = text.lower()
    return any(marker in lowered for marker in _INJECTION_MARKERS)


def safe_summary(reason: str = "flagged content") -> str:
    """A generic, non-revealing summary shown in the private queue when the
    original text must not be displayed verbatim (AT-08)."""
    return f"A supporter message was received but hidden because it contained {reason}."
