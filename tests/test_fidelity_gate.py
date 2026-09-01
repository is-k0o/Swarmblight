from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from openai.lib._pydantic import to_strict_json_schema
from pydantic import ValidationError

from budget import BudgetManager
from config import Settings
from forge import (
    SOURCE_FIDELITY_PROMPT,
    SourceFidelityGate,
    SourceFidelityGateResult,
    _build_parser,
    _print_json,
    _run_fidelity_checks,
)
from knowledge_store import SQLiteKnowledgeStore
from llm import (
    IncompleteLLMResponse,
    InvalidLLMResponse,
    LLMAmbiguousInterruption,
    LLMClient,
    LLMResponseMetadata,
    StructuredLLMResult,
    UsageDetails,
)
from memory import SQLiteMemoryStore
from pricing import ModelPricing, PricingCatalog
from schemas import (
    AgentName,
    KnowledgeCard,
    KnowledgeCardStatus,
    KnowledgeSourceType,
    KnowledgeTopic,
    SourceFidelityCheckedFields,
    SourceFidelityReview,
)
from source_ingestion import SourceIngestor


CHECKED_FIELDS = {
    field: True for field in SourceFidelityCheckedFields.model_fields
}


def review_payload(
    decision: str,
    issues: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "review": {
            "decision": decision,
            "checked_fields": dict(CHECKED_FIELDS),
            "issues": issues or [],
        }
    }


def issue(
    classification: str = "stronger_than_source",
) -> dict[str, str]:
    return {
        "field": "evidence_required",
        "classification": classification,
        "reason": "The card requires a mechanism that the chunk does not establish.",
    }


def test_strict_pass_requires_all_fields_and_zero_issues() -> None:
    review = SourceFidelityReview.model_validate(review_payload("pass"))

    assert review.decision.value == "pass"
    assert review.issues == []
    assert set(review.checked_fields.model_fields_set) == set(CHECKED_FIELDS)


