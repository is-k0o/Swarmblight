from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from openai.lib._pydantic import to_strict_json_schema
from pydantic import TypeAdapter, ValidationError

import forge
from budget import BudgetManager
from config import Settings
from forge import (
    DecomposedSourceFidelityGate,
    KNOWLEDGE_CARD_FIELD_SEMANTICS,
    SOURCE_FIDELITY_CROSS_FIELD_PROMPT,
    SOURCE_FIDELITY_FIELD_PROMPT,
    _decomposed_review_units,
    _run_decomposed_fidelity_checks,
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
    SourceFidelityCrossFieldReview,
    SourceFidelityField,
    SourceFidelityFieldReview,
    SourceFidelityItemReview,
)
from source_ingestion import SourceChunk, SourceDocument


def item_review(index=0, decision="pass", field="evidence_required"):
    return {
        "index": index,
        "decision": decision,
        "issues": [] if decision == "pass" else [{
            "field": field, "index": index, "classification": "unsupported",
            "reason": "This item omits a required constraint.",
        }],
    }


def cross_review(decision="pass"):
    return {"review": {
        "decision": decision,
        "issues": [] if decision == "pass" else [{
            "fields": ["principle", "evidence_required"],
            "classification": "unsupported",
            "reason": "The evidence targets a different proposition from the principle.",
        }],
    }}


@pytest.mark.parametrize("decision,issues,valid", [
    ("pass", [], True), ("pass", item_review(decision="fail")["issues"], False),
    ("fail", [], False), ("fail", item_review(decision="fail")["issues"], True),
])
def test_item_schema_decision_requires_corresponding_issue_cardinality(decision, issues, valid):
    adapter = TypeAdapter(SourceFidelityItemReview)
    value = {"index": 0, "decision": decision, "issues": issues}
    if valid:
        assert adapter.validate_python(value).decision == decision
    else:
        with pytest.raises(ValidationError):
            adapter.validate_python(value)


@pytest.mark.parametrize("index", [-1, True, "0", 0.5])
def test_item_indices_must_be_nonnegative_strict_integers(index):
    with pytest.raises(ValidationError):
        TypeAdapter(SourceFidelityItemReview).validate_python(item_review(index))


@pytest.mark.parametrize("change", ["pass_with_issue", "fail_without_issue", "one_field", "same_field_twice", "excluded_field", "long_reason"])
def test_cross_field_schema_rejects_malformed_relationships(change):
    value = cross_review("fail")
    if change == "pass_with_issue":
        value["review"]["decision"] = "pass"
    elif change == "fail_without_issue":
        value["review"]["issues"] = []
    elif change == "one_field":
        value["review"]["issues"][0]["fields"] = ["principle"]
    elif change == "same_field_twice":
        value["review"]["issues"][0]["fields"] = ["principle", "principle"]
    elif change == "excluded_field":
        value["review"]["issues"][0]["fields"] = ["principle", "confidence"]
    else:
        value["review"]["issues"][0]["reason"] = "x" * 301
    with pytest.raises(ValidationError):
        SourceFidelityCrossFieldReview.model_validate(value)


def test_provider_schemas_are_strict_objects_with_no_rewrite_fields():
    def visit(node):
        if isinstance(node, dict):
            assert "oneOf" not in node
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["properties"]) == set(node["required"])
                assert not {"value", "rewritten_item", "revised_card"} & set(node["properties"])
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    for model in (SourceFidelityFieldReview, SourceFidelityCrossFieldReview):
        schema = to_strict_json_schema(model)
        assert schema["type"] == "object" and "anyOf" not in schema
        visit(schema)
    schema = to_strict_json_schema(SourceFidelityFieldReview)
    assert schema["$defs"]["PassSourceFidelityItemReview"]["properties"]["issues"]["maxItems"] == 0
    assert schema["$defs"]["FailSourceFidelityItemReview"]["properties"]["issues"]["minItems"] == 1
    for model, value in (
        (SourceFidelityFieldReview, {"field": "title", "item_reviews": [item_review()]}),
        (SourceFidelityCrossFieldReview, cross_review()),
    ):
        value["revised_card"] = {}
        with pytest.raises(ValidationError):
            model.model_validate(value)


