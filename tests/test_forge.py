from __future__ import annotations

from collections import deque
from pathlib import Path

import pytest

from budget import BudgetExceeded, BudgetManager
from config import Settings
from forge import (
    CRITIC_PROMPT,
    GENERATOR_PROMPT,
    KNOWLEDGE_CARD_FIELD_SEMANTIC_CLASSES,
    KNOWLEDGE_CARD_FIELD_SEMANTICS,
    SOURCE_FIDELITY_PROMPT,
    _build_parser,
    ForgeRunStatus,
    KnowledgeCardCritic,
    KnowledgeCardGenerator,
    KnowledgeDeduplicator,
    KnowledgeForge,
    KnowledgeValidator,
    SourceFidelityGate,
)
from knowledge_store import FidelityReviewStatus, SQLiteKnowledgeStore
from llm import (
    IncompleteLLMResponse,
    InvalidLLMResponse,
    LLMResponseMetadata,
    LLMTransportError,
    StructuredLLMResult,
    UsageDetails,
)
from memory import SQLiteMemoryStore
from pricing import PricingCatalog
from schemas import (
    AgentName,
    CriticDecision,
    GeneratedKnowledgeCards,
    KnowledgeCard,
    KnowledgeCardCritique,
    KnowledgeCardDraft,
    KnowledgeCardStatus,
    KnowledgeSourceType,
    KnowledgeTopic,
    SourceFidelityCheckedFields,
    SourceFidelityReview,
)
from source_ingestion import SourceChunkStatus, SourceIngestor


class FakeStructuredLLM:
    def __init__(self, outputs: list[object]) -> None:
        self.outputs = deque(outputs)
        self.calls = 0

    async def ask_structured(
        self,
        agent,
        system_prompt,
        user_input,
        response_model,
        context="",
        max_output_tokens=None,
        verbosity=None,
    ) -> StructuredLLMResult:
        self.calls += 1
        output = self.outputs.popleft()
        if isinstance(output, Exception):
            raise output
        return StructuredLLMResult(
            output=output,
            usage=UsageDetails(input_tokens=10, output_tokens=5, total_tokens=15),
        )


class FailOnAuthorization:
    def __init__(self, delegate: BudgetManager, fail_on: int) -> None:
        self.delegate = delegate
        self.fail_on = fail_on
        self.calls = 0

    def authorize_call(self, **kwargs):
        self.calls += 1
        if self.calls == self.fail_on:
            raise BudgetExceeded("simulated exhausted forge budget")
        return self.delegate.authorize_call(**kwargs)

    def finalize(self, reservation, usage):
        return self.delegate.finalize(reservation, usage)

    def cancel(self, reservation):
        return self.delegate.cancel(reservation)


def valid_draft(title: str = "Attribute control is not execution") -> KnowledgeCardDraft:
    return KnowledgeCardDraft(
        subtopic="attribute-context",
        title=title,
        tags=["dom", "xss", "attribute"],
        triggers=["setattribute", "attribute context"],
        principle=(
            "When controllable data reaches an HTML attribute, distinguish attribute "
            "control from an executable browser context."
        ),
        questions_to_ask=["Which attribute and parser context receive the value?"],
        false_positive_traps=["Treating setAttribute reachability as script execution."],
        evidence_required=["Parsed DOM context and separately demonstrated behavior."],
        confidence=0.86,
    )


def critique(
    decision: CriticDecision,
    *,
    revised: KnowledgeCardDraft | None = None,
) -> KnowledgeCardCritique:
    payload: dict[str, object] = {
        "decision": decision,
        "reasons": [f"critic chose {decision.value}"],
    }
    if decision == CriticDecision.REVISE:
        payload["revised_card"] = revised
    return KnowledgeCardCritique(critique=payload)


