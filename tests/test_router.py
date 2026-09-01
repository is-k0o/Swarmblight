from collections import defaultdict, deque
from pathlib import Path
import sqlite3

import pytest

from config import Settings
from llm import LLMResult
from memory import MemoryStore, SQLiteMemoryStore
from renderer import DiscordRenderer
from router import SwarmRouter
from schemas import (
    AgentName,
    AgentRequest,
    EvidenceFact,
    EvidenceItem,
    EvidenceLevel,
    EvidenceType,
    Hypothesis,
    MessageType,
    StructuredAgentResponse,
)


def response(
    agent: AgentName,
    *,
    requests: list[AgentRequest] | None = None,
    summary: str = "analysis",
) -> StructuredAgentResponse:
    return StructuredAgentResponse(
        agent=agent,
        message_type=MessageType.DECISION if agent == AgentName.HORNED_RAT else MessageType.HYPOTHESIS,
        summary=summary,
        requests=requests or [],
        confidence=0.5,
        reasoning_summary="Test rationale.",
    )


def request(agent: AgentName) -> AgentRequest:
    return AgentRequest(target_agent=agent, task="Review this area", reason="Relevant evidence")


class FakeLLM:
    def __init__(self, scripted: dict[AgentName, list[StructuredAgentResponse]]) -> None:
        self.scripted = {key: deque(value) for key, value in scripted.items()}
        self.calls: defaultdict[AgentName, int] = defaultdict(int)
        self.contexts: defaultdict[AgentName, list[str]] = defaultdict(list)

    async def ask_agent(self, agent, system_prompt, user_input, context="") -> LLMResult:
        self.calls[agent] += 1
        self.contexts[agent].append(context)
        return LLMResult(response=self.scripted[agent].popleft())


def make_router(tmp_path: Path, fake: FakeLLM, rounds: int = 2) -> tuple[SwarmRouter, MemoryStore]:
    settings = Settings(
        database_path=tmp_path / "router.db",
        max_agent_rounds=rounds,
        max_specialists_per_round=3,
    )
    memory = SQLiteMemoryStore(settings.database_path)
    return SwarmRouter(fake, memory, settings), memory


@pytest.mark.asyncio
async def test_horned_rat_selects_specialist(tmp_path: Path) -> None:
    fake = FakeLLM(
        {
            AgentName.HORNED_RAT: [
                response(AgentName.HORNED_RAT, requests=[request(AgentName.QUEEK)]),
                response(AgentName.HORNED_RAT, summary="Final decision"),
            ],
            AgentName.QUEEK: [response(AgentName.QUEEK)],
        }
    )
    router, memory = make_router(tmp_path, fake)

    result = await router.run(memory.create_session(), "manual HTTP request")

    assert fake.calls[AgentName.QUEEK] == 1
    assert result.final_response.summary == "Final decision"
    assert result.rounds_used == 1
    assert "BUDGET REMAINING" in fake.contexts[AgentName.HORNED_RAT][1]


@pytest.mark.asyncio
async def test_max_agent_rounds_is_strict(tmp_path: Path) -> None:
    fake = FakeLLM(
        {
            AgentName.HORNED_RAT: [
                response(AgentName.HORNED_RAT, requests=[request(AgentName.QUEEK)]),
                response(AgentName.HORNED_RAT, requests=[request(AgentName.SNIKCH)]),
                response(AgentName.HORNED_RAT, requests=[request(AgentName.QUEEK)]),
            ],
            AgentName.QUEEK: [response(AgentName.QUEEK)],
            AgentName.SNIKCH: [response(AgentName.SNIKCH)],
        }
    )
    router, memory = make_router(tmp_path, fake, rounds=2)

    result = await router.run(memory.create_session(), "manual data")

    assert result.rounds_used == 2
    assert len(result.specialist_responses) == 2
    assert fake.calls[AgentName.QUEEK] == 1
    assert fake.calls[AgentName.SNIKCH] == 1


@pytest.mark.asyncio
async def test_specialist_request_cannot_trigger_direct_loop(tmp_path: Path) -> None:
    specialist_response = response(
        AgentName.QUEEK, requests=[request(AgentName.SNIKCH)]
    ).model_copy(update={"peer_review_request": request(AgentName.SNIKCH)})
    fake = FakeLLM(
        {
            AgentName.HORNED_RAT: [
                response(AgentName.HORNED_RAT, requests=[request(AgentName.QUEEK)]),
                response(AgentName.HORNED_RAT, summary="Peer review refused"),
            ],
            AgentName.QUEEK: [specialist_response],
        }
    )
    router, memory = make_router(tmp_path, fake)

    result = await router.run(memory.create_session(), "manual data")

    assert result.rounds_used == 1
    assert fake.calls[AgentName.SNIKCH] == 0


@pytest.mark.asyncio
async def test_complete_mock_flow_persists_evaluation_and_renders_finding(
    tmp_path: Path,
) -> None:
    hypothesis = Hypothesis(
        title="Server trusts client price",
        description="A supplied manual result shows the server retained a modified price.",
        author_agent=AgentName.QUEEK,
        required_evidence=["Authorized manual request/response comparison"],
    )
    evidence = EvidenceItem(
        hypothesis_id=hypothesis.id,
        source="manually supplied test result",
        description="The supplied response shows the modified price was accepted by the server.",
        evidence_type=EvidenceType.MANUAL_TEST_RESULT,
        supports=True,
        facts=[EvidenceFact.SERVER_ACCEPTANCE_DEMONSTRATED],
        satisfies_required_evidence=[
            "Authorized manual request/response comparison"
        ],
        confidence=0.9,
        proposed_level=EvidenceLevel.DEMONSTRATED,
    )
    specialist = StructuredAgentResponse(
        agent=AgentName.QUEEK,
        message_type=MessageType.HYPOTHESIS,
        summary="Price authority appears server-side unsafe.",
        observations=["The manually supplied response retained the modified price."],
        hypotheses=[hypothesis],
        evidence=[evidence],
        reasoning_summary="The supplied before/after pair is discriminating.",
    )
    fake = FakeLLM(
        {
            AgentName.HORNED_RAT: [
                response(AgentName.HORNED_RAT, requests=[request(AgentName.QUEEK)]),
                response(AgentName.HORNED_RAT, summary="Human review warranted"),
            ],
            AgentName.QUEEK: [specialist],
        }
    )
    router, memory = make_router(tmp_path, fake)
    session_id = memory.create_session()

    result = await router.run(session_id, "manual price request and response")

    saved = memory.get_hypothesis(hypothesis.id)
    assert saved is not None
    assert saved.current_evidence_level == EvidenceLevel.DEMONSTRATED
    assert memory.list_evidence(hypothesis.id)[0].id == evidence.id
    assert len(result.finding_candidates) == 1
    with sqlite3.connect(memory.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM findings").fetchone()[0] == 1
    rendered = DiscordRenderer(0).render_report(
        result.final_response,
        result.specialist_responses,
        result.finding_candidates,
    )
    assert "Human-reviewable finding candidates" in rendered
