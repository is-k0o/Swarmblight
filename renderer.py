from __future__ import annotations

from schemas import (
    AgentName,
    FindingCandidate,
    HypothesisStatus,
    Priority,
    StructuredAgentResponse,
)

AGENT_LABELS = {
    AgentName.HORNED_RAT: "HORNED RAT — Coordinator",
    AgentName.QUEEK: "QUEEK — LogicRat",
    AgentName.IKIT: "IKIT — InjectionRat",
    AgentName.SNIKCH: "SNIKCH — IdentityRat",
}

SKAVEN_STATUS = {
    HypothesisStatus.NEW: "fresh-smell",
    HypothesisStatus.TESTING: "sniff-sniff",
    HypothesisStatus.SUPPORTED: "good-good evidence",
    HypothesisStatus.REFUTED: "dead-rat hypothesis",
    HypothesisStatus.NEEDS_REVIEW: "needs more sniff-sniff",
    HypothesisStatus.CLOSED: "bury-bury",
}


class DiscordRenderer:
    def __init__(self, skaven_level: int = 2) -> None:
        self.skaven_level = skaven_level

    def render_response(self, response: StructuredAgentResponse) -> str:
        if self.skaven_level >= 2:
            return self._render_skaven(response)
        return self._render_technical(response)

    def render_report(
        self,
        final_response: StructuredAgentResponse,
        specialist_responses: list[StructuredAgentResponse],
        finding_candidates: list[FindingCandidate] | None = None,
    ) -> str:
        sections = [self.render_response(final_response)]
        sections.extend(self.render_response(item) for item in specialist_responses)
        if finding_candidates:
            sections.append(self._render_findings(finding_candidates))
        return "\n\n".join(sections)

    def render_status(self, summary: object) -> str:
        open_count = getattr(summary, "open_hypotheses")
        closed_count = getattr(summary, "closed_hypotheses")
        analyses = getattr(summary, "analyses_stored")
        tokens = getattr(summary, "total_tokens")
        cost = getattr(summary, "estimated_cost")
        cost_text = "unavailable" if cost is None else f"${cost:.4f}"
        if self.skaven_level >= 2:
            return (
                "WARPSTONE LEDGER\n"
                f"Open scent-trails: {open_count}\n"
                f"Bury-bury hypotheses: {closed_count}\n"
                f"Stored analyses: {analyses}\n"
                f"Token usage: {tokens}\nRecorded cost: {cost_text}"
            )
        return (
            "Session status\n"
            f"Open hypotheses: {open_count}\n"
            f"Closed hypotheses: {closed_count}\n"
            f"Stored analyses: {analyses}\n"
            f"Token usage: {tokens}\nRecorded cost: {cost_text}"
        )

    def _render_technical(self, response: StructuredAgentResponse) -> str:
        lines = [f"**{AGENT_LABELS[response.agent]}**", response.summary]
        self._append_details(lines, response, skaven=False)
        return "\n".join(lines)

    def _render_skaven(self, response: StructuredAgentResponse) -> str:
        introductions = {
            AgentName.HORNED_RAT: "SILENCE-SILENCE. The swarm has decided:",
            AgentName.QUEEK: "Queek checks the server-law, yes-yes:",
            AgentName.IKIT: "Ikit traces source to sink, proof-proof:",
            AgentName.SNIKCH: "Snikch asks who is user-you:",
        }
        lines = [f"**{AGENT_LABELS[response.agent]}**", introductions[response.agent]]
        lines.append(response.summary)
        self._append_details(lines, response, skaven=True)
        return "\n".join(lines)

    @staticmethod
    def _append_details(
        lines: list[str], response: StructuredAgentResponse, *, skaven: bool
    ) -> None:
        if response.observations:
            lines.append("\nObservations:")
            lines.extend(f"- {item}" for item in response.observations)
        if response.hypotheses:
            lines.append("\nHypotheses:")
            for hypothesis in response.hypotheses:
                status = (
                    SKAVEN_STATUS[hypothesis.status]
                    if skaven
                    else hypothesis.status.value
                )
                priority = hypothesis.priority.value
                if skaven and hypothesis.priority in {Priority.HIGH, Priority.CRITICAL}:
                    priority = "BIG CHEESE"
                lines.append(
                    f"- [{status} | evidence={hypothesis.current_evidence_level.value} | "
                    f"{priority} | {hypothesis.confidence:.0%}] "
                    f"{hypothesis.title}: {hypothesis.description}"
                )
                if hypothesis.discriminating_test:
                    test = hypothesis.discriminating_test
                    lines.append(
                        f"  Test: {test.objective} | true: {test.expected_if_true} | "
                        f"false: {test.expected_if_false}"
                    )
                elif hypothesis.status not in {HypothesisStatus.REFUTED, HypothesisStatus.CLOSED}:
                    lines.append("  Test: not currently known")
        if response.evidence:
            lines.append("\nEvidence:")
            for item in response.evidence:
                facts = ", ".join(fact.value for fact in item.facts) or "none"
                lines.append(
                    f"- [proposed={item.proposed_level.value} | {item.evidence_type.value} | "
                    f"{'supports' if item.supports else 'against'} | facts={facts}] "
                    f"{item.description}"
                )
        if response.recommended_next_steps:
            lines.append("\nNext sniff-sniff:" if skaven else "\nRecommended next steps:")
            lines.extend(f"- {item}" for item in response.recommended_next_steps)
        lines.append(f"\nConfidence: {response.confidence:.0%}")
        lines.append(f"Rationale: {response.reasoning_summary}")
        if response.cascade_questions:
            lines.append("\nOptional cascade questions:")
            lines.extend(f"- {item}" for item in response.cascade_questions)

    def _render_findings(self, findings: list[FindingCandidate]) -> str:
        heading = (
            "**HUMAN REVIEW — demonstrated scent-trails**"
            if self.skaven_level >= 2
            else "**Human-reviewable finding candidates**"
        )
        lines = [heading]
        for finding in findings:
            lines.append(
                f"- [{finding.evaluation.evidence_level.value}] "
                f"{finding.hypothesis.title}: human confirmation required"
            )
        return "\n".join(lines)


def split_discord_message(text: str, limit: int = 1900) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(line) > limit:
            if current:
                chunks.append(current.rstrip())
                current = ""
            chunks.extend(line[index : index + limit] for index in range(0, len(line), limit))
        elif len(current) + len(line) > limit:
            chunks.append(current.rstrip())
            current = line
        else:
            current += line
    if current:
        chunks.append(current.rstrip())
    return chunks
