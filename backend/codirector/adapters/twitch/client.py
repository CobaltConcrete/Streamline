"""Real Twitch adapter — build spec v1.0 §5.3. Chat over IRC (twitchio);
subs/resubs/raids/cheers over the same IRC connection's tagged messages
(USERNOTICE for subs/resubs/raids, PRIVMSG `bits` tag for cheers) — twitchio
2.x's EventSub support requires a public HTTPS webhook endpoint, which is out
of scope for a local-desktop POC (§1 D-9: single PC, no inbound networking).

The parsing/normalization functions below are pure (no I/O) specifically so
they can be unit-tested without a network call (§0: "No network call to a
real third party in unit or integration tests. Ever."). TwitchAdapter itself
wires those pure functions to twitchio.Client's callbacks.
"""
import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress

import twitchio

from codirector.core.backpressure import BoundedDropOldestQueue
from codirector.core.events import ChatMessageEvent, HealthEvent, SupportEvent, Trust

_SUB_MSG_IDS = {"sub": "support.sub", "resub": "support.resub"}


class MissingTwitchCredentialsError(RuntimeError):
    pass


def create_twitch_adapter(channel: str, oauth_token: str | None = None) -> "TwitchAdapter":
    """Create the read-only Twitch IRC adapter from explicit or env credentials."""
    if oauth_token is None:
        from codirector.config.loader import get_twitch_token

        oauth_token = get_twitch_token()
    normalized_channel = channel.strip().lstrip("#")
    if not normalized_channel or normalized_channel == "your_channel":
        raise MissingTwitchCredentialsError("set TWITCH_CHANNEL to the broadcaster login")
    if not oauth_token:
        raise MissingTwitchCredentialsError(
            "set TWITCH_USER_ACCESS_TOKEN to a user token with chat:read scope"
        )
    return TwitchAdapter(channel=normalized_channel, oauth_token=oauth_token)


def normalize_chat_message(*, message_id: str, user_id: str, display_name: str, text: str,
                            is_subscriber: bool, is_moderator: bool, event_time: float) -> ChatMessageEvent:
    now = time.monotonic()
    return ChatMessageEvent(
        event_id=message_id,
        event_time=event_time,
        ingest_time=now,
        wall_time="1970-01-01T00:00:00.000Z",
        trust=Trust.VIEWER,
        user_id=user_id,
        display_name=display_name,
        text=text,
        is_subscriber=is_subscriber,
        is_moderator=is_moderator,
    )


def normalize_cheer(*, message_id: str, user_id: str, display_name: str, text: str,
                     bits: int, event_time: float) -> SupportEvent:
    now = time.monotonic()
    return SupportEvent(
        event_id=message_id,
        event_time=event_time,
        ingest_time=now,
        wall_time="1970-01-01T00:00:00.000Z",
        trust=Trust.PLATFORM_VERIFIED,
        type="support.cheer",
        user_id=user_id,
        display_name=display_name,
        message=text,
        amount=bits,
    )


def normalize_usernotice(tags: dict, event_time: float) -> SupportEvent | None:
    """Handles sub/resub/raid USERNOTICE payloads. Returns None for
    USERNOTICE sub-types we don't model (e.g. gift subs, ritual messages)."""
    msg_id = tags.get("msg-id", "")
    notice_event_id = tags.get("id") or str(uuid.uuid4())
    user_id = tags.get("user-id", "")
    display_name = tags.get("display-name", user_id)
    now = time.monotonic()

    if msg_id in _SUB_MSG_IDS:
        months = tags.get("msg-param-cumulative-months")
        return SupportEvent(
            event_id=notice_event_id,
            event_time=event_time,
            ingest_time=now,
            wall_time="1970-01-01T00:00:00.000Z",
            trust=Trust.PLATFORM_VERIFIED,
            type=_SUB_MSG_IDS[msg_id],
            user_id=user_id,
            display_name=display_name,
            message=tags.get("system-msg"),
            amount=int(months) if months else None,
            tier=tags.get("msg-param-sub-plan"),
        )
    if msg_id == "raid":
        viewers = tags.get("msg-param-viewerCount")
        return SupportEvent(
            event_id=notice_event_id,
            event_time=event_time,
            ingest_time=now,
            wall_time="1970-01-01T00:00:00.000Z",
            trust=Trust.PLATFORM_VERIFIED,
            type="support.raid",
            user_id=user_id,
            display_name=display_name,
            message=None,
            amount=int(viewers) if viewers else None,
        )
    return None