def fidelity_review(decision: str) -> SourceFidelityReview:
    issues = []
    if decision == "fail":
        issues = [
            {
                "field": "evidence_required",
                "classification": "stronger_than_source",
                "reason": "The card imports a more specific proof mechanism.",
            }
        ]
    return SourceFidelityReview(
        review={
            "decision": decision,
            "checked_fields": {
                field: True for field in SourceFidelityCheckedFields.model_fields
            },
            "issues": issues,
        }
    )


def setup_forge(
    tmp_path: Path,
    outputs: list[object],
    *,
    settings: Settings | None = None,
    store: SQLiteKnowledgeStore | None = None,
    memory: SQLiteMemoryStore | None = None,
    budget_override=None,
) -> tuple[KnowledgeForge, SQLiteKnowledgeStore, SQLiteMemoryStore, FakeStructuredLLM]:
    config = settings or Settings(
        database_path=tmp_path / "forge.db",
        specialist_model="mock-model",
        max_output_tokens=256,
    )
    local_memory = memory or SQLiteMemoryStore(config.database_path)
    local_store = store or SQLiteKnowledgeStore(
        config.database_path, config.max_knowledge_fragments
    )
    fake = FakeStructuredLLM(outputs)
    budget = budget_override or BudgetManager(local_memory, config, PricingCatalog())
    forge = KnowledgeForge(
        store=local_store,
        memory=local_memory,
        generator=KnowledgeCardGenerator(fake, budget, config),
        critic=KnowledgeCardCritic(fake, budget, config),
        validator=KnowledgeValidator(config.max_card_chars),
        deduplicator=KnowledgeDeduplicator(),
        settings=config,
        fidelity_gate=SourceFidelityGate(fake, budget, config),
    )
    return forge, local_store, local_memory, fake


def ingest(
    tmp_path: Path,
    store: SQLiteKnowledgeStore,
    content: str,
    *,
    name: str = "source.md",
):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    document, chunks = SourceIngestor(200).ingest_file(
        path,
        agent=AgentName.IKIT,
        source_type=KnowledgeSourceType.ACADEMY,
        topic=KnowledgeTopic.DOM,
    )
    store.save_document(document, chunks)
    return document, chunks


def test_source_chunking_preserves_provenance(tmp_path: Path) -> None:
    path = tmp_path / "dom.md"
    path.write_text(
        "# Source\n\n" + "source text " * 30 + "\n\n## Sink\n\n" + "sink text " * 30,
        encoding="utf-8",
    )
    document, chunks = SourceIngestor(200).ingest_file(
        path,
        agent=AgentName.IKIT,
        source_type=KnowledgeSourceType.ACADEMY,
        topic=KnowledgeTopic.DOM,
    )

    assert len(chunks) >= 4
    assert all(chunk.document_id == document.id for chunk in chunks)
    assert all(chunk.source_reference == document.source_reference for chunk in chunks)
    assert all(len(chunk.content) <= 200 for chunk in chunks)
    assert {chunk.heading for chunk in chunks} == {"Source", "Sink"}
    assert [chunk.sequence for chunk in chunks] == list(range(len(chunks)))


@pytest.mark.asyncio
async def test_candidate_is_not_approved_without_critic_and_validation(tmp_path: Path) -> None:
    forge, store, _, _ = setup_forge(
        tmp_path,
        [GeneratedKnowledgeCards(cards=[valid_draft()])],
    )
    document, _ = ingest(tmp_path, store, "# DOM\n\nAttribute control is observed.")

    result = await forge.build(document.id, critic_enabled=False)

    cards = store.list_cards()
    assert result.status == ForgeRunStatus.COMPLETED
    assert len(cards) == 1
    assert cards[0].status == KnowledgeCardStatus.CANDIDATE


@pytest.mark.asyncio
async def test_generator_may_retain_zero_cards(tmp_path: Path) -> None:
    forge, store, _, _ = setup_forge(
        tmp_path,
        [GeneratedKnowledgeCards(cards=[])],
    )
    document, _ = ingest(tmp_path, store, "# Navigation\n\nNo reusable security content.")

    result = await forge.build(document.id)

    assert result.status == ForgeRunStatus.COMPLETED
    assert result.processed_chunks == 1
    assert store.list_cards() == []


