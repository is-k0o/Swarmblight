from __future__ import annotations

from dataclasses import dataclass

from schemas import (
    EvidenceFact,
    EvidenceItem,
    EvidenceLevel,
    EvidenceType,
    EvaluationResult,
    FindingCandidate,
    Hypothesis,
    HypothesisStatus,
)


LEVEL_ORDER = {
    EvidenceLevel.OBSERVATION: 0,
    EvidenceLevel.CANDIDATE: 1,
    EvidenceLevel.SUPPORTED: 2,
    EvidenceLevel.DEMONSTRATED: 3,
    EvidenceLevel.CONFIRMED: 4,
}

INDEPENDENT_EVIDENCE_TYPES = {
    EvidenceType.USER_PROVIDED,
    EvidenceType.MANUAL_TEST_RESULT,
    EvidenceType.RESPONSE_COMPARISON,
    EvidenceType.CODE_VALIDATION,
}

DETERMINISTIC_EVIDENCE_TYPES = {
    EvidenceType.MANUAL_TEST_RESULT,
    EvidenceType.CODE_VALIDATION,
}

DEMONSTRATION_FACTS = {
    EvidenceFact.EXECUTION_DEMONSTRATED,
    EvidenceFact.UNAUTHORIZED_ACCESS_DEMONSTRATED,
    EvidenceFact.UNAUTHORIZED_ACTION_DEMONSTRATED,
    EvidenceFact.SERVER_ACCEPTANCE_DEMONSTRATED,
    EvidenceFact.SECURITY_IMPACT_DEMONSTRATED,
    EvidenceFact.DISCRIMINATING_TEST_PASSED,
}


@dataclass(frozen=True)
class EvaluationOutcome:
    hypothesis: Hypothesis
    evaluation: EvaluationResult
    finding: FindingCandidate | None


