"""R-ENG-06: no chat message is ever sent to Twitch. Source-level assertion —
no call site anywhere in the production tree invokes a chat-send method."""
import re
from pathlib import Path

CODIRECTOR_ROOT = Path(__file__).resolve().parents[2] / "codirector"
_SEND_CALL_RE = re.compile(r"\.send\(|\.send_message\(|channel\.send|\.reply\(")


def test_no_chat_write_path_exists():
    offending = []
    for path in CODIRECTOR_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if _SEND_CALL_RE.search(text):
            offending.append(path.relative_to(CODIRECTOR_ROOT))
    assert offending == [], f"found a chat-send call site (R-ENG-06 violation): {offending}"


def test_twitch_adapter_never_imports_a_send_capable_client_construct():
    # Belt-and-suspenders: TwitchAdapter only ever reads from the IRC
    # connection (event_message/event_raw_usernotice); it never constructs
    # an outbound Channel/Message.send reference.
    text = (CODIRECTOR_ROOT / "adapters" / "twitch" / "client.py").read_text(encoding="utf-8")
    assert "send(" not in text
    assert "send_message(" not in text