@pytest.mark.asyncio
async def test_critic_reject_keeps_card_rejected(tmp_path: Path) -> None:
    forge, store, _, _ = setup_forge(
        tmp_path,
        [
            GeneratedKnowledgeCards(cards=[valid_draft()]),
            critique(CriticDecision.REJECT),
        ],
    )
    document, _ = ingest(tmp_path, store, "# DOM\n\nAttribute control is observed.")

    await forge.build(document.id)

    card = store.list_cards()[0]
    review = store.get_card_review(card.id)
    assert card.status == KnowledgeCardStatus.REJECTED
    assert review is not None
    assert review.critic_decision == CriticDecision.REJECT


@pytest.mark.asyncio
async def test_disabled_fidelity_gate_preserves_existing_approval_path(
    tmp_path: Path,
) -> None:
    forge, store, _, fake = setup_forge(
        tmp_path,
        [
            GeneratedKnowledgeCards(cards=[valid_draft()]),
            critique(CriticDecision.APPROVE),
        ],
    )
    document, _ = ingest(tmp_path, store, "# DOM\n\nAttribute control is observed.")

    await forge.build(document.id)

    card = store.list_cards()[0]
    assert fake.calls == 2
    assert card.status == KnowledgeCardStatus.APPROVED
    assert store.get_fidelity_review(card.id) is None


@pytest.mark.asyncio
async def test_fidelity_fail_preserves_candidate_and_blocks_auto_approval(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_path=tmp_path / "forge.db",
        specialist_model="mock-model",
        max_output_tokens=256,
        source_fidelity_gate_enabled=True,
    )
    forge, store, _, _ = setup_forge(
        tmp_path,
        [
            GeneratedKnowledgeCards(cards=[valid_draft()]),
            critique(CriticDecision.APPROVE),
            fidelity_review("fail"),
        ],
        settings=settings,
    )
    document, _ = ingest(tmp_path, store, "# DOM\n\nAttribute control is observed.")

    result = await forge.build(document.id)

    card = store.list_cards()[0]
    fidelity = store.get_fidelity_review(card.id)
    assert result.status == ForgeRunStatus.COMPLETED
    assert card.status == KnowledgeCardStatus.CANDIDATE
    assert fidelity is not None
    assert fidelity.status == FidelityReviewStatus.FAIL
    assert fidelity.issues[0].field.value == "evidence_required"


@pytest.mark.asyncio
async def test_fidelity_pass_continues_normal_approval_path(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "forge.db",
        specialist_model="mock-model",
        max_output_tokens=256,
        source_fidelity_gate_enabled=True,
    )
    forge, store, _, _ = setup_forge(
        tmp_path,
        [
            GeneratedKnowledgeCards(cards=[valid_draft()]),
            critique(CriticDecision.APPROVE),
            fidelity_review("pass"),
        ],
        settings=settings,
    )
    document, _ = ingest(tmp_path, store, "# DOM\n\nAttribute control is observed.")

    await forge.build(document.id)

    card = store.list_cards()[0]
    fidelity = store.get_fidelity_review(card.id)
    assert card.status == KnowledgeCardStatus.APPROVED
    assert fidelity is not None
    assert fidelity.status == FidelityReviewStatus.PASS