class EvaluationEngine:
    """Deterministic skepticism between agent claims and reviewable findings."""

    def evaluate(
        self,
        hypothesis: Hypothesis,
        evidence: list[EvidenceItem],
        observations: list[str],
    ) -> EvaluationOutcome:
        self._validate_links(hypothesis, evidence)
        supporting = [item for item in evidence if item.supports]
        contradictory = [
            item
            for item in evidence
            if not item.supports and item.evidence_type in INDEPENDENT_EVIDENCE_TYPES
        ]
        applied_rules: list[str] = []
        notes: list[str] = []

        level = self._derive_level(supporting, applied_rules)
        level = self._apply_required_evidence(
            hypothesis, supporting, level, applied_rules, notes
        )
        level = self._apply_required_facts(
            hypothesis, supporting, level, applied_rules, notes
        )
        level, force_refuted = self._apply_contradictions(
            contradictory, level, applied_rules, notes
        )

        if any(item.proposed_level == EvidenceLevel.CONFIRMED for item in evidence):
            applied_rules.append("proposed_level_is_advisory")
            notes.append("Agent-proposed confirmation has no authority over evaluation.")

        evaluated = hypothesis.model_copy(deep=True)
        evaluated.current_evidence_level = level
        evaluated.validation_notes = list(
            dict.fromkeys(hypothesis.validation_notes + notes)
        )
        if force_refuted:
            evaluated.status = HypothesisStatus.REFUTED
        elif evaluated.status not in {
            HypothesisStatus.REFUTED,
            HypothesisStatus.CLOSED,
        }:
            evaluated.status = self._status_for(level)

        finding_eligible = (
            level == EvidenceLevel.DEMONSTRATED
            and evaluated.status
            not in {HypothesisStatus.REFUTED, HypothesisStatus.CLOSED}
        )
        if level == EvidenceLevel.DEMONSTRATED and not finding_eligible:
            applied_rules.append("refuted_or_closed_hypothesis_is_not_a_finding")
            evaluated.validation_notes = list(
                dict.fromkeys(
                    evaluated.validation_notes
                    + ["Refuted or closed hypotheses cannot become finding candidates."]
                )
            )

        result = EvaluationResult(
            hypothesis_id=evaluated.id,
            evidence_level=level,
            finding_eligible=finding_eligible,
            human_review_required=True,
            applied_rules=list(dict.fromkeys(applied_rules)),
            validation_notes=evaluated.validation_notes,
        )
        finding = None
        if finding_eligible:
            finding = FindingCandidate(
                observations=observations,
                hypothesis=evaluated,
                evidence=evidence,
                evaluation=result,
            )
        return EvaluationOutcome(evaluated, result, finding)

    @staticmethod
    def _validate_links(
        hypothesis: Hypothesis, evidence: list[EvidenceItem]
    ) -> None:
        for item in evidence:
            if item.hypothesis_id != hypothesis.id:
                raise ValueError(
                    f"Evidence {item.id} is linked to {item.hypothesis_id}, not {hypothesis.id}"
                )

    @staticmethod
    def _derive_level(
        supporting: list[EvidenceItem], applied_rules: list[str]
    ) -> EvidenceLevel:
        independent = [
            item
            for item in supporting
            if item.evidence_type in INDEPENDENT_EVIDENCE_TYPES
        ]
        if not independent:
            applied_rules.append("no_independent_supporting_evidence")
            return EvidenceLevel.CANDIDATE

        demonstrated = any(
            item.evidence_type in DETERMINISTIC_EVIDENCE_TYPES
            and bool(set(item.facts) & DEMONSTRATION_FACTS)
            for item in independent
        )
        if demonstrated:
            applied_rules.append("typed_deterministic_fact_allows_demonstrated")
            return EvidenceLevel.DEMONSTRATED

        applied_rules.append("independent_evidence_allows_supported")
        return EvidenceLevel.SUPPORTED

    @staticmethod
    def _apply_required_evidence(
        hypothesis: Hypothesis,
        supporting: list[EvidenceItem],
        level: EvidenceLevel,
        applied_rules: list[str],
        notes: list[str],
    ) -> EvidenceLevel:
        required = {
            EvaluationEngine._normalize_requirement(item)
            for item in hypothesis.required_evidence
        }
        if not required:
            return level
        satisfied = {
            EvaluationEngine._normalize_requirement(requirement)
            for item in supporting
            if item.evidence_type in INDEPENDENT_EVIDENCE_TYPES
            for requirement in item.satisfies_required_evidence
        }
        missing = required - satisfied
        if not missing:
            applied_rules.append("required_evidence_explicitly_satisfied")
            return level
        applied_rules.append("required_evidence_missing")
        notes.append(
            "Required evidence not explicitly satisfied: " + ", ".join(sorted(missing))
        )
        return EvaluationEngine._cap(level, EvidenceLevel.CANDIDATE)

    @staticmethod
    def _apply_required_facts(
        hypothesis: Hypothesis,
        supporting: list[EvidenceItem],
        level: EvidenceLevel,
        applied_rules: list[str],
        notes: list[str],
    ) -> EvidenceLevel:
        required = set(hypothesis.required_facts)
        if not required:
            return level
        satisfied = {
            fact
            for item in supporting
            if item.evidence_type in INDEPENDENT_EVIDENCE_TYPES
            for fact in item.facts
        }
        missing = required - satisfied
        if not missing:
            applied_rules.append("required_typed_facts_satisfied")
            return level
        applied_rules.append("required_typed_facts_missing")
        notes.append(
            "Required typed facts missing: "
            + ", ".join(sorted(fact.value for fact in missing))
        )
        return EvaluationEngine._cap(level, EvidenceLevel.SUPPORTED)

    @staticmethod
    def _apply_contradictions(
        contradictory: list[EvidenceItem],
        level: EvidenceLevel,
        applied_rules: list[str],
        notes: list[str],
    ) -> tuple[EvidenceLevel, bool]:
        if not contradictory:
            return level, False
        applied_rules.append("contradictory_evidence_blocks_demonstrated")
        notes.append("Contradictory independent evidence prevents demonstrated status.")
        level = EvaluationEngine._cap(level, EvidenceLevel.SUPPORTED)
        strong = any(
            item.evidence_type in DETERMINISTIC_EVIDENCE_TYPES
            and EvidenceFact.HYPOTHESIS_CONTRADICTED in item.facts
            for item in contradictory
        )
        if strong:
            applied_rules.append("typed_strong_contradiction_refutes_hypothesis")
            notes.append("A deterministic result explicitly contradicts the hypothesis.")
            return EvidenceLevel.CANDIDATE, True
        return level, False

    @staticmethod
    def _normalize_requirement(value: str) -> str:
        return " ".join(value.casefold().split())

    @staticmethod
    def _cap(level: EvidenceLevel, maximum: EvidenceLevel) -> EvidenceLevel:
        return level if LEVEL_ORDER[level] <= LEVEL_ORDER[maximum] else maximum

    @staticmethod
    def _status_for(level: EvidenceLevel) -> HypothesisStatus:
        if level == EvidenceLevel.SUPPORTED:
            return HypothesisStatus.SUPPORTED
        if level == EvidenceLevel.DEMONSTRATED:
            return HypothesisStatus.NEEDS_REVIEW
        return HypothesisStatus.NEW
