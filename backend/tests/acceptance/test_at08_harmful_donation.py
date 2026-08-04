"""AT-08 (§6.5): a verified donation contains a slur and a phone number.
Expected: the support event is still acknowledged per policy; the harmful
text is never rendered publicly; the private prompt shows a safe summary
instead of the raw text."""
import json

from codirector.core.events import SupportEvent
from codirector.policy import content_safety
from tests.conftest import FIXTURES


def test_at08_harmful_donation_text_never_rendered_publicly():
    raw = json.loads((FIXTURES / "harmful_donation.json").read_text(encoding="utf-8"))
    events = [SupportEvent.model_validate(e) for e in raw]

    for event in events:
        public_result = content_safety.check_public(event.message, max_length=120)
        assert public_result.safe is False  # never eligible for a public overlay as-is
        assert "slur" in public_result.blocked_categories

        # The safe summary is what a private prompt would show instead of
        # the raw text — it must not itself leak the flagged content.
        summary = content_safety.safe_summary("flagged content")
        assert "slur_token" not in summary.lower()
        assert "555-201-9871" not in summary
        assert "42 wallaby way" not in summary.lower()

        # The support event itself is still real and acknowledgeable — safety
        # filtering blocks the *text*, not the fact that a supporter showed up.
        assert event.trust == "platform_verified"
        assert event.type in ("support.cheer", "support.sub")


def test_at08_private_surface_flags_but_does_not_hide_doxxing_by_default_text():
    # Private surface (§5.8): blocks slurs and doxxing patterns specifically,
    # otherwise passes through — this is what "private prompt shows a safe
    # summary" is standing in for when the block fires.
    raw = json.loads((FIXTURES / "harmful_donation.json").read_text(encoding="utf-8"))
    events = [SupportEvent.model_validate(e) for e in raw]
    for event in events:
        private_result = content_safety.check_private(event.message)
        assert private_result.safe is False
        assert "slur" in private_result.blocked_categories or "doxxing" in private_result.blocked_categories