@pytest.mark.asyncio
async def test_retryable_fidelity_stage_resumes_without_generator_or_critic(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_path=tmp_path / "forge.db",
        specialist_model="mock-model",
        max_output_tokens=256,
        source_fidelity_gate_enabled=True,
    )
    forge, store, memory, first_fake = setup_forge(
        tmp_path,
        [
            GeneratedKnowledgeCards(cards=[valid_draft()]),
            critique(CriticDecision.APPROVE),
            IncompleteLLMResponse(
                "fidelity output reached its ceiling",
                usage=UsageDetails(input_tokens=20, output_tokens=256, total_tokens=276),
                metadata=LLMResponseMetadata(
                    response_id="resp_fidelity_retry",
                    response_status="incomplete",
                    incomplete_reason="max_output_tokens",
                ),
                retryable=True,
            ),
        ],
        settings=settings,
    )
    document, _ = ingest(tmp_path, store, "# DOM\n\nAttribute control is observed.")

    first = await forge.build(document.id)

    card = store.list_cards()[0]
    fidelity = store.get_fidelity_review(card.id)
    assert first.status == ForgeRunStatus.RETRYABLE
    assert first_fake.calls == 3
    assert card.status == KnowledgeCardStatus.CANDIDATE
    assert fidelity is not None
    assert fidelity.status == FidelityReviewStatus.RETRYABLE

    resumed, _, _, resumed_fake = setup_forge(
        tmp_path,
        [fidelity_review("pass")],
        settings=settings,
        store=store,
        memory=memory,
    )
    second = await resumed.build(document.id)

    assert second.status == ForgeRunStatus.COMPLETED
    assert resumed_fake.calls == 1
    assert store.get_card(card.id).status == KnowledgeCardStatus.APPROVED


@pytest.mark.parametrize("confidence", [0.9, 0.0])
@pytest.mark.asyncio
async def test_card_confidence_does_not_block_source_bounded_approval(
    tmp_path: Path,
    confidence: float,
) -> None:
    draft = valid_draft().model_copy(update={"confidence": confidence})
    forge, store, _, _ = setup_forge(
        tmp_path,
        [
            GeneratedKnowledgeCards(cards=[draft]),
            critique(CriticDecision.APPROVE),
        ],
    )
    document, _ = ingest(
        tmp_path,
        store,
        """# Attribute context

Controlling an attribute through setAttribute proves reachability, not executable
JavaScript. Inspect the exact browser parsing context before concluding XSS. Ask
which attribute and parser context receive the value. Treating setAttribute
reachability as script execution is a false positive; require parsed DOM context
and separately demonstrated behavior.
""",
    )

    await forge.build(document.id)

    card = store.list_cards()[0]
    review = store.get_card_review(card.id)
    assert card.status == KnowledgeCardStatus.APPROVED
    assert card.confidence == confidence
    assert review is not None
    assert review.revision_count == 0


@pytest.mark.asyncio
async def test_critic_revision_is_limited(tmp_path: Path) -> None:
    revised_once = valid_draft("Revised attribute-context principle")
    revised_twice = valid_draft("A second revision must not loop")
    settings = Settings(
        database_path=tmp_path / "forge.db",
        specialist_model="mock-model",
        max_output_tokens=256,
        max_card_revisions=1,
    )
    forge, store, _, fake = setup_forge(
        tmp_path,
        [
            GeneratedKnowledgeCards(cards=[valid_draft()]),
            critique(CriticDecision.REVISE, revised=revised_once),
            critique(CriticDecision.REVISE, revised=revised_twice),
        ],
        settings=settings,
    )
    document, _ = ingest(tmp_path, store, "# DOM\n\nAttribute control is observed.")

    await forge.build(document.id)

    card = store.list_cards()[0]
    review = store.get_card_review(card.id)
    assert fake.calls == 3
    assert card.status == KnowledgeCardStatus.REJECTED
    assert review is not None
    assert review.revision_count == 1
    assert "Maximum card revisions" in (review.rejection_reason or "")


def test_malformed_card_is_rejected() -> None:
    result = KnowledgeValidator(2500).validate(
        {
            "id": "not-a-uuid",
            "agent": "ikit",
            "topic": "unknown-topic",
            "title": "Malformed",
            "principle": "",
        }
    )

    assert not result.accepted
    assert result.errors[0].startswith("schema_violation")


