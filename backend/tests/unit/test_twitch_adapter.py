"""R-CHT-01/02: normalization and dedupe. Exercises only the pure parsing
functions and TwitchAdapter._ingest — never twitchio.Client.start()/connect(),
so no network call happens (§0 rule)."""
import pytest

from codirector.adapters.twitch.client import (
    MissingTwitchCredentialsError,
    TwitchAdapter,
    create_twitch_adapter,
    normalize_chat_message,
    normalize_cheer,
    normalize_usernotice,
)
from codirector.core.events import Trust


def test_normalization_chat_message():
    event = normalize_chat_message(
        message_id="msg-1",
        user_id="123",
        display_name="SomeViewer",
        text="hello chat",
        is_subscriber=True,
        is_moderator=False,
        event_time=1.0,
    )
    assert event.trust == Trust.VIEWER
    assert event.type == "chat.message"
    assert event.is_subscriber is True
    assert event.text == "hello chat"


def test_normalization_cheer():
    event = normalize_cheer(
        message_id="msg-2", user_id="123", display_name="Cheerer", text="cheer100 nice",
        bits=100, event_time=2.0,
    )
    assert event.trust == Trust.PLATFORM_VERIFIED
    assert event.type == "support.cheer"
    assert event.amount == 100


def test_normalization_usernotice_sub():
    tags = {
        "msg-id": "sub", "id": "notice-1", "user-id": "555", "display-name": "NewSub",
        "msg-param-cumulative-months": "3", "msg-param-sub-plan": "1000",
        "system-msg": "NewSub subscribed at Tier 1.",
    }
    event = normalize_usernotice(tags, event_time=3.0)
    assert event.type == "support.sub"
    assert event.amount == 3
    assert event.tier == "1000"


def test_normalization_usernotice_raid():
    tags = {"msg-id": "raid", "id": "notice-2", "user-id": "777", "display-name": "Raider",
            "msg-param-viewerCount": "42"}
    event = normalize_usernotice(tags, event_time=4.0)
    assert event.type == "support.raid"
    assert event.amount == 42


def test_normalization_usernotice_unmodeled_returns_none():
    tags = {"msg-id": "ritual", "id": "notice-3"}
    assert normalize_usernotice(tags, event_time=5.0) is None


async def test_dedupe_by_message_id():
    # Async (even with no internal await): twitchio.Client's constructor calls
    # asyncio.get_event_loop(), which needs a running loop in this context on
    # Windows/py3.10 — a plain sync test has none by the time other async
    # tests have run and closed theirs.
    adapter = TwitchAdapter(channel="teststreamer", oauth_token="fake-token-not-used")
    event = normalize_chat_message(
        message_id="dup-1", user_id="1", display_name="A", text="hi",
        is_subscriber=False, is_moderator=False, event_time=0.0,
    )
    adapter._ingest(event)
    adapter._ingest(event)  # replay of the same Twitch message id
    assert adapter._queue.qsize() == 1


def test_factory_requires_channel_and_user_token():
    with pytest.raises(MissingTwitchCredentialsError, match="TWITCH_CHANNEL"):
        create_twitch_adapter("your_channel", "token")
    with pytest.raises(MissingTwitchCredentialsError, match="TWITCH_USER_ACCESS_TOKEN"):
        create_twitch_adapter("real_channel", "")


async def test_factory_normalizes_channel_name():
    adapter = create_twitch_adapter("#Real_Channel", "test-token")
    assert adapter._channel == "Real_Channel"