def make_card(*, all_fields=False):
    document = SourceDocument(
        id=uuid4(), title="Supplied document", content="Context.\n\nThe application stores a value and later displays it.",
        source_type=KnowledgeSourceType.MANUAL, source_reference="local-diagnostic-source",
        topic=KnowledgeTopic.XSS,
    )
    chunk = SourceChunk(
        id=uuid4(), document_id=document.id, heading="Supplied chunk",
        content="The application stores a value and later displays it.",
        sequence=0, source_reference=document.source_reference,
    )
    card = KnowledgeCard(
        agent=AgentName.IKIT, topic=KnowledgeTopic.XSS,
        subtopic="stored value", title="Value display", principle=chunk.content,
        evidence_required=[
            "Confirm the stored value is displayed.",
            "Confirm the stored value is always displayed.",
            "Confirm the stored value is displayed unchanged — café.",
        ],
        confidence=0.9, speculative_extensions=["An isolated speculation."],
        source_type=document.source_type, source_title=document.title,
        source_reference=document.source_reference, source_chunk_id=chunk.id,
        status=KnowledgeCardStatus.APPROVED,
    )
    if all_fields:
        for name in ("tags", "triggers", "questions_to_ask", "false_positive_traps", "technique_assumptions", "prerequisites"):
            setattr(card, name, ["stored", "value"])
        card.escalation_topics = [KnowledgeTopic.DOM, KnowledgeTopic.XSS]
        card.demonstrated_behavior = "The value is displayed."
    return card, document, chunk


def test_decomposition_covers_exactly_all_twelve_fields_and_preserves_values():
    card, _, _ = make_card(all_fields=True)
    original = card.model_dump(mode="json")
    units = _decomposed_review_units(card)
    assert set(units) == set(SourceFidelityCheckedFields.model_fields)
    assert len(units) == 12
    for name, items in units.items():
        value = original[name]
        expected = value if isinstance(value, list) else [value]
        assert items == [{"index": i, "value": text} for i, text in enumerate(expected)]
    assert units["escalation_topics"] == [{"index": 0, "value": "dom"}, {"index": 1, "value": "xss"}]
    assert "confidence" not in units and "speculative_extensions" not in units
    assert card.model_dump(mode="json") == original


def field_result(payload):
    return {"field": payload["target_field"], "item_reviews": [
        item_review(item["index"], field=payload["target_field"])
        for item in payload["target_items"]
    ]}


class FakeBackend:
    def __init__(self, transform=None):
        self.calls = []
        self.transform = transform

    async def ask_structured(self, **kwargs):
        payload = json.loads(kwargs["user_input"])
        self.calls.append({**kwargs, "payload": payload})
        output = field_result(payload) if "target_field" in payload else cross_review()
        if self.transform:
            output = self.transform(payload, output, len(self.calls))
        return StructuredLLMResult(
            output=output,
            usage=UsageDetails(model="mock-model", input_tokens=10, output_tokens=5, reasoning_tokens=2, total_tokens=15),
            metadata=LLMResponseMetadata(response_id=f"resp_{len(self.calls)}", response_status="completed"),
        )


class RecordingBudget(BudgetManager):
    def __init__(self, *args):
        super().__init__(*args)
        self.authorized = []

    def authorize_call(self, **kwargs):
        reservation = super().authorize_call(**kwargs)
        self.authorized.append(reservation)
        return reservation


def setup(tmp_path, transform=None, **settings_values):
    settings = Settings(_env_file=None, database_path=tmp_path / "diagnostic.db", specialist_model="mock-model", **settings_values)
    memory = SQLiteMemoryStore(settings.database_path)
    session_id = memory.create_session()
    budget = RecordingBudget(memory, settings, PricingCatalog({"mock-model": ModelPricing(1.0, 2.0)}))
    backend = FakeBackend(transform)
    return DecomposedSourceFidelityGate(backend, budget, settings), backend, budget, memory, session_id