class TwitchAdapter:
    def __init__(self, channel: str, oauth_token: str, queue_maxsize: int = 1000) -> None:
        self._channel = channel
        self._queue: BoundedDropOldestQueue = BoundedDropOldestQueue(maxsize=queue_maxsize)
        self._seen_ids: set[str] = set()  # R-CHT-02: dedupe by Twitch message id
        self._status = "down"
        self._detail = "not connected"
        self._client_task: asyncio.Task | None = None
        adapter = self

        class _InnerClient(twitchio.Client):
            async def event_ready(self_inner):
                adapter._status = "ok"
                adapter._detail = "connected"

            async def event_message(self_inner, message: twitchio.Message):
                if message.echo:
                    return
                msg_id = message.tags.get("id") if message.tags else None
                bits = message.tags.get("bits") if message.tags else None
                event_time = time.monotonic()
                if bits:
                    event = normalize_cheer(
                        message_id=msg_id or str(uuid.uuid4()),
                        user_id=str(message.author.id),
                        display_name=message.author.display_name or message.author.name,
                        text=message.content,
                        bits=int(bits),
                        event_time=event_time,
                    )
                else:
                    event = normalize_chat_message(
                        message_id=msg_id or str(uuid.uuid4()),
                        user_id=str(message.author.id),
                        display_name=message.author.display_name or message.author.name,
                        text=message.content,
                        is_subscriber=bool(getattr(message.author, "is_subscriber", False)),
                        is_moderator=bool(getattr(message.author, "is_mod", False)),
                        event_time=event_time,
                    )
                adapter._ingest(event)

            async def event_raw_usernotice(self_inner, channel, tags: dict):
                event = normalize_usernotice(tags, time.monotonic())
                if event is not None:
                    adapter._ingest(event)

            async def event_error(self_inner, error, data=None):
                adapter._status = "degraded"
                adapter._detail = f"twitch client error: {error}"

        self._client = _InnerClient(token=oauth_token, initial_channels=[channel])

    def _ingest(self, event: ChatMessageEvent | SupportEvent) -> None:
        if event.event_id in self._seen_ids:  # R-CHT-02
            return
        self._seen_ids.add(event.event_id)
        self._queue.put_nowait(event)  # R-CHT-03

    async def connect(self) -> None:
        if self._client_task is not None and not self._client_task.done():
            return
        self._client_task = asyncio.create_task(self._client.start(), name="twitchio-client")
        self._client_task.add_done_callback(self._client_stopped)

    def _client_stopped(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self._status = "down"
            self._detail = f"connection failed: {error}"

    async def events(self) -> AsyncIterator[ChatMessageEvent | SupportEvent]:
        while True:
            yield await self._queue.get()

    async def disconnect(self) -> None:
        await self._client.close()
        if self._client_task is not None:
            with suppress(asyncio.CancelledError):
                await self._client_task
        self._status = "down"
        self._detail = "disconnected"

    @property
    def drop_count(self) -> int:
        return self._queue.drop_count

    @property
    def health(self) -> HealthEvent:
        now = time.monotonic()
        return HealthEvent(
            event_id=str(uuid.uuid4()),
            event_time=now,
            ingest_time=now,
            wall_time="1970-01-01T00:00:00.000Z",
            trust=Trust.SYSTEM,
            component="twitch",
            status=self._status,
            detail=f"{self._detail} (dropped={self.drop_count})",
        )
