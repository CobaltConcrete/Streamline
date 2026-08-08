from pathlib import Path

from codirector.api.runtime import LiveChatRuntime
from codirector.api.state import AppState
from codirector.config.loader import load_persona
from codirector.core.chat_filter import ChatCommentFilter
from codirector.core.clustering import Clusterer
from codirector.core.events import ChatMessageEvent, Trust
from codirector.core.models import Proposal, ReasoningResponse
from codirector.policy.catalog import load_catalog

ROOT = Path(__file__).resolve().parents[3]


class FakeTwitch:
    pass


class CapturingReasoning:
    def __init__(self) -> None:
        self.prompts = []

    async def propose(self, prompt):
        self.prompts.append(prompt)
        first = prompt.cluster_context[0]
        return ReasoningResponse(
            proposals=[
                Proposal(
                    cluster_id=first["cluster_id"],
                    decision_type="SURFACE",
                    action_id=None,
                    parameters={},
                    representative_text=first["representative_text"],
                    response_angle="answer the viewer question",
                    relevance=0.9,
                    rationale="timely and useful",
                )
            ]
        )


def event(event_id: str, user_id: str, text: str) -> ChatMessageEvent:
    return ChatMessageEvent(
        event_id=event_id,
        event_time=1.0,
        ingest_time=1.0,
        wall_time="2026-08-08T00:00:00Z",
        trust=Trust.VIEWER,
        user_id=user_id,
        display_name=user_id,
        text=text,
    )


def runtime(max_representatives=50, max_wait_s=10.0):
    state = AppState(
        persona=load_persona(ROOT / "config" / "personas" / "conversational.yaml"),
        catalog=load_catalog(ROOT / "config" / "action_catalog.yaml"),
    )
    reasoning = CapturingReasoning()
    live = LiveChatRuntime(
        state=state,
        twitch=FakeTwitch(),
        reasoning=reasoning,
        clusterer=Clusterer(),
        chat_filter=ChatCommentFilter(min_recognized_words=3),
        max_representative_texts=max_representatives,
        max_wait_s=max_wait_s,
    )
    return live, state, reasoning


async def test_flushes_when_representative_text_limit_is_reached():
    live, state, reasoning = runtime(max_representatives=2)

    await live.handle_chat(event("1", "alice", "what microphone are you using"), now=1.0)
    assert reasoning.prompts == []
    await live.handle_chat(event("2", "bob", "which game comes after this one"), now=2.0)

    assert len(reasoning.prompts) == 1
    assert len(reasoning.prompts[0].cluster_context) == 2
    assert state.last_batch["representative_text_count"] == 2
    assert state.analysis_results[0]["representative_text"] == "what microphone are you using"


async def test_flushes_at_ten_second_deadline():
    live, state, reasoning = runtime(max_wait_s=10.0)
    await live.handle_chat(event("1", "alice", "what microphone are you using"), now=100.0)

    assert await live.flush_if_due(now=109.99) is False
    assert await live.flush_if_due(now=110.0) is True
    assert len(reasoning.prompts) == 1
    assert state.last_batch["representative_text_count"] == 1


async def test_repeated_text_is_one_representative_with_distinct_user_count():
    live, _state, reasoning = runtime()
    text = "what microphone are you using today"
    await live.handle_chat(event("1", "alice", text), now=1.0)
    await live.handle_chat(event("2", "alice", text), now=2.0)
    await live.handle_chat(event("3", "bob", text), now=3.0)
    await live.flush_batch(now=4.0)

    context = reasoning.prompts[0].cluster_context
    assert len(context) == 1
    assert context[0]["unique_user_count"] == 2


async def test_filtered_chat_is_visible_but_never_sent_to_reasoning():
    live, state, reasoning = runtime()
    await live.handle_chat(event("1", "alice", "hello"), now=1.0)

    assert state.recent_chat[0]["accepted"] is False
    assert state.recent_chat[0]["filter_reason"] == "unintelligible"
    assert await live.flush_if_due(now=20.0) is False
    assert reasoning.prompts == []

