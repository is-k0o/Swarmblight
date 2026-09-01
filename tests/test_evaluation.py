from uuid import uuid4

import pytest

from evaluation import EvaluationEngine
from schemas import (
    AgentName,
    EvidenceFact,
    EvidenceItem,
    EvidenceLevel,
    EvidenceType,
    Hypothesis,
    HypothesisStatus,
)


def test_observation_does_not_automatically_become_finding() -> None:
    hypothesis = Hypothesis(
        title="Unexpected response",
        description="A response differs from the expected response.",
        author_agent=AgentName.QUEEK,
    )

    outcome = EvaluationEngine().evaluate(
        hypothesis, [], ["The supplied response has status 500."]
    )

    assert outcome.evaluation.evidence_level == EvidenceLevel.CANDIDATE
    assert outcome.finding is None


def test_supported_is_not_confirmed() -> None:
    hypothesis = Hypothesis(
        title="Price invariant may be missing",
        description="The server may accept a client supplied price.",
        author_agent=AgentName.QUEEK,
    )
    evidence = EvidenceItem(
        hypothesis_id=hypothesis.id,
        source="manually supplied comparison",
        description="Two supplied responses support different totals.",
        evidence_type=EvidenceType.RESPONSE_COMPARISON,
        supports=True,
        confidence=0.8,
        proposed_level=EvidenceLevel.SUPPORTED,
    )

    outcome = EvaluationEngine().evaluate(hypothesis, [evidence], [])

    assert outcome.evaluation.evidence_level == EvidenceLevel.SUPPORTED
    assert outcome.evaluation.evidence_level != EvidenceLevel.CONFIRMED
    assert outcome.finding is None


def test_evidence_must_be_linked_to_evaluated_hypothesis() -> None:
    hypothesis = Hypothesis(
        title="Candidate",
        description="Candidate issue.",
        author_agent=AgentName.IKIT,
    )
    evidence = EvidenceItem(
        hypothesis_id=uuid4(),
        source="manual",
        description="Evidence for another hypothesis.",
        evidence_type=EvidenceType.MANUAL_TEST_RESULT,
        supports=True,
        proposed_level=EvidenceLevel.DEMONSTRATED,
    )

    with pytest.raises(ValueError, match="not"):
        EvaluationEngine().evaluate(hypothesis, [evidence], [])


def test_execution_failed_text_is_not_execution_demonstrated() -> None:
    hypothesis = Hypothesis(
        title="Potential executable sink",
        description="Execution requires deterministic proof.",
        author_agent=AgentName.IKIT,
        required_facts=[EvidenceFact.EXECUTION_DEMONSTRATED],
    )
    evidence = EvidenceItem(
        hypothesis_id=hypothesis.id,
        source="manual browser result",
        description="Execution failed because CSP blocked it.",
        evidence_type=EvidenceType.MANUAL_TEST_RESULT,
        supports=True,
        proposed_level=EvidenceLevel.CONFIRMED,
    )

    outcome = EvaluationEngine().evaluate(hypothesis, [evidence], [])

    assert outcome.evaluation.evidence_level != EvidenceLevel.DEMONSTRATED
    assert outcome.finding is None


def test_negative_unauthorized_text_does_not_satisfy_idor_fact() -> None:
    hypothesis = Hypothesis(
        title="Object authorization candidate",
        description="Cross-account access requires proof.",
        author_agent=AgentName.QUEEK,
        required_facts=[EvidenceFact.UNAUTHORIZED_ACCESS_DEMONSTRATED],
    )
    evidence = EvidenceItem(
        hypothesis_id=hypothesis.id,
        source="manual account comparison",
        description="Unauthorized access was not demonstrated.",
        evidence_type=EvidenceType.MANUAL_TEST_RESULT,
        supports=True,
        proposed_level=EvidenceLevel.DEMONSTRATED,
    )

    outcome = EvaluationEngine().evaluate(hypothesis, [evidence], [])

    assert outcome.evaluation.evidence_level != EvidenceLevel.DEMONSTRATED
    assert EvidenceFact.UNAUTHORIZED_ACCESS_DEMONSTRATED not in evidence.facts


def test_irrelevant_positive_evidence_does_not_satisfy_required_evidence() -> None:
    requirement = "unauthorized access as account B"
    hypothesis = Hypothesis(
        title="Ownership candidate",
        description="Account B may access account A's object.",
        author_agent=AgentName.QUEEK,
        required_evidence=[requirement],
    )
    evidence = EvidenceItem(
        hypothesis_id=hypothesis.id,
        source="manual request",
        description="The identifier is client-controlled.",
        evidence_type=EvidenceType.MANUAL_TEST_RESULT,
        supports=True,
        facts=[EvidenceFact.SERVER_ACCEPTANCE_DEMONSTRATED],
        proposed_level=EvidenceLevel.DEMONSTRATED,
    )

    outcome = EvaluationEngine().evaluate(hypothesis, [evidence], [])

    assert outcome.evaluation.evidence_level == EvidenceLevel.CANDIDATE
    assert "required_evidence_missing" in outcome.evaluation.applied_rules


def test_contradictory_evidence_blocks_demonstrated() -> None:
    hypothesis = Hypothesis(
        title="Candidate",
        description="A discriminating test may support this.",
        author_agent=AgentName.QUEEK,
    )
    supporting = EvidenceItem(
        hypothesis_id=hypothesis.id,
        source="manual result A",
        description="The discriminating true condition occurred.",
        evidence_type=EvidenceType.MANUAL_TEST_RESULT,
        supports=True,
        facts=[EvidenceFact.DISCRIMINATING_TEST_PASSED],
    )
    contradictory = EvidenceItem(
        hypothesis_id=hypothesis.id,
        source="manual result B",
        description="A second supplied result contradicts the first.",
        evidence_type=EvidenceType.RESPONSE_COMPARISON,
        supports=False,
    )

    outcome = EvaluationEngine().evaluate(
        hypothesis, [supporting, contradictory], []
    )

    assert outcome.evaluation.evidence_level == EvidenceLevel.SUPPORTED
    assert "contradictory_evidence_blocks_demonstrated" in outcome.evaluation.applied_rules
    assert outcome.finding is None


def test_refuted_hypothesis_cannot_create_finding_candidate() -> None:
    hypothesis = Hypothesis(
        title="Refuted candidate",
        description="This branch was already refuted.",
        author_agent=AgentName.SNIKCH,
        status=HypothesisStatus.REFUTED,
    )
    evidence = EvidenceItem(
        hypothesis_id=hypothesis.id,
        source="manual result",
        description="A deterministic fact was supplied after closure.",
        evidence_type=EvidenceType.MANUAL_TEST_RESULT,
        supports=True,
        facts=[EvidenceFact.SERVER_ACCEPTANCE_DEMONSTRATED],
    )

    outcome = EvaluationEngine().evaluate(hypothesis, [evidence], [])

    assert outcome.hypothesis.status == HypothesisStatus.REFUTED
    assert outcome.evaluation.finding_eligible is False
    assert outcome.finding is None
    assert "refuted_or_closed_hypothesis_is_not_a_finding" in outcome.evaluation.applied_rules