def test_oversized_card_is_rejected() -> None:
    card = KnowledgeCard(
        agent=AgentName.IKIT,
        topic=KnowledgeTopic.DOM,
        subtopic="attribute-context",
        title="Oversized card",
        source_type=KnowledgeSourceType.ACADEMY,
        source_title="Synthetic source",
        source_reference="local.md",
        source_chunk_id="35ea6d95-6bd8-4ce9-b176-61a5ba7355a6",
        tags=["dom"],
        triggers=["attribute"],
        principle="x" * 600,
        questions_to_ask=["What context is parsed?"],
    )

    result = KnowledgeValidator(500).validate(card)

    assert not result.accepted
    assert any(error.startswith("oversized_card") for error in result.errors)


def test_generator_schema_rejects_more_than_three_cards() -> None:
    with pytest.raises(ValueError, match="at most 3"):
        GeneratedKnowledgeCards(cards=[valid_draft(str(index)) for index in range(4)])


def test_generator_prompt_limits_output_to_zero_through_three_cards() -> None:
    normalized = " ".join(GENERATOR_PROMPT.casefold().split())
    assert "zero to three" in normalized
    assert "prefer fewer high-density cards" in normalized
    assert "zero cards is correct" in normalized
    assert "merely to summarize prose" in normalized
    assert "academy material must not invent research-only" in normalized


def test_generator_prompt_is_strictly_source_bounded() -> None:
    normalized = " ".join(GENERATOR_PROMPT.casefold().split())
    assert "every factual or mechanistic claim" in normalized
    assert "must be supported by the current source chunk" in normalized
    assert "do not fill gaps from general or pretrained websec knowledge" in normalized
    assert "mitigations, browser behavior, contexts, attack paths, headers, apis" in normalized
    assert "empty lists are preferable" in normalized
    assert "speculative_extensions is the only field allowed" in normalized
    assert "explicitly speculative" in normalized


def test_critic_prompt_removes_unsupported_pretrained_knowledge() -> None:
    normalized = " ".join(CRITIC_PROMPT.casefold().split())
    assert "verify source support field by field" in normalized
    assert "faithful abstraction" in normalized
    assert "inference directly supported by the chunk" in normalized
    assert "unsupported pretrained-model knowledge" in normalized
    assert "must not survive into an approved card" in normalized
    assert "requires revise or reject" in normalized
    assert "speculative_extensions is the only field permitted" in normalized
    assert "do not punish a concise card" in normalized
    assert "apply the rule for each field's class" in normalized
    assert "distinguish claim strength from the act of asking or observing" in normalized
    assert "semantic relevance rather than lexical identity" in normalized
    assert "justified adjacency rather than current curriculum availability" in normalized
    assert "general websec correctness is not sufficient" in normalized
    assert "one to four short reasons" in normalized
    assert "never emit successive variants" in normalized
    assert "repeated punctuation" in normalized
    assert "whitespace padding" in normalized
    assert "close the object immediately" in normalized
    assert "any reviewed field containing an unauthorized claim or relationship requires revise or reject" in normalized
    for field in (
        "subtopic",
        "title",
        "tags",
        "triggers",
        "principle",
        "questions_to_ask",
        "false_positive_traps",
        "evidence_required",
        "escalation_topics",
        "technique_assumptions",
        "prerequisites",
        "demonstrated_behavior",
    ):
        assert field in normalized


def test_prompts_define_confidence_as_non_source_bounded_model_metadata() -> None:
    generator = " ".join(GENERATOR_PROMPT.casefold().split())
    critic = " ".join(CRITIC_PROMPT.casefold().split())

    assert "confidence is forge/model metadata" in generator
    assert "source need not state or justify the numeric value" in generator
    assert "confidence is forge/model metadata" in critic
    assert "not a factual statement or a source-derived numeric claim" in critic
    assert "never revise or reject solely" in critic
    assert "confidence such as 0.0 or 0.9 is absent from the source" in critic
    assert "any confidence implication" not in critic


