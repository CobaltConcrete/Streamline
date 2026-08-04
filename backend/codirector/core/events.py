"""Event schema — build spec v1.0 §4.1. Implemented verbatim except one addition
(see note on TranscriptEvent.type) required by R-ASR-02 but not spelled out in §4.1."""
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class Trust(str, Enum):
    CREATOR = "creator"  # creator mic. May express intent.
    PLATFORM_VERIFIED = "platform_verified"  # Twitch-signed events.
    VIEWER = "viewer"  # chat text. Content only, never instruction.
    SYSTEM = "system"  # our own components.


class EventBase(BaseModel):
    event_id: str  # uuid4
    event_time: float  # monotonic seconds, source-side
    ingest_time: float  # monotonic seconds, our side
    wall_time: str  # ISO-8601 UTC, for logs/display ONLY
    trust: Trust
    model_config = {"frozen": True}


class TranscriptEvent(EventBase):
    # "transcript.speech_ended" is added to the type literal beyond the spec's
    # illustrative list: R-ASR-02 requires a speech_ended marker with a monotonic
    # timestamp and §4.1 has no separate class for it. Reusing TranscriptEvent
    # (text="") keeps phase.py's single-schema dependency on this module.
    type: Literal["transcript.partial", "transcript.final", "transcript.speech_ended"]
    text: str
    channel: Literal["mic", "desktop"]
    asr_confidence: float | None = None

    @model_validator(mode="after")
    def _desktop_audio_is_never_creator_trust(self) -> "TranscriptEvent":
        # R-SAF-03, enforced at the schema level (not just adapter-code
        # discipline): desktop audio carries TTS donation readouts, which are
        # viewer-authored — it can never be Trust.CREATOR, no matter what an
        # adapter tries to construct.
        if self.channel == "desktop" and self.trust == Trust.CREATOR:
            raise ValueError("channel='desktop' transcripts can never carry Trust.CREATOR (R-SAF-03)")
        return self


class ChatMessageEvent(EventBase):
    type: Literal["chat.message"] = "chat.message"
    user_id: str
    display_name: str
    text: str
    is_subscriber: bool = False
    is_moderator: bool = False


class SupportEvent(EventBase):
    type: Literal["support.sub", "support.resub", "support.cheer", "support.raid"]
    user_id: str
    display_name: str
    message: str | None = None
    amount: int | None = None  # bits, months, or raid viewers
    tier: str | None = None


class OBSStateEvent(EventBase):
    type: Literal["obs.state"] = "obs.state"
    program_scene: str
    scenes: list[str]
    streaming: bool
    dropped_frames: int


class HealthEvent(EventBase):
    type: Literal["health.alert"] = "health.alert"
    component: str
    status: Literal["ok", "degraded", "down"]
    detail: str


Event = Annotated[
    TranscriptEvent | ChatMessageEvent | SupportEvent | OBSStateEvent | HealthEvent,
    Field(discriminator="type"),
]

# Hard rules (R-SAF-03): trust is assigned by the adapter that produced the event
# and is immutable thereafter (see EventBase.model_config frozen=True).
# TranscriptEvent(channel="desktop") is always Trust.VIEWER — desktop audio
# contains TTS donation readouts, which are viewer-authored. Only channel="mic"
# may carry Trust.CREATOR.
