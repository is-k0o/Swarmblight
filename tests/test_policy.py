from pathlib import Path

import pytest

from config import Settings
from llm import LLMResult
from memory import SQLiteMemoryStore
from policy import PolicyEngine, PolicyViolation
from router import SwarmRouter
from schemas import (
    ActionType,
    AgentName,
    AgentRequest,
    MessageType,
    ProposedAction,
    StructuredAgentResponse,
)


def test_horned_rat_cannot_exceed_policy_rounds() -> None:
    policy = PolicyEngine(Settings(max_agent_rounds=1))

    policy.validate_round(1)
    with pytest.raises(PolicyViolation, match="exceeds"):
        policy.validate_round(2)


class ForbiddenActionLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def ask_agent(self, agent, system_prompt, user_input, context="") -> LLMResult:
        self.calls += 1
        return LLMResult(
            StructuredAgentResponse(
                agent=AgentName.HORNED_RAT,
                message_type=MessageType.DECISION,
                summary="Send target request.",
                reasoning_summary="Requested by coordinator.",
                proposed_actions=[
                    ProposedAction(
                        action=ActionType.NETWORK_REQUEST,
                        description="Send an autonomous target request.",
                    )
                ],
            )
        )


@pytest.mark.asyncio
async def test_horned_rat_cannot_activate_forbidden_action(tmp_path: Path) -> None:
    settings = Settings(database_path=tmp_path / "policy.db")
    memory = SQLiteMemoryStore(settings.database_path)
    fake = ForbiddenActionLLM()
    router = SwarmRouter(fake, memory, settings)

    with pytest.raises(PolicyViolation, match="forbidden"):
        await router.run(memory.create_session(), "manual data")

    assert fake.calls == 1


def test_specialist_cannot_bypass_horned_rat() -> None:
    policy = PolicyEngine(Settings())
    request = AgentRequest(
        target_agent=AgentName.SNIKCH,
        task="Review identity",
        reason="Potential overlap",
    )

    assert policy.approve_specialist_requests(AgentName.QUEEK, [request]) == []
    assert policy.approve_specialist_requests(AgentName.HORNED_RAT, [request]) == [request]