def test_prompts_define_source_bounded_evidence_required() -> None:
    for prompt in (GENERATOR_PROMPT, CRITIC_PROMPT):
        normalized = " ".join(prompt.casefold().split())
        assert "evidence that would substantiate the card's claimed mechanism" in normalized
        assert "need not literally prescribe" in normalized or "may use observation verbs" in normalized
        assert (
            "introduce no new mechanism" in normalized
            or "introduces a new mechanism" in normalized
        )
        assert "no stronger" in normalized
        assert "mutually inappropriate alternative outcomes" in normalized
        assert "reflection" in normalized
        assert "demonstrated execution" in normalized


def test_authoritative_field_semantics_classifies_every_knowledge_card_field() -> None:
    assert set(KNOWLEDGE_CARD_FIELD_SEMANTIC_CLASSES) == set(KnowledgeCard.model_fields)
    assert KNOWLEDGE_CARD_FIELD_SEMANTIC_CLASSES["evidence_required"] == (
        "DERIVED_OPERATIONAL"
    )
    assert KNOWLEDGE_CARD_FIELD_SEMANTIC_CLASSES["tags"] == "SEMANTIC_LABEL"
    assert KNOWLEDGE_CARD_FIELD_SEMANTIC_CLASSES["escalation_topics"] == (
        "ROUTING_METADATA"
    )
    assert KNOWLEDGE_CARD_FIELD_SEMANTIC_CLASSES["confidence"] == "FORGE_METADATA"
    assert KNOWLEDGE_CARD_FIELD_SEMANTIC_CLASSES["source_chunk_id"] == (
        "PROVENANCE_STATE"
    )

    for prompt in (GENERATOR_PROMPT, CRITIC_PROMPT, SOURCE_FIDELITY_PROMPT):
        assert KNOWLEDGE_CARD_FIELD_SEMANTICS in prompt


def test_derived_operational_contract_separates_wrapper_from_factual_payload() -> None:
    shared = " ".join(KNOWLEDGE_CARD_FIELD_SEMANTICS.casefold().split())
    generator = " ".join(GENERATOR_PROMPT.casefold().split())
    critic = " ".join(CRITIC_PROMPT.casefold().split())
    gate = " ".join(SOURCE_FIDELITY_PROMPT.casefold().split())

    assert "only the operational framing may be introduced" in shared
    assert "the semantic payload inside that framing may not be invented" in shared
    assert "the source modality must be preserved" in shared
    assert "a descriptive proposition p may become a check whether p" in shared
    assert "prescription p may become a check" in shared
    assert "does not assert that p is already implemented" in shared
    assert "identify payload and modality semantically, not by matching keywords" in shared
    assert "authentication or session qualifier" in shared
    assert "request/response path" in shared
    assert "guarantee" in shared

    assert "when constructing a derived_operational item" in generator
    assert "whether its modality is descriptive or normative" in generator
    assert "checking whether the relevant implementation conforms" in generator
    assert "do not turn that prescription into an assertion" in generator
    assert "never hide a new factual mechanism" in generator
    assert "do not mechanically reinterpret a prescription" in critic
    assert "preserves both payload and modality" in critic
    assert "revise or reject when it imports new specificity" in critic
    assert "check 1 — operational derivation" in gate
    assert "check 2 — factual payload and modality" in gate
    assert "do not reinterpret a prescription as an unconditional descriptive assertion" in gate
    assert "does not assert that the prescribed behavior is already implemented" in gate
    assert "pass the item only if both checks succeed" in gate

    assert "revise or reject when its payload" not in generator
    assert "pass the item only if both checks succeed" not in critic


def test_modality_preservation_is_shared_but_role_behavior_stays_distinct() -> None:
    generator = " ".join(GENERATOR_PROMPT.casefold().split())
    critic = " ".join(CRITIC_PROMPT.casefold().split())
    gate = " ".join(SOURCE_FIDELITY_PROMPT.casefold().split())

    assert "may be operationalized by checking" in generator
    assert "revise or reject" not in generator
    assert "revise or reject" in critic
    assert "pass the item only if both checks succeed" in gate
    assert "do not repair, rewrite, or improve the card" in gate


