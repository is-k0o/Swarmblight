from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentName(str, Enum):
    HORNED_RAT = "horned_rat"
    QUEEK = "queek"
    IKIT = "ikit"
    SNIKCH = "snikch"


class MessageType(str, Enum):
    OBSERVATION = "observation"
    HYPOTHESIS = "hypothesis"
    PEER_REVIEW = "peer_review"
    TASK_REQUEST = "task_request"
    DECISION = "decision"
    SUMMARY = "summary"


class HypothesisStatus(str, Enum):
    NEW = "new"
    TESTING = "testing"
    SUPPORTED = "supported"
    REFUTED = "refuted"
    NEEDS_REVIEW = "needs_review"
    CLOSED = "closed"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EvidenceLevel(str, Enum):
    OBSERVATION = "observation"
    CANDIDATE = "candidate"
    SUPPORTED = "supported"
    DEMONSTRATED = "demonstrated"
    CONFIRMED = "confirmed"


class EvidenceType(str, Enum):
    USER_PROVIDED = "user_provided"
    AGENT_INTERPRETATION = "agent_interpretation"
    MANUAL_TEST_RESULT = "manual_test_result"
    RESPONSE_COMPARISON = "response_comparison"
    CODE_VALIDATION = "code_validation"


class EvidenceFact(str, Enum):
    EXECUTION_DEMONSTRATED = "execution_demonstrated"
    UNAUTHORIZED_ACCESS_DEMONSTRATED = "unauthorized_access_demonstrated"
    UNAUTHORIZED_ACTION_DEMONSTRATED = "unauthorized_action_demonstrated"
    SERVER_ACCEPTANCE_DEMONSTRATED = "server_acceptance_demonstrated"
    SECURITY_IMPACT_DEMONSTRATED = "security_impact_demonstrated"
    DISCRIMINATING_TEST_PASSED = "discriminating_test_passed"
    HYPOTHESIS_CONTRADICTED = "hypothesis_contradicted"


class KnowledgeSourceType(str, Enum):
    ACADEMY = "academy"
    RESEARCH = "research"
    INTERNAL = "internal"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class KnowledgeCardStatus(str, Enum):
    CANDIDATE = "candidate"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class KnowledgeTopic(str, Enum):
    XSS = "xss"
    DOM = "dom"
    SQLI = "sqli"
    SSTI = "ssti"


class CriticDecision(str, Enum):
    APPROVE = "approve"
    REVISE = "revise"
    REJECT = "reject"


class SourceFidelityDecision(str, Enum):
    PASS = "pass"
    FAIL = "fail"


class SourceFidelityClassification(str, Enum):
    STRONGER_THAN_SOURCE = "stronger_than_source"
    UNSUPPORTED = "unsupported"


class SourceFidelityField(str, Enum):
    SUBTOPIC = "subtopic"
    TITLE = "title"
    TAGS = "tags"
    TRIGGERS = "triggers"
    PRINCIPLE = "principle"
    QUESTIONS_TO_ASK = "questions_to_ask"
    FALSE_POSITIVE_TRAPS = "false_positive_traps"
    EVIDENCE_REQUIRED = "evidence_required"
    ESCALATION_TOPICS = "escalation_topics"
    TECHNIQUE_ASSUMPTIONS = "technique_assumptions"
    PREREQUISITES = "prerequisites"
    DEMONSTRATED_BEHAVIOR = "demonstrated_behavior"


class ActionType(str, Enum):
    ANALYZE_MANUAL_DATA = "analyze_manual_data"
    STORE_RESULT = "store_result"
    REQUEST_SPECIALIST = "request_specialist"
    PROPOSE_MANUAL_TEST = "propose_manual_test"
    NETWORK_REQUEST = "network_request"
    BROWSER_AUTOMATION = "browser_automation"
    EXECUTE_PAYLOAD = "execute_payload"


class DiscriminatingTest(BaseModel):
    objective: str
    expected_if_true: str
    expected_if_false: str
    required_inputs: list[str] = Field(default_factory=list)
    risk_notes: str