@pytest.mark.parametrize(
    "payload",
    [
        review_payload("pass", [issue()]),
        review_payload("fail"),
    ],
)
def test_decision_issue_cardinality_is_strict(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SourceFidelityReview.model_validate(payload)


@pytest.mark.parametrize(
    "classification",
    ["stronger_than_source", "unsupported"],
)
def test_fail_accepts_only_bounded_issue_classifications(
    classification: str,
) -> None:
    review = SourceFidelityReview.model_validate(
        review_payload("fail", [issue(classification)])
    )

    assert review.decision.value == "fail"
    assert review.issues[0].classification.value == classification


def test_invalid_field_and_missing_checked_field_are_rejected() -> None:
    invalid = review_payload(
        "fail",
        [
            {
                "field": "confidence",
                "classification": "unsupported",
                "reason": "Not a fidelity field.",
            }
        ],
    )
    missing = review_payload("pass")
    del missing["review"]["checked_fields"]["subtopic"]

    with pytest.raises(ValidationError):
        SourceFidelityReview.model_validate(invalid)
    with pytest.raises(ValidationError):
        SourceFidelityReview.model_validate(missing)


def test_gate_contract_cannot_return_a_revised_card() -> None:
    payload = review_payload("pass")
    payload["review"]["revised_card"] = {
        "title": "Forbidden rewrite",
        "principle": "The gate cannot edit cards.",
    }

    with pytest.raises(ValidationError):
        SourceFidelityReview.model_validate(payload)


def test_provider_schema_matches_the_strict_local_contract() -> None:
    schema = to_strict_json_schema(SourceFidelityReview)
    variants = schema["properties"]["review"]["anyOf"]
    branches = {
        schema["$defs"][variant["$ref"].rsplit("/", 1)[-1]]["properties"][
            "decision"
        ]["const"]: schema["$defs"][variant["$ref"].rsplit("/", 1)[-1]]
        for variant in variants
    }

    assert set(branches) == {"pass", "fail"}
    assert branches["pass"]["properties"]["issues"]["maxItems"] == 0
    assert branches["fail"]["properties"]["issues"]["minItems"] == 1
    assert branches["fail"]["properties"]["issues"]["maxItems"] == 8
    checked = schema["$defs"]["SourceFidelityCheckedFields"]
    assert set(checked["required"]) == set(CHECKED_FIELDS)
    assert "subtopic" in checked["properties"]
    assert "confidence" not in checked["properties"]
    assert "speculative_extensions" not in checked["properties"]
    fidelity_issue = schema["$defs"]["SourceFidelityIssue"]["properties"]
    assert fidelity_issue["reason"]["maxLength"] == 300
    field_definition = schema["$defs"][
        fidelity_issue["field"]["$ref"].rsplit("/", 1)[-1]
    ]
    assert set(field_definition["enum"]) == set(CHECKED_FIELDS)


def test_fidelity_prompt_is_narrow_adversarial_and_non_rewriting() -> None:
    normalized = " ".join(SOURCE_FIDELITY_PROMPT.casefold().split())
    for statement in (
        "general cybersecurity correctness is irrelevant",
        "the current chunk is the only authority",
        "useful advice that imports new domain knowledge also fails",
        "must not import a standard pentest proof workflow",
        "are not free advisory fields",
        "empty optional fields are better than invented content",
        "do not use pretrained websec knowledge to fill gaps",
        "if uncertain whether the chunk licenses a stronger factual or mechanistic claim, fail",
        "do not repair, rewrite, or improve the card",
    ):
        assert statement in normalized
    assert "judge the strength of the semantic payload separately" in normalized
    assert "preserve whether the source is descriptive or normative" in normalized
    assert "check 1 — operational derivation" in normalized
    assert "check 2 — factual payload" in normalized
    assert "mentally remove that framing only to compare payloads" in normalized
    assert "do not reinterpret a prescription as an unconditional descriptive assertion" in normalized
    assert "pass the item only if both checks succeed" in normalized
    assert "semantic relevance or adjacency, not literal wording" in normalized
    assert "subtopic, title, tags, triggers" in normalized
    assert "confidence is forge metadata and is excluded" in normalized
    assert "speculative_extensions is also excluded" in normalized


def test_fidelity_configuration_defaults_disabled_and_bounds_repeats() -> None:
    settings = Settings(_env_file=None)

    assert settings.source_fidelity_gate_enabled is False
    assert settings.fidelity_max_output_tokens == 4000
    assert _build_parser().parse_args(
        ["fidelity-check", str(uuid4()), "--repeat", "5"]
    ).repeat == 5
    with pytest.raises(SystemExit):
        _build_parser().parse_args(
            ["fidelity-check", str(uuid4()), "--repeat", "6"]
        )


class FakeRawResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.request_id = "req_fidelity"

    def json(self):
        return self.payload


class FakeRawEndpoint:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, object]] = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class FakeOpenAIClient:
    def __init__(self, outcome: object) -> None:
        self.endpoint = FakeRawEndpoint(outcome)
        self.responses = SimpleNamespace(
            with_raw_response=SimpleNamespace(parse=self.endpoint.parse)
        )


class RecordingBudgetManager(BudgetManager):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.authorized = []

    def authorize_call(self, **kwargs):
        reservation = super().authorize_call(**kwargs)
        self.authorized.append(reservation)
        return reservation


def response_payload(
    output_text: str,
    *,
    status: str = "completed",
    incomplete_reason: str | None = None,
) -> dict[str, object]:
    return {
        "id": "resp_fidelity",
        "status": status,
        "model": "mock-model",
        "incomplete_details": (
            {"reason": incomplete_reason} if incomplete_reason else None
        ),
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "output_tokens_details": {"reasoning_tokens": 20},
            "total_tokens": 150,
        },
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": output_text}],
            }
        ],
    }