def test_build_cli_accepts_explicit_retry_failed_option() -> None:
    args = _build_parser().parse_args(
        ["build", "d3e1c635-64cf-4f03-8235-0d67dad9a24d", "--retry-failed"]
    )
    assert args.retry_failed is True


@pytest.mark.asyncio
async def test_budget_failure_preserves_progress_and_resume_skips_processed_chunks(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_path=tmp_path / "forge.db",
        specialist_model="mock-model",
        max_output_tokens=256,
    )
    memory = SQLiteMemoryStore(settings.database_path)
    store = SQLiteKnowledgeStore(settings.database_path, settings.max_knowledge_fragments)
    delegate = BudgetManager(memory, settings, PricingCatalog())
    gate = FailOnAuthorization(delegate, fail_on=2)
    first_forge, _, _, first_fake = setup_forge(
        tmp_path,
        [GeneratedKnowledgeCards(cards=[valid_draft("First chunk")])],
        settings=settings,
        store=store,
        memory=memory,
        budget_override=gate,
    )
    document, chunks = ingest(
        tmp_path,
        store,
        "# First\n\n" + "first evidence " * 6 + "\n\n# Second\n\n" + "second evidence " * 6,
    )

    stopped = await first_forge.build(document.id, critic_enabled=False)

    states = store.list_chunks(document.id)
    assert stopped.status == ForgeRunStatus.BUDGET_EXHAUSTED
    assert [chunk.status for chunk in states] == [
        SourceChunkStatus.PROCESSED,
        SourceChunkStatus.PENDING,
    ]
    assert len(store.list_cards()) == 1
    assert first_fake.calls == 1

    resumed_forge, _, _, resumed_fake = setup_forge(
        tmp_path,
        [GeneratedKnowledgeCards(cards=[valid_draft("Second chunk")])],
        settings=settings,
        store=store,
        memory=memory,
    )
    resumed = await resumed_forge.build(document.id, critic_enabled=False)

    assert resumed.run_id == stopped.run_id
    assert resumed.status == ForgeRunStatus.COMPLETED
    assert resumed.processed_chunks == len(chunks)
    assert resumed_fake.calls == 1
    assert len(store.list_cards()) == 2


@pytest.mark.asyncio
async def test_deduplication_preserves_additional_source_provenance(tmp_path: Path) -> None:
    draft = valid_draft()
    forge, store, _, _ = setup_forge(
        tmp_path,
        [
            GeneratedKnowledgeCards(cards=[draft]),
            critique(CriticDecision.APPROVE),
            GeneratedKnowledgeCards(cards=[draft]),
            critique(CriticDecision.APPROVE),
        ],
    )
    document, _ = ingest(
        tmp_path,
        store,
        "# First source\n\nAttribute control is observed.\n\n"
        "# Second source\n\nThe same reusable distinction is independently described.",
    )

    await forge.build(document.id)

    approved = store.list_cards(status=KnowledgeCardStatus.APPROVED)
    rejected = store.list_cards(status=KnowledgeCardStatus.REJECTED)
    assert len(approved) == 1
    assert len(rejected) == 1
    review = store.get_card_review(rejected[0].id)
    assert review is not None
    assert review.duplicate_of == approved[0].id
    assert len(store.get_card_sources(approved[0].id)) == 2


def retryable_response_error() -> InvalidLLMResponse:
    return InvalidLLMResponse(
        "malformed structured JSON",
        usage=UsageDetails(
            model="mock-model",
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
        ),
        metadata=LLMResponseMetadata(
            response_id="resp_retryable",
            response_status="completed",
            request_id="req_retryable",
            model="mock-model",
        ),
        retryable=True,
    )