class Hypothesis(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    title: str
    description: str
    author_agent: AgentName
    status: HypothesisStatus = HypothesisStatus.NEW
    priority: Priority = Priority.MEDIUM
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence_for: list[str] = Field(default_factory=list)
    evidence_against: list[str] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    required_facts: list[EvidenceFact] = Field(default_factory=list)
    current_evidence_level: EvidenceLevel = EvidenceLevel.CANDIDATE
    validation_notes: list[str] = Field(default_factory=list)
    discriminating_test: DiscriminatingTest | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AgentRequest(BaseModel):
    target_agent: AgentName
    task: str
    reason: str


class ProposedAction(BaseModel):
    action: ActionType
    description: str


class EvidenceItem(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    hypothesis_id: UUID
    source: str
    description: str
    evidence_type: EvidenceType
    supports: bool
    facts: list[EvidenceFact] = Field(default_factory=list)
    satisfies_required_evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    proposed_level: EvidenceLevel = EvidenceLevel.OBSERVATION
    created_at: datetime = Field(default_factory=utc_now)


class EvaluationResult(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    hypothesis_id: UUID
    evidence_level: EvidenceLevel
    finding_eligible: bool = False
    human_review_required: bool = True
    applied_rules: list[str] = Field(default_factory=list)
    validation_notes: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class FindingCandidate(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    observations: list[str]
    hypothesis: Hypothesis
    evidence: list[EvidenceItem]
    evaluation: EvaluationResult
    created_at: datetime = Field(default_factory=utc_now)


class Lesson(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    agent: AgentName
    title: str
    content: str
    source_hypothesis_id: UUID | None = None
    tags: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=utc_now)


class KnowledgeSchema(BaseModel):
    """Strict schema base for LLM-generated knowledge artifacts."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


KnowledgeTagText = Annotated[str, Field(min_length=1, max_length=40)]
KnowledgeFieldText = Annotated[str, Field(min_length=1, max_length=400)]
CriticReasonText = Annotated[str, Field(min_length=1, max_length=400)]


class KnowledgeCardDraft(KnowledgeSchema):
    subtopic: str = Field(default="general", min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    tags: list[KnowledgeTagText] = Field(default_factory=list, max_length=12)
    triggers: list[KnowledgeFieldText] = Field(default_factory=list, max_length=12)
    principle: str = Field(min_length=1, max_length=800)
    questions_to_ask: list[KnowledgeFieldText] = Field(default_factory=list, max_length=8)
    false_positive_traps: list[KnowledgeFieldText] = Field(
        default_factory=list, max_length=8
    )
    evidence_required: list[KnowledgeFieldText] = Field(default_factory=list, max_length=8)
    escalation_topics: list[KnowledgeTopic] = Field(default_factory=list, max_length=4)
    technique_assumptions: list[KnowledgeFieldText] = Field(
        default_factory=list, max_length=8
    )
    prerequisites: list[KnowledgeFieldText] = Field(default_factory=list, max_length=8)
    demonstrated_behavior: str = Field(default="", max_length=800)
    speculative_extensions: list[KnowledgeFieldText] = Field(
        default_factory=list, max_length=6
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "Forge-model meta-confidence that this draft is a faithful reusable "
            "abstraction. The Generator sets it initially and the Critic may "
            "recalibrate it during revision; it is not a source-derived claim."
        ),
    )

    @field_validator(
        "tags",
        "triggers",
        "questions_to_ask",
        "false_positive_traps",
        "evidence_required",
        "technique_assumptions",
        "prerequisites",
        "speculative_extensions",
    )
    @classmethod
    def list_items_must_not_be_blank(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("list items must not be blank")
        return values


class GeneratedKnowledgeCards(KnowledgeSchema):
    cards: list[KnowledgeCardDraft] = Field(default_factory=list, max_length=3)


class KnowledgeCard(KnowledgeCardDraft):
    id: UUID = Field(default_factory=uuid4)
    agent: AgentName
    topic: KnowledgeTopic
    source_type: KnowledgeSourceType
    source_title: str = Field(min_length=1, max_length=300)
    source_reference: str = Field(min_length=1, max_length=1000)
    source_chunk_id: UUID
    status: KnowledgeCardStatus = KnowledgeCardStatus.CANDIDATE
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ApproveKnowledgeCardCritique(KnowledgeSchema):
    decision: Literal[CriticDecision.APPROVE]
    reasons: list[CriticReasonText] = Field(min_length=1, max_length=4)


class RejectKnowledgeCardCritique(KnowledgeSchema):
    decision: Literal[CriticDecision.REJECT]
    reasons: list[CriticReasonText] = Field(min_length=1, max_length=4)


class ReviseKnowledgeCardCritique(KnowledgeSchema):
    decision: Literal[CriticDecision.REVISE]
    reasons: list[CriticReasonText] = Field(min_length=1, max_length=4)
    revised_card: KnowledgeCardDraft


KnowledgeCardCritiqueVariant = (
    ApproveKnowledgeCardCritique
    | RejectKnowledgeCardCritique
    | ReviseKnowledgeCardCritique
)


class KnowledgeCardCritique(KnowledgeSchema):
    """Root object wrapping a provider-compatible nested critique union."""

    critique: KnowledgeCardCritiqueVariant

    @property
    def decision(self) -> CriticDecision:
        return CriticDecision(self.critique.decision)

    @property
    def reasons(self) -> list[str]:
        return self.critique.reasons

    @property
    def revised_card(self) -> KnowledgeCardDraft | None:
        if isinstance(self.critique, ReviseKnowledgeCardCritique):
            return self.critique.revised_card
        return None


class SourceFidelityCheckedFields(KnowledgeSchema):
    """Provider-visible proof that every gate-owned card field was considered."""

    subtopic: Literal[True]
    title: Literal[True]
    tags: Literal[True]
    triggers: Literal[True]
    principle: Literal[True]
    questions_to_ask: Literal[True]
    false_positive_traps: Literal[True]
    evidence_required: Literal[True]
    escalation_topics: Literal[True]
    technique_assumptions: Literal[True]
    prerequisites: Literal[True]
    demonstrated_behavior: Literal[True]


class SourceFidelityIssue(KnowledgeSchema):
    field: SourceFidelityField
    classification: SourceFidelityClassification
    reason: str = Field(min_length=1, max_length=300)


class PassSourceFidelityReview(KnowledgeSchema):
    decision: Literal[SourceFidelityDecision.PASS]
    checked_fields: SourceFidelityCheckedFields
    issues: list[SourceFidelityIssue] = Field(max_length=0)


class FailSourceFidelityReview(KnowledgeSchema):
    decision: Literal[SourceFidelityDecision.FAIL]
    checked_fields: SourceFidelityCheckedFields
    issues: list[SourceFidelityIssue] = Field(min_length=1, max_length=8)


SourceFidelityReviewVariant = PassSourceFidelityReview | FailSourceFidelityReview


class SourceFidelityReview(KnowledgeSchema):
    """Strict, provider-compatible source-fidelity admission verdict."""

    review: SourceFidelityReviewVariant

    @property
    def decision(self) -> SourceFidelityDecision:
        return SourceFidelityDecision(self.review.decision)

    @property
    def checked_fields(self) -> SourceFidelityCheckedFields:
        return self.review.checked_fields

    @property
    def issues(self) -> list[SourceFidelityIssue]:
        return self.review.issues


class SourceFidelityItemIssue(SourceFidelityIssue):
    """An issue owned by one explicit target field/item, with no rewrite slot."""

    index: int = Field(ge=0, strict=True)


class PassSourceFidelityItemReview(KnowledgeSchema):
    index: int = Field(ge=0, strict=True)
    decision: Literal[SourceFidelityDecision.PASS]
    issues: list[SourceFidelityItemIssue] = Field(max_length=0)


class FailSourceFidelityItemReview(KnowledgeSchema):
    index: int = Field(ge=0, strict=True)
    decision: Literal[SourceFidelityDecision.FAIL]
    issues: list[SourceFidelityItemIssue] = Field(min_length=1, max_length=4)


SourceFidelityItemReview = PassSourceFidelityItemReview | FailSourceFidelityItemReview


class SourceFidelityFieldReview(KnowledgeSchema):
    """One non-empty field; exact target coverage is validated by the application."""

    field: SourceFidelityField
    item_reviews: list[SourceFidelityItemReview] = Field(min_length=1, max_length=12)


class SourceFidelityCrossFieldIssue(KnowledgeSchema):
    fields: list[SourceFidelityField] = Field(min_length=2, max_length=12)
    classification: SourceFidelityClassification
    reason: str = Field(min_length=1, max_length=300)

    @field_validator("fields")
    @classmethod
    def fields_must_be_distinct(cls, fields: list[SourceFidelityField]) -> list[SourceFidelityField]:
        if len(set(fields)) != len(fields):
            raise ValueError("cross-field issues must name distinct fields")
        return fields


class PassSourceFidelityCrossFieldReview(KnowledgeSchema):
    decision: Literal[SourceFidelityDecision.PASS]
    issues: list[SourceFidelityCrossFieldIssue] = Field(max_length=0)


class FailSourceFidelityCrossFieldReview(KnowledgeSchema):
    decision: Literal[SourceFidelityDecision.FAIL]
    issues: list[SourceFidelityCrossFieldIssue] = Field(min_length=1, max_length=8)


class SourceFidelityCrossFieldReview(KnowledgeSchema):
    """Provider-compatible root wrapping relationship-only PASS/FAIL variants."""

    review: PassSourceFidelityCrossFieldReview | FailSourceFidelityCrossFieldReview

    @property
    def decision(self) -> SourceFidelityDecision:
        return SourceFidelityDecision(self.review.decision)

    @property
    def issues(self) -> list[SourceFidelityCrossFieldIssue]:
        return self.review.issues


DEFAULT_CASCADE_QUESTIONS = [
    "How could similar behavior be detected elsewhere?",
    "Could the underlying cause enable a different attack class?",
]


class StructuredAgentResponse(BaseModel):
    agent: AgentName
    message_type: MessageType
    summary: str
    observations: list[str] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    requests: list[AgentRequest] = Field(default_factory=list)
    peer_review_request: AgentRequest | None = None
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
    cascade_questions: list[str] = Field(default_factory=list)
    priority: Priority = Priority.MEDIUM
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reasoning_summary: str
    recommended_next_steps: list[str] = Field(default_factory=list)


class SessionSummary(BaseModel):
    session_id: UUID
    open_hypotheses: int = 0
    closed_hypotheses: int = 0
    analyses_stored: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: float | None = None


class StoredMessage(BaseModel):
    id: int
    session_id: UUID
    role: str
    author: str
    content: str
    created_at: datetime
    raw_json: dict[str, Any] | None = None