def setup_gate(
    tmp_path: Path,
    outcome: object,
    *,
    fidelity_max_output_tokens: int | None = 1200,
):
    settings_values: dict[str, object] = {
        "_env_file": None,
        "database_path": tmp_path / "gate.db",
        "openai_api_key": "local-test-key",
        "specialist_model": "mock-model",
        "max_output_tokens": 256,
    }
    if fidelity_max_output_tokens is not None:
        settings_values["fidelity_max_output_tokens"] = fidelity_max_output_tokens
    settings = Settings(**settings_values)
    memory = SQLiteMemoryStore(settings.database_path)
    budget = RecordingBudgetManager(
        memory,
        settings,
        PricingCatalog({"mock-model": ModelPricing(1.0, 2.0)}),
    )
    api = FakeOpenAIClient(outcome)
    gate = SourceFidelityGate(LLMClient(settings, client=api), budget, settings)
    source_path = tmp_path / "source.md"
    source_path.write_text("# Source\n\nOnly this claim is supported.", encoding="utf-8")
    document, chunks = SourceIngestor(500).ingest_file(
        source_path,
        agent=AgentName.IKIT,
        source_type=KnowledgeSourceType.ACADEMY,
        topic=KnowledgeTopic.XSS,
    )
    card = KnowledgeCard(
        agent=AgentName.IKIT,
        topic=KnowledgeTopic.XSS,
        title="Supported claim",
        principle="Only this claim is supported.",
        questions_to_ask=["Is this exact claim present?"],
        source_type=document.source_type,
        source_title=document.title,
        source_reference=document.source_reference,
        source_chunk_id=chunks[0].id,
        status=KnowledgeCardStatus.CANDIDATE,
    )
    return (
        settings,
        memory,
        budget,
        api,
        gate,
        card,
        document,
        chunks[0],
        memory.create_session(),
    )


def accounting_rows(path: Path) -> tuple[int, int]:
    with sqlite3.connect(path) as connection:
        actual = connection.execute("SELECT COUNT(*) FROM usage").fetchone()[0]
        uncertain = connection.execute(
            "SELECT COUNT(*) FROM budget_uncertain_usage WHERE resolved_at IS NULL"
        ).fetchone()[0]
    return int(actual), int(uncertain)


@pytest.mark.asyncio
async def test_gate_api_and_budget_use_same_stage_limit(tmp_path: Path) -> None:
    raw = FakeRawResponse(response_payload(json.dumps(review_payload("pass"))))
    settings, _, budget, api, gate, card, document, chunk, session_id = setup_gate(
        tmp_path, raw
    )

    result = await gate.check(
        card,
        document,
        chunk,
        run_id=uuid4(),
        session_id=session_id,
    )

    assert api.endpoint.calls[0]["max_output_tokens"] == 1200
    assert api.endpoint.calls[0]["text"] == {"verbosity": "low"}
    assert budget.authorized[0].max_output_tokens == 1200
    assert settings.fidelity_max_output_tokens == 1200
    assert result.usage.reasoning_tokens == 20
    assert result.metadata.response_id == "resp_fidelity"


@pytest.mark.asyncio
async def test_gate_default_4000_reaches_api_and_budget_reservation(
    tmp_path: Path,
) -> None:
    raw = FakeRawResponse(response_payload(json.dumps(review_payload("pass"))))
    settings, _, budget, api, gate, card, document, chunk, session_id = setup_gate(
        tmp_path,
        raw,
        fidelity_max_output_tokens=None,
    )

    await gate.check(
        card,
        document,
        chunk,
        run_id=uuid4(),
        session_id=session_id,
    )

    assert settings.fidelity_max_output_tokens == 4000
    assert api.endpoint.calls[0]["max_output_tokens"] == 4000
    assert budget.authorized[0].max_output_tokens == 4000


@pytest.mark.asyncio
async def test_completed_malformed_gate_output_is_accounted_before_error(
    tmp_path: Path,
) -> None:
    raw = FakeRawResponse(
        response_payload('{"review":{"decision":"pass","issues":[]}}')
    )
    settings, _, budget, _, gate, card, document, chunk, session_id = setup_gate(
        tmp_path, raw
    )

    with pytest.raises(InvalidLLMResponse):
        await gate.check(
            card,
            document,
            chunk,
            run_id=uuid4(),
            session_id=session_id,
        )

    assert accounting_rows(settings.database_path) == (1, 0)
    assert budget.active_reservation_count() == 0


@pytest.mark.asyncio
async def test_incomplete_gate_output_is_accounted_and_retryable(tmp_path: Path) -> None:
    raw = FakeRawResponse(
        response_payload(
            '{"review":',
            status="incomplete",
            incomplete_reason="max_output_tokens",
        )
    )
    settings, _, budget, _, gate, card, document, chunk, session_id = setup_gate(
        tmp_path, raw
    )

    with pytest.raises(IncompleteLLMResponse) as caught:
        await gate.check(
            card,
            document,
            chunk,
            run_id=uuid4(),
            session_id=session_id,
        )

    assert caught.value.retryable is True
    assert accounting_rows(settings.database_path) == (1, 0)
    assert budget.active_reservation_count() == 0