async def check(gate, session_id, *, all_fields=False):
    return await gate.check(*make_card(all_fields=all_fields), run_id=uuid4(), session_id=session_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("all_fields,expected_calls", [(False, 5), (True, 13)])
async def test_all_items_and_relationships_pass_with_exact_context_and_budget(tmp_path, all_fields, expected_calls):
    gate, backend, budget, memory, session_id = setup(tmp_path, fidelity_max_output_tokens=600)
    card, document, chunk = make_card(all_fields=all_fields)
    original = [obj.model_dump(mode="json") for obj in (card, document, chunk)]
    result = await gate.check(card, document, chunk, run_id=uuid4(), session_id=session_id)
    report = result.to_dict()

    assert result.status == "completed" and result.decision == "pass"
    assert len(backend.calls) == expected_calls
    assert len(budget.authorized) == expected_calls
    assert report["total_usage"]["total_tokens"] == 15 * expected_calls
    assert report["total_usage"]["reasoning_tokens"] == 2 * expected_calls
    assert report["total_usage"]["actual_cost_usd"] == pytest.approx(0.000020 * expected_calls)
    assert report["usage_complete"] is True
    assert report["unreviewed_fields"] == []
    assert set(report["field_reviews"]) | set(report["skipped_empty_fields"]) == set(SourceFidelityCheckedFields.model_fields)
    assert report["cross_field_review"]["review"]["decision"] == "pass"
    for call, reservation in zip(backend.calls, budget.authorized, strict=True):
        payload = call["payload"]
        assert payload["final_card"] == original[0]
        assert payload["source_document"] == original[1]
        assert payload["source_chunk"] == original[2]
        assert call["max_output_tokens"] == reservation.max_output_tokens == 600
        assert not {"expected", "rationale", "derived_boundary", "case_id"} & set(payload)
        if "target_field" in payload:
            name = payload["target_field"]
            assert payload["target_items"] == _decomposed_review_units(card)[name]
            assert payload["semantic_class"] == forge.KNOWLEDGE_CARD_FIELD_SEMANTIC_CLASSES[name]
    assert [obj.model_dump(mode="json") for obj in (card, document, chunk)] == original
    with sqlite3.connect(memory.path) as db:
        assert db.execute("SELECT COUNT(*) FROM usage").fetchone()[0] == expected_calls
    assert budget.active_reservation_count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_index", [0, 1, 2])
async def test_each_list_position_can_fail_and_skips_cross_field(tmp_path, failed_index):
    def transform(payload, output, _):
        if payload.get("target_field") == "evidence_required":
            output["item_reviews"][failed_index] = item_review(failed_index, "fail")
        return output
    gate, backend, _, _, session_id = setup(tmp_path, transform)
    result = await check(gate, session_id)
    assert result.status == "completed" and result.decision == "fail"
    assert result.cross_field_review is None
    assert all("target_field" in call["payload"] for call in backend.calls)
    assert result.to_dict()["issues"][0]["index"] == failed_index


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["missing", "duplicate", "unexpected", "wrong_field", "wrong_issue_field", "wrong_issue_index", "pass_issue", "fail_no_issue"])
async def test_malformed_field_coverage_never_becomes_pass_and_is_accounted(tmp_path, problem):
    def transform(payload, output, _):
        if payload.get("target_field") != "evidence_required":
            return output
        if problem == "missing":
            output["item_reviews"].pop()
        elif problem == "duplicate":
            output["item_reviews"][2] = copy.deepcopy(output["item_reviews"][1])
        elif problem == "unexpected":
            output["item_reviews"][2]["index"] = 20
        elif problem == "wrong_field":
            output["field"] = "title"
        else:
            output["item_reviews"][2] = item_review(2, "fail")
            issue = output["item_reviews"][2]["issues"][0]
            if problem == "wrong_issue_field":
                issue["field"] = "title"
            elif problem == "wrong_issue_index":
                issue["index"] = 1
            elif problem == "pass_issue":
                output["item_reviews"][2]["decision"] = "pass"
            else:
                output["item_reviews"][2]["issues"] = []
        return output
    gate, _, budget, memory, session_id = setup(tmp_path, transform)
    result = await check(gate, session_id)
    assert result.status == "error" and result.decision is None
    assert result.cross_field_review is None
    assert result.calls[-1]["response_id"] == "resp_4"
    assert result.to_dict()["total_usage"]["total_tokens"] == 60
    assert result.error["target_field"] == "evidence_required"
    with sqlite3.connect(memory.path) as db:
        assert db.execute("SELECT COUNT(*) FROM usage").fetchone()[0] == 4
    assert budget.active_reservation_count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [False, True])
