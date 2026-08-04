"""Provider protocols — build spec v1.0 §5.1. Signatures are binding; internals
are free. Every protocol has exactly two implementations at POC: a real one and
a deterministic mock (same input -> same output, no clock, no randomness)."""
from collections.abc import AsyncIterator, Callable
from typing import Protocol

from codirector.core.events import (
    ChatMessageEvent,
    HealthEvent,
    OBSStateEvent,
    SupportEvent,
    TranscriptEvent,
)
from codirector.core.models import ReasoningResponse


class ReasoningPrompt:
    """Minimal container passed to ReasoningProvider.propose(). Not a Pydantic
    model in the spec; kept as a plain dataclass-like holder here."""

    __slots__ = ("cluster_context", "persona", "session_summary")

    def __init__(self, session_summary: str, cluster_context: list[dict], persona: dict) -> None:
        self.session_summary = session_summary
        self.cluster_context = cluster_context
        self.persona = persona


class ASRProvider(Protocol):
    async def start(self, on_event: Callable[[TranscriptEvent], None]) -> None: ...
    async def stop(self) -> None: ...

    @property
    def health(self) -> HealthEvent: ...


class ChatProvider(Protocol):
    async def connect(self) -> None: ...
    async def events(self) -> AsyncIterator[ChatMessageEvent | SupportEvent]: ...
    async def disconnect(self) -> None: ...

    @property
    def health(self) -> HealthEvent: ...


class OBSProvider(Protocol):
    async def connect(self) -> None: ...
    async def get_state(self) -> OBSStateEvent: ...
    async def set_scene(self, scene_name: str) -> None: ...
    async def set_input_text(self, input_name: str, text: str) -> None: ...
    async def set_item_visibility(self, scene: str, item_id: int, visible: bool) -> None: ...
    async def set_filter_enabled(self, source: str, filter_name: str, enabled: bool) -> None: ...


class ReasoningProvider(Protocol):
    async def propose(self, prompt: ReasoningPrompt) -> ReasoningResponse: ...