@pytest.mark.asyncio
async def test_ambiguous_gate_interruption_is_accounted_pessimistically(
    tmp_path: Path,
) -> None:
    settings, _, budget, _, gate, card, document, chunk, session_id = setup_gate(
        tmp_path, LLMAmbiguousInterruption("cancelled in flight")
    )

    with pytest.raises(LLMAmbiguousInterruption):
        await gate.check(
            card,
            document,
            chunk,
            run_id=uuid4(),
            session_id=session_id,
        )

    assert accounting_rows(settings.database_path) == (0, 1)
    assert budget.active_reservation_count() == 0


class MockReadOnlyGate:
    async def check(self, *args, **kwargs) -> SourceFidelityGateResult:
        return SourceFidelityGateResult(
            review=SourceFidelityReview.model_validate(review_payload("pass")),
            usage=UsageDetails(input_tokens=1, output_tokens=1, total_tokens=2),
            metadata=LLMResponseMetadata(response_id="resp_mock"),
        )


class IncompleteThenPassGate:
    def __init__(self) -> None:
        self.calls = 0

    async def check(self, *args, **kwargs) -> SourceFidelityGateResult:
        self.calls += 1
        if self.calls == 1:
            raise IncompleteLLMResponse(
                "Provider response incomplete: max_output_tokens",
                usage=UsageDetails(
                    model="mock-model",
                    input_tokens=100,
                    output_tokens=2000,
                    reasoning_tokens=1792,
                    total_tokens=2100,
                ),
                metadata=LLMResponseMetadata(
                    response_id="resp_incomplete",
                    response_status="incomplete",
                    incomplete_reason="max_output_tokens",
                ),
                retryable=True,
            )
        return await MockReadOnlyGate().check(*args, **kwargs)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.asyncio
async def test_read_only_fidelity_harness_reports_incomplete_and_continues(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "read-only.db"
    SQLiteMemoryStore(path)
    store = SQLiteKnowledgeStore(path)
    source_path = tmp_path / "existing.md"
    source_path.write_text("# Source\n\nSupported statement.", encoding="utf-8")
    document, chunks = SourceIngestor(500).ingest_file(
        source_path,
        agent=AgentName.IKIT,
        source_type=KnowledgeSourceType.ACADEMY,
        topic=KnowledgeTopic.XSS,
    )
    store.save_document(document, chunks)
    card = KnowledgeCard(
        agent=AgentName.IKIT,
        topic=KnowledgeTopic.XSS,
        title="Supported statement",
        principle="Supported statement.",
        questions_to_ask=["Is it supported?"],
        source_type=document.source_type,
        source_title=document.title,
        source_reference=document.source_reference,
        source_chunk_id=chunks[0].id,
        status=KnowledgeCardStatus.APPROVED,
    )
    store.save_card(card)
    before = file_hash(path)

    gate = IncompleteThenPassGate()
    result = await _run_fidelity_checks(
        store=SQLiteKnowledgeStore.open_read_only(path),
        gate=gate,
        card_id=card.id,
        run_id=uuid4(),
        session_id=uuid4(),
        repeat=3,
    )
    _print_json(result)
    output = capsys.readouterr().out

    assert file_hash(path) == before
    assert result["pass_count"] == 2
    assert result["incomplete_count"] == 1
    assert gate.calls == 3
    assert result["runs"][0] == {
        "run": 1,
        "attempt": "1/3",
        "status": "incomplete",
        "reason": "max_output_tokens",
        "response_id": "resp_incomplete",
        "usage": {
            "model": "mock-model",
            "input_tokens": 100,
            "output_tokens": 2000,
            "reasoning_tokens": 1792,
            "total_tokens": 2100,
            "estimated_cost": None,
            "actual_cost_usd": None,
        },
        "reasoning_tokens": 1792,
        "retryable": True,
    }
    assert [run["status"] for run in result["runs"]] == [
        "incomplete",
        "completed",
        "completed",
    ]
    assert "Traceback" not in output
    assert result["knowledge_state_mutated"] is False
    assert result["fidelity_review_persisted"] is False