async def test_cross_field_failure_or_malformed_result_never_passes(tmp_path, invalid):
    def transform(payload, output, _):
        if "target_field" not in payload:
            output = cross_review("fail")
            if invalid:
                output["review"]["issues"][0]["fields"] = ["principle", "principle"]
        return output
    gate, _, _, _, session_id = setup(tmp_path, transform)
    result = await check(gate, session_id)
    assert result.status == ("error" if invalid else "completed")
    assert result.decision == (None if invalid else "fail")
    if not invalid:
        assert result.to_dict()["issues"][0]["fields"] == ["principle", "evidence_required"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["incomplete", "invalid", "cancelled", "plain_cancelled"])
async def test_provider_errors_and_cancellation_keep_budget_accounting(tmp_path, kind):
    def transform(payload, output, _):
        if kind == "cancelled":
            raise LLMAmbiguousInterruption("interrupted")
        if kind == "plain_cancelled":
            raise asyncio.CancelledError()
        error = IncompleteLLMResponse if kind == "incomplete" else InvalidLLMResponse
        raise error(
            "Provider response unusable", usage=UsageDetails(model="mock-model", input_tokens=10, output_tokens=5, total_tokens=15),
            metadata=LLMResponseMetadata(response_id="resp_error", response_status=kind, incomplete_reason="max_output_tokens" if kind == "incomplete" else None),
            retryable=True,
        )
    gate, _, budget, memory, session_id = setup(tmp_path, transform)
    result = await check(gate, session_id)
    assert result.status == ("error" if kind == "invalid" else "incomplete")
    assert result.decision is None
    cancelled = "cancelled" in kind
    assert result.to_dict()["usage_complete"] is not cancelled
    if cancelled:
        assert result.to_dict()["total_usage"]["actual_cost_usd"] is None
    else:
        assert result.to_dict()["total_usage"]["actual_cost_usd"] == pytest.approx(0.000020)
    with sqlite3.connect(memory.path) as db:
        assert db.execute("SELECT COUNT(*) FROM usage").fetchone()[0] == (0 if cancelled else 1)
        assert db.execute("SELECT COUNT(*) FROM budget_uncertain_usage").fetchone()[0] == (1 if cancelled else 0)
    assert budget.active_reservation_count() == 0


@pytest.mark.asyncio
async def test_persistence_failure_stops_with_reservation_retained(tmp_path, monkeypatch):
    gate, backend, budget, memory, session_id = setup(tmp_path)
    def fail_save(*args, **kwargs):
        raise OSError("ledger unavailable")
    monkeypatch.setattr(memory, "save_usage", fail_save)
    result = await check(gate, session_id)
    assert result.status == "error" and result.decision is None
    assert result.error["retryable"] is False
    assert len(backend.calls) == 1
    assert budget.active_reservation_count() == 1


def test_prompts_are_separate_and_existing_contract_is_unchanged():
    assert KNOWLEDGE_CARD_FIELD_SEMANTICS in SOURCE_FIDELITY_FIELD_PROMPT
    field = " ".join(SOURCE_FIDELITY_FIELD_PROMPT.casefold().split())
    cross = " ".join(SOURCE_FIDELITY_CROSS_FIELD_PROMPT.casefold().split())
    for phrase in (
        "judge only the target field", "other card fields are contextual",
        "not being certified by this call", "every supplied item index independently",
        "source licensing", "modality", "evidentiary sufficiency",
    ):
        assert phrase in field
    assert "e could be true while p is false" in field
    for phrase in ("relationships only", "does not certify individual fields", "contradictions", "joint strengthening", "scope", "modality"):
        assert phrase in cross
    for case_id in forge._load_fidelity_evaluation_cases():
        assert case_id not in SOURCE_FIDELITY_FIELD_PROMPT + SOURCE_FIDELITY_CROSS_FIELD_PROMPT
    assert "<b>Hello</b>" not in SOURCE_FIDELITY_FIELD_PROMPT + SOURCE_FIDELITY_CROSS_FIELD_PROMPT
    assert hashlib.sha256(forge.SOURCE_FIDELITY_PROMPT.encode()).hexdigest() == "2b9c4dc3fedd46efd7cbcd789a6ee703b2d0d713e2434f8ad600ab585fa4c5fa"


@pytest.mark.parametrize("repeat", [1, 5])
def test_cli_decomposed_repeat_parsing_without_a_client(repeat):
    card_id = uuid4()
    args = forge._build_parser().parse_args(["fidelity-check-decomposed", str(card_id), "--repeat", str(repeat)])
    assert args.card_id == card_id and args.repeat == repeat