@pytest.mark.asyncio
async def test_provider_400_keeps_chunk_retryable(tmp_path: Path) -> None:
    forge, store, _, _ = setup_forge(
        tmp_path,
        [
            GeneratedKnowledgeCards(cards=[valid_draft()]),
            LLMTransportError(
                "OpenAI API rejected the request with HTTP 400 "
                "(code=unsupported_parameter)"
            ),
        ],
    )
    document, _ = ingest(tmp_path, store, "# DOM\n\nAttribute control is observed.")

    result = await forge.build(document.id)

    chunk = store.list_chunks(document.id)[0]
    assert result.status == ForgeRunStatus.RETRYABLE
    assert result.retryable_chunks == 1
    assert result.failed_chunks == 0
    assert chunk.status == SourceChunkStatus.RETRYABLE
    assert chunk.error is not None
    assert "HTTP 400" in chunk.error


@pytest.mark.asyncio
async def test_retryable_chunks_are_processed_on_resumed_build(tmp_path: Path) -> None:
    forge, store, memory, _ = setup_forge(tmp_path, [retryable_response_error()])
    document, _ = ingest(tmp_path, store, "# DOM\n\nAttribute control is observed.")

    first = await forge.build(document.id, critic_enabled=False)

    assert first.status == ForgeRunStatus.RETRYABLE
    assert first.retryable_chunks == 1
    assert store.list_chunks(document.id)[0].status == SourceChunkStatus.RETRYABLE
    resumed_forge, _, _, resumed_fake = setup_forge(
        tmp_path,
        [GeneratedKnowledgeCards(cards=[valid_draft("Recovered card")])],
        settings=forge.settings,
        store=store,
        memory=memory,
    )

    resumed = await resumed_forge.build(document.id, critic_enabled=False)

    assert resumed.run_id == first.run_id
    assert resumed.status == ForgeRunStatus.COMPLETED
    assert resumed.processed_chunks == 1
    assert resumed.retryable_chunks == 0
    assert resumed_fake.calls == 1


@pytest.mark.asyncio
async def test_permanent_failed_chunks_are_not_automatically_retried(tmp_path: Path) -> None:
    forge, store, _, fake = setup_forge(
        tmp_path,
        [GeneratedKnowledgeCards(cards=[valid_draft("Must not be generated")])],
    )
    document, chunks = ingest(tmp_path, store, "# DOM\n\nPermanent application failure.")
    store.set_chunk_status(
        chunks[0].id,
        SourceChunkStatus.FAILED,
        error="permanent invariant failure",
    )

    result = await forge.build(document.id, critic_enabled=False)

    assert result.status == ForgeRunStatus.FAILED
    assert result.failed_chunks == 1
    assert fake.calls == 0
    assert store.list_chunks(document.id)[0].status == SourceChunkStatus.FAILED


@pytest.mark.asyncio
async def test_retry_failed_requeues_failures_without_touching_processed_chunks(
    tmp_path: Path,
) -> None:
    forge, store, _, fake = setup_forge(
        tmp_path,
        [GeneratedKnowledgeCards(cards=[valid_draft("Recovered failed chunk")])],
    )
    document, chunks = ingest(
        tmp_path,
        store,
        "# Processed\n\nAlready completed methodology.\n\n"
        "# Failed\n\nPreviously failed methodology.",
    )
    store.set_chunk_status(chunks[0].id, SourceChunkStatus.PROCESSED)
    store.set_chunk_status(
        chunks[1].id,
        SourceChunkStatus.FAILED,
        error="old live failure",
    )

    result = await forge.build(
        document.id,
        critic_enabled=False,
        retry_failed=True,
    )

    states = store.list_chunks(document.id)
    assert result.status == ForgeRunStatus.COMPLETED
    assert [chunk.status for chunk in states] == [
        SourceChunkStatus.PROCESSED,
        SourceChunkStatus.PROCESSED,
    ]
    assert fake.calls == 1
