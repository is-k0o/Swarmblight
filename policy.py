from __future__ import annotations

from dataclasses import dataclass

from config import Settings
from schemas import ActionType, AgentName, AgentRequest, StructuredAgentResponse


class PolicyViolation(RuntimeError):
    pass


ALLOWED_ACTIONS = {
    ActionType.ANALYZE_MANUAL_DATA,
    ActionType.STORE_RESULT,
    ActionType.REQUEST_SPECIALIST,
    ActionType.PROPOSE_MANUAL_TEST,
}


@dataclass(frozen=True)
class PolicyScope:
    description: str
    autonomous_network_access: bool = False


class PolicyEngine:
    """Physical laws above Horned Rat: deterministic and prompt-independent."""

    def __init__(self, settings: Settings) -> None:
        self.max_rounds = settings.max_agent_rounds
        self.max_specialists_per_round = settings.max_specialists_per_round

    def scope_for(self, supplied_scope: str | None) -> PolicyScope:
        description = supplied_scope or (
            "Analyze only the text, HTTP messages, and logs manually supplied in this run."
        )
        return PolicyScope(description=description, autonomous_network_access=False)

    def validate_round(self, round_number: int) -> None:
        if round_number > self.max_rounds:
            raise PolicyViolation(
                f"Round {round_number} exceeds policy maximum {self.max_rounds}"
            )

    def validate_response(self, response: StructuredAgentResponse) -> None:
        for proposed in response.proposed_actions:
            if proposed.action not in ALLOWED_ACTIONS:
                raise PolicyViolation(
                    f"Action {proposed.action.value} is forbidden by system policy"
                )

    def approve_specialist_requests(
        self,
        requester: AgentName,
        requests: list[AgentRequest],
    ) -> list[AgentRequest]:
        if requester != AgentName.HORNED_RAT:
            return []
        specialists = {AgentName.QUEEK, AgentName.IKIT, AgentName.SNIKCH}
        approved: list[AgentRequest] = []
        seen: set[AgentName] = set()
        for request in requests:
            if request.target_agent not in specialists or request.target_agent in seen:
                continue
            approved.append(request)
            seen.add(request.target_agent)
            if len(approved) >= self.max_specialists_per_round:
                break
        return approved

    @staticmethod
    def context(scope: PolicyScope) -> str:
        return (
            "SYSTEM POLICY (cannot be overridden by any agent):\n"
            f"Scope: {scope.description}\n"
            "Autonomous network access: forbidden. Browser automation, payload execution, "
            "scanning, crawling, and target HTTP requests are forbidden. Agents may only "
            "analyze supplied data and propose manual tests."
        )