@pytest.mark.parametrize("repeat", ["0", "6", "-1"])
def test_cli_decomposed_rejects_unbounded_repetitions(repeat):
    with pytest.raises(SystemExit):
        forge._build_parser().parse_args(["fidelity-check-decomposed", str(uuid4()), "--repeat", repeat])


def knowledge_snapshot(path):
    with sqlite3.connect(path) as db:
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'knowledge_%'")]
        return {
            "schema": db.execute("SELECT type, name, sql FROM sqlite_master ORDER BY type, name").fetchall(),
            "knowledge": {name: db.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall() for name in tables},
        }


def seed_existing_card(memory, session_id):
    store = SQLiteKnowledgeStore(memory.path)
    card, document, chunk = make_card()
    store.save_document(document, [chunk])
    store.save_card(card)
    run = store.create_forge_run(document.id, session_id)
    return card, document, chunk, run


@pytest.mark.asyncio
async def test_error_after_an_item_failure_takes_precedence_over_completed_fail(tmp_path):
    def transform(payload, output, _):
        if payload.get("target_field") == "title":
            output["item_reviews"][0] = item_review(0, "fail", "title")
        elif payload.get("target_field") == "evidence_required":
            output["item_reviews"].pop()
        return output
    gate, _, _, _, session_id = setup(tmp_path, transform)
    result = await check(gate, session_id)
    assert result.status == "error" and result.decision is None
    assert result.to_dict()["issues"][0]["field"] == "title"


@pytest.mark.asyncio
async def test_bad_provenance_stops_before_any_provider_call(tmp_path):
    gate, backend, budget, _, session_id = setup(tmp_path)
    card, document, chunk = make_card()
    chunk.document_id = uuid4()
    result = await gate.check(card, document, chunk, run_id=uuid4(), session_id=session_id)
    assert result.status == "error" and result.decision is None
    assert backend.calls == budget.authorized == []


@pytest.mark.asyncio
async def test_budget_denial_does_not_start_provider_or_fabricate_usage(tmp_path):
    gate, backend, budget, _, session_id = setup(tmp_path, daily_token_budget=1)
    result = await check(gate, session_id)
    assert result.status == "error" and result.decision is None
    assert result.error["type"] == "BudgetExceeded"
    assert result.error["retryable"] is False
    assert backend.calls == []
    assert budget.active_reservation_count() == 0


def test_cli_reports_independent_runs_and_preserves_all_knowledge_state(tmp_path, monkeypatch, capsys):
    run_number = 0
    def transform(payload, output, _):
        nonlocal run_number
        if payload.get("target_field") == "subtopic":
            run_number += 1
        if payload.get("target_field") == "evidence_required":
            if run_number == 1:
                raise IncompleteLLMResponse(
                    "truncated", usage=UsageDetails(model="mock-model", input_tokens=10, output_tokens=5, total_tokens=15),
                    metadata=LLMResponseMetadata(response_id="resp_truncated", response_status="incomplete", incomplete_reason="max_output_tokens"),
                    retryable=True,
                )
            if run_number == 3:
                output["item_reviews"][2] = item_review(2, "fail")
        return output
    gate, backend, _, memory, session_id = setup(tmp_path, transform)
    card, _, _, run = seed_existing_card(memory, session_id)
    before = knowledge_snapshot(memory.path)
    monkeypatch.setattr(forge, "get_settings", lambda: gate.settings)
    monkeypatch.setattr(forge, "LLMClient", lambda settings: backend)
    assert forge.main(["fidelity-check-decomposed", str(card.id), "--repeat", "3"]) == 2
    output = capsys.readouterr().out
    result = json.loads(output)
    assert "Traceback" not in output
    assert result["repeat"] == 3
    assert result["pass_count"] == result["fail_count"] == result["incomplete_count"] == 1
    assert [item["status"] for item in result["runs"]] == ["incomplete", "completed", "completed"]
    assert [item["decision"] for item in result["runs"]] == [None, "pass", "fail"]
    assert result["runs"][0]["calls"][-1]["metadata"]["incomplete_reason"] == "max_output_tokens"
    assert result["runs"][1]["calls"][0]["target_field"] == "subtopic"
    assert result["aggregation"] == "independent observations; no automatic vote"
    assert result["knowledge_state_mutated"] is result["decomposed_review_persisted"] is False
    assert "majority" not in result and "overall_decision" not in result
    assert knowledge_snapshot(memory.path) == before
    with sqlite3.connect(memory.path) as db:
        usage = db.execute("SELECT run_id FROM usage").fetchall()
        assert len(usage) == 13
        assert {row[0] for row in usage} == {str(run.id)}


@pytest.mark.asyncio
async def test_cancelled_repeat_stops_without_knowledge_writes(tmp_path):
    def transform(*args):
        raise LLMAmbiguousInterruption("interrupted")
    gate, backend, _, memory, session_id = setup(tmp_path, transform)
    card, _, _, run = seed_existing_card(memory, session_id)
    before = knowledge_snapshot(memory.path)
    result = await _run_decomposed_fidelity_checks(
        store=SQLiteKnowledgeStore.open_read_only(memory.path), gate=gate,
        card_id=card.id, run_id=run.id, session_id=session_id, repeat=5,
    )
    assert len(result["runs"]) == result["incomplete_count"] == 1
    assert len(backend.calls) == 1
    assert knowledge_snapshot(memory.path) == before


def test_unknown_card_fails_preflight_without_constructing_client(tmp_path, monkeypatch):
    gate, _, _, memory, _ = setup(tmp_path)
    SQLiteKnowledgeStore(memory.path)
    before = memory.path.read_bytes()
    monkeypatch.setattr(forge, "get_settings", lambda: gate.settings)
    def forbidden_client(*args, **kwargs):
        pytest.fail("no API client before source/card preflight")
    monkeypatch.setattr(forge, "LLMClient", forbidden_client)
    with pytest.raises(SystemExit, match="Unknown knowledge card"):
        forge.main(["fidelity-check-decomposed", str(uuid4())])
    assert memory.path.read_bytes() == before


class FakeResponsesEndpoint:
    def __init__(self, mode):
        self.mode = mode
        self.calls = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        payload, _ = json.JSONDecoder().raw_decode(kwargs["input"][1]["content"])
        value = field_result(payload) if "target_field" in payload else cross_review()
        text = json.dumps(value) if self.mode == "completed" else "{"
        body = {
            "id": f"resp_endpoint_{len(self.calls)}", "status": "incomplete" if self.mode == "incomplete" else "completed",
            "model": "mock-model", "incomplete_details": {"reason": "max_output_tokens"} if self.mode == "incomplete" else None,
            "usage": {"input_tokens": 10, "output_tokens": 5, "output_tokens_details": {"reasoning_tokens": 2}, "total_tokens": 15},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
        }
        return SimpleNamespace(request_id="req_mock", json=lambda: body)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,count,status", [("completed", 5, "completed"), ("incomplete", 1, "incomplete"), ("malformed", 1, "error")])
async def test_responses_adapter_receives_schemas_and_matching_budget_ceiling(tmp_path, mode, count, status):
    gate, _, budget, memory, session_id = setup(tmp_path)
    endpoint = FakeResponsesEndpoint(mode)
    client = SimpleNamespace(responses=SimpleNamespace(with_raw_response=SimpleNamespace(parse=endpoint.parse)))
    gate.llm = LLMClient(gate.settings, client=client)
    result = await check(gate, session_id)
    assert result.status == status
    assert result.decision == ("pass" if mode == "completed" else None)
    assert len(endpoint.calls) == count
    for call, reservation in zip(endpoint.calls, budget.authorized, strict=True):
        assert call["max_output_tokens"] == reservation.max_output_tokens == 4000
        assert call["text"] == {"verbosity": "low"}
        assert call["text_format"] in (SourceFidelityFieldReview, SourceFidelityCrossFieldReview)
    if mode == "completed":
        assert endpoint.calls[-1]["text_format"] is SourceFidelityCrossFieldReview
    with sqlite3.connect(memory.path) as db:
        assert db.execute("SELECT COUNT(*) FROM usage").fetchone()[0] == count
    assert budget.active_reservation_count() == 0


def test_fixture_corpus_remains_frozen():
    path = Path(__file__).parent / "corpus" / "knowledge_card_field_semantics_cases.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == "feb295f88e5816c701094b7b23daed2f8392a3990461317014324552a3ecb55e"
    cases = forge._load_fidelity_evaluation_cases()
    assert len(cases) == 56
    assert sum(case.expected_verdict in {"pass", "fail"} for case in cases.values()) == 54
