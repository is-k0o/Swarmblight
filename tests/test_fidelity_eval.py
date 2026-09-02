from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from budget import BudgetManager
from config import Settings
from forge import (
    FidelityEvaluationBatchError,
    FidelityEvaluationCase,
    SourceFidelityGate,
    SourceFidelityGateResult,
    _build_atomic_fidelity_artifacts,
    _build_parser,
    _get_fidelity_evaluation_case,
    _load_fidelity_evaluation_cases,
    _preflight_fidelity_evaluation_cases,
    _print_json,
    _run_atomic_fidelity_evaluation,
    _run_atomic_fidelity_evaluation_batch,
)
from knowledge_store import SQLiteKnowledgeStore
from llm import (
    IncompleteLLMResponse,
    LLMClient,
    LLMResponseMetadata,
    UsageDetails,
)
from memory import SQLiteMemoryStore
from pricing import ModelPricing, PricingCatalog
from schemas import SourceFidelityCheckedFields, SourceFidelityReview


CHECKED_FIELDS = {
    field: True for field in SourceFidelityCheckedFields.model_fields
}
KNOWLEDGE_TABLES = (
    "knowledge_documents",
    "knowledge_chunks",
    "knowledge_cards",
    "knowledge_card_sources",
    "knowledge_forge_runs",
    "knowledge_fidelity_reviews",
)
CALIBRATION_CASES = {
    "derived-sqli-faithful": (
        "SQL injection is a server-side vulnerability that targets the application's database.",
        "evidence_required",
        "Confirm that SQL injection targets the application's database.",
        "pass",
    ),
    "derived-sqli-mechanism": (
        "SQL injection is a server-side vulnerability that targets the application's database.",
        "evidence_required",
        "Confirm crafted input alters SQL queries.",
        "fail",
    ),
    "derived-csrf-faithful": (
        "CSRF involves inducing a victim user to perform actions they do not intend to do.",
        "questions_to_ask",
        "Determine whether the victim was induced to perform an unintended action.",
        "pass",
    ),
    "derived-csrf-mechanism": (
        "CSRF involves inducing a victim user to perform actions they do not intend to do.",
        "evidence_required",
        "Confirm an authenticated victim action was caused by an induced request.",
        "fail",
    ),
    "derived-php-faithful": (
        "Escape your outputs with htmlentities and ENT_QUOTES for HTML contexts.",
        "evidence_required",
        "Confirm the relevant HTML output path uses htmlentities with ENT_QUOTES.",
        "pass",
    ),
    "derived-php-csp": (
        "Escape your outputs with htmlentities and ENT_QUOTES for HTML contexts.",
        "evidence_required",
        "Confirm CSP blocks JavaScript execution.",
        "fail",
    ),
}


def review(
    decision: str,
    *,
    issue_field: str | None = None,
) -> SourceFidelityReview:
    issues = []
    if issue_field is not None:
        issues.append(
            {
                "field": issue_field,
                "classification": "unsupported",
                "reason": "The fixture source does not support this target content.",
            }
        )
    return SourceFidelityReview.model_validate(
        {
            "review": {
                "decision": decision,
                "checked_fields": dict(CHECKED_FIELDS),
                "issues": issues,
            }
        }
    )


class SequenceGate:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    async def check(self, *args, **kwargs) -> SourceFidelityGateResult:
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return SourceFidelityGateResult(
            review=outcome,
            usage=UsageDetails(
                model="mock-model",
                input_tokens=10,
                output_tokens=5,
                reasoning_tokens=2,
                total_tokens=15,
            ),
            metadata=LLMResponseMetadata(response_id=f"resp_{self.calls}"),
        )


def incomplete(*, retryable: bool = True) -> IncompleteLLMResponse:
    return IncompleteLLMResponse(
        "Provider response incomplete: max_output_tokens",
        usage=UsageDetails(
            model="mock-model",
            input_tokens=100,
            output_tokens=4000,
            reasoning_tokens=3200,
            total_tokens=4100,
        ),
        metadata=LLMResponseMetadata(
            response_id="resp_incomplete",
            response_status="incomplete",
            incomplete_reason="max_output_tokens",
        ),
        retryable=retryable,
    )


def test_fixture_loader_normalizes_authoritative_fixture_and_calibration_pairs() -> None:
    cases = _load_fidelity_evaluation_cases()

    assert len(cases) == 38
    for case_id, (source, field, value, expected) in CALIBRATION_CASES.items():
        case = cases[case_id]
        assert case.case_id == case_id
        assert case.semantic_class == "DERIVED_OPERATIONAL"
        assert case.source_text == source
        assert case.target_field == field
        assert case.candidate_value == value
        assert case.expected_verdict == expected
        assert case.boundary_kind in {"operational_wrapper", "factual_payload"}
        assert case.rationale


def test_fixture_loader_accepts_normalized_keys_without_duplicate_truth(
    tmp_path: Path,
) -> None:
    path = tmp_path / "normalized.json"
    path.write_text(
        json.dumps(
            [
                {
                    "case_id": "normalized-case",
                    "semantic_class": "SOURCE_FACTUAL",
                    "source_text": "A bounded source statement.",
                    "target_field": "principle",
                    "candidate_value": "A bounded source statement.",
                    "expected_verdict": "pass",
                    "rationale": "Exact support.",
                    "boundary_kind": "source_factual",
                }
            ]
        ),
        encoding="utf-8",
    )

    case = _load_fidelity_evaluation_cases(path)["normalized-case"]

    assert case.source_text == "A bounded source statement."
    assert case.boundary_kind == "source_factual"


def test_unknown_case_id_fails_cleanly() -> None:
    with pytest.raises(KeyError, match="Unknown fidelity evaluation case: missing"):
        _get_fidelity_evaluation_case("missing")


def test_fidelity_eval_repeat_is_bounded_without_changing_fidelity_check() -> None:
    parser = _build_parser()

    assert parser.parse_args(
        ["fidelity-eval", "derived-sqli-faithful", "--repeat", "1"]
    ).repeat == 1
    assert parser.parse_args(
        ["fidelity-eval", "derived-sqli-faithful", "--repeat", "5"]
    ).repeat == 5
    assert parser.parse_args(
        ["fidelity-check", str(uuid4()), "--repeat", "5"]
    ).repeat == 5
    with pytest.raises(SystemExit):
        parser.parse_args(["fidelity-eval", "derived-sqli-faithful", "--repeat", "0"])
    with pytest.raises(SystemExit):
        parser.parse_args(["fidelity-eval", "derived-sqli-faithful", "--repeat", "6"])


@pytest.mark.parametrize("case_id", sorted(CALIBRATION_CASES))
def test_minimal_artifacts_are_schema_valid_exact_and_deterministic(case_id: str) -> None:
    case = _get_fidelity_evaluation_case(case_id)

    first_card, first_document, first_chunk = _build_atomic_fidelity_artifacts(case)
    second_card, second_document, second_chunk = _build_atomic_fidelity_artifacts(case)

    assert first_card.id == second_card.id
    assert first_document.id == second_document.id
    assert first_chunk.id == second_chunk.id
    assert first_chunk.document_id == first_document.id
    assert first_card.source_chunk_id == first_chunk.id
    assert first_document.content == case.source_text
    assert first_chunk.content == case.source_text
    target = getattr(first_card, case.target_field)
    expected_target = (
        case.candidate_value
        if not isinstance(target, list) or isinstance(case.candidate_value, list)
        else [case.candidate_value]
    )
    assert target == expected_target


def test_non_target_fields_add_no_unrelated_semantic_claims() -> None:
    case = _get_fidelity_evaluation_case("derived-sqli-mechanism")
    card, document, chunk = _build_atomic_fidelity_artifacts(case)

    assert card.title == case.source_text
    assert card.principle == case.source_text
    assert case.source_text.startswith(card.subtopic)
    assert card.tags == []
    assert card.triggers == []
    assert card.questions_to_ask == []
    assert card.false_positive_traps == []
    assert card.escalation_topics == []
    assert card.technique_assumptions == []
    assert card.prerequisites == []
    assert card.demonstrated_behavior == ""
    assert card.speculative_extensions == []
    assert document.content == chunk.content == case.source_text


@pytest.mark.parametrize(
    "case_id",
    [
        "derived-stored-xss-later-response-faithful",
        "derived-stored-xss-verbatim",
        "derived-stored-xss-unsafe-inclusion-faithful",
        "derived-stored-xss-same-payload",
        "derived-stored-xss-workflow-faithful",
        "derived-stored-xss-exact-bytes",
        "derived-stored-xss-browser-html-context",
        "derived-stored-xss-example-no-processing-scoped",
        "derived-stored-xss-no-processing-generalized",
    ],
)
def test_long_stored_xss_source_remains_exact_with_neutral_bounded_card_fields(
    case_id: str,
) -> None:
    case = _get_fidelity_evaluation_case(case_id)
    card, document, chunk = _build_atomic_fidelity_artifacts(case)

    assert document.content == chunk.content == case.source_text
    assert case.source_text.startswith(card.subtopic)
    assert case.source_text.startswith(card.title)
    assert case.source_text.startswith(card.principle)
    assert len(card.subtopic) <= 80
    assert len(card.title) <= 160
    assert len(card.principle) <= 800
    assert case.candidate_value in getattr(card, case.target_field)


def test_historical_kerberos_id_builds_the_dom_negative_routing_fixture() -> None:
    case = _get_fidelity_evaluation_case("routing_fail_kerberos")
    card, document, chunk = _build_atomic_fidelity_artifacts(case)

    assert [topic.value for topic in card.escalation_topics] == ["dom"]
    assert document.content == chunk.content == (
        "The source discusses SQL injection targeting the database."
    )
    assert case.expected_verdict == "fail"


@pytest.mark.asyncio
async def test_retryable_incomplete_is_reported_and_repetitions_continue(
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = _get_fidelity_evaluation_case("derived-sqli-faithful")
    gate = SequenceGate([incomplete(), review("pass"), review("pass")])

    result = await _run_atomic_fidelity_evaluation(
        case=case,
        gate=gate,
        run_id=uuid4(),
        session_id=uuid4(),
        repeat=3,
    )
    _print_json(result)
    output = capsys.readouterr().out

    assert gate.calls == 3
    assert result["pass_count"] == 2
    assert result["incomplete_count"] == 1
    assert result["matches_expected"] == 2
    assert [run["status"] for run in result["runs"]] == [
        "incomplete",
        "completed",
        "completed",
    ]
    assert result["runs"][0]["reason"] == "max_output_tokens"
    assert result["runs"][0]["reasoning_tokens"] == 3200
    assert "Traceback" not in output


@pytest.mark.asyncio
async def test_nonretryable_incomplete_stops_like_fidelity_check() -> None:
    case = _get_fidelity_evaluation_case("derived-sqli-faithful")
    gate = SequenceGate([incomplete(retryable=False), review("pass")])

    result = await _run_atomic_fidelity_evaluation(
        case=case,
        gate=gate,
        run_id=uuid4(),
        session_id=uuid4(),
        repeat=2,
    )

    assert gate.calls == 1
    assert result["incomplete_count"] == 1
    assert len(result["runs"]) == 1


@pytest.mark.asyncio
async def test_target_detection_distinguishes_verdict_match_from_semantic_match() -> None:
    case = _get_fidelity_evaluation_case("derived-sqli-mechanism")
    gate = SequenceGate(
        [
            review("fail", issue_field="evidence_required"),
            review("fail", issue_field="title"),
        ]
    )

    result = await _run_atomic_fidelity_evaluation(
        case=case,
        gate=gate,
        run_id=uuid4(),
        session_id=uuid4(),
        repeat=2,
    )

    assert result["fail_count"] == 2
    assert result["target_detected_count"] == 1
    assert result["matches_expected"] == 1
    assert result["runs"][0]["verdict_matches_expected"] is True
    assert result["runs"][0]["target_detected"] is True
    assert result["runs"][0]["matches_expected"] is True
    assert result["runs"][1]["verdict_matches_expected"] is True
    assert result["runs"][1]["target_detected"] is False
    assert result["runs"][1]["matches_expected"] is False


@pytest.mark.asyncio
async def test_expected_pass_with_any_issue_is_a_mismatch() -> None:
    case = _get_fidelity_evaluation_case("derived-sqli-faithful")

    result = await _run_atomic_fidelity_evaluation(
        case=case,
        gate=SequenceGate([review("fail", issue_field="evidence_required")]),
        run_id=uuid4(),
        session_id=uuid4(),
        repeat=1,
    )

    assert result["pass_count"] == 0
    assert result["fail_count"] == 1
    assert result["matches_expected"] == 0
    assert result["runs"][0]["matches_expected"] is False


@pytest.mark.asyncio
async def test_results_are_independent_and_never_majority_voted() -> None:
    case = _get_fidelity_evaluation_case("derived-sqli-faithful")
    result = await _run_atomic_fidelity_evaluation(
        case=case,
        gate=SequenceGate(
            [review("pass"), review("fail", issue_field="title"), review("pass")]
        ),
        run_id=uuid4(),
        session_id=uuid4(),
        repeat=3,
    )

    assert [run["decision"] for run in result["runs"]] == ["pass", "fail", "pass"]
    assert result["aggregation"] == "independent runs; no automatic vote"
    assert "majority" not in result
    assert "overall_decision" not in result


@pytest.mark.asyncio
async def test_batch_mixes_pass_and_fail_cases_and_aggregates_semantic_matches() -> None:
    cases = _preflight_fidelity_evaluation_cases(
        ["derived-sqli-faithful", "derived-sqli-mechanism"]
    )
    gate = SequenceGate(
        [
            review("pass"),
            review("pass"),
            review("fail", issue_field="evidence_required"),
            review("fail", issue_field="evidence_required"),
        ]
    )

    result = await _run_atomic_fidelity_evaluation_batch(
        cases=cases,
        gate=gate,
        run_id=uuid4(),
        session_id=uuid4(),
        repeat=2,
    )

    assert result["repeat_per_case"] == 2
    assert result["case_count"] == 2
    assert result["total_attempts"] == 4
    assert [case["case_id"] for case in result["cases"]] == [
        "derived-sqli-faithful",
        "derived-sqli-mechanism",
    ]
    assert result["summary"] == {
        "expected_matches": 4,
        "expected_total": 4,
        "target_detected": 2,
        "target_expected_total": 2,
        "pass_expected_cases_clean": 1,
        "fail_expected_cases_clean": 1,
        "incomplete_count": 0,
        "stopped_cases": [],
        "all_expected": True,
    }
    assert result["knowledge_state_mutated"] is False
    assert result["fidelity_review_persisted"] is False
    assert result["aggregation"] == "independent observations; no automatic vote"
    assert "majority" not in result
    assert "overall_decision" not in result


@pytest.mark.asyncio
async def test_batch_aggregates_retryable_incomplete_without_voting() -> None:
    cases = _preflight_fidelity_evaluation_cases(["derived-sqli-faithful"])

    result = await _run_atomic_fidelity_evaluation_batch(
        cases=cases,
        gate=SequenceGate([incomplete(), review("pass")]),
        run_id=uuid4(),
        session_id=uuid4(),
        repeat=2,
    )

    assert result["total_attempts"] == 2
    assert result["summary"]["expected_matches"] == 1
    assert result["summary"]["expected_total"] == 2
    assert result["summary"]["incomplete_count"] == 1
    assert result["summary"]["stopped_cases"] == []
    assert result["summary"]["all_expected"] is False


@pytest.mark.asyncio
async def test_batch_reports_nonretryable_stopped_case_and_continues_later_case() -> None:
    cases = _preflight_fidelity_evaluation_cases(
        ["derived-sqli-faithful", "derived-csrf-faithful"]
    )
    gate = SequenceGate(
        [incomplete(retryable=False), review("pass"), review("pass")]
    )

    result = await _run_atomic_fidelity_evaluation_batch(
        cases=cases,
        gate=gate,
        run_id=uuid4(),
        session_id=uuid4(),
        repeat=2,
    )

    assert gate.calls == 3
    assert result["total_attempts"] == 3
    assert result["summary"]["stopped_cases"] == ["derived-sqli-faithful"]
    assert result["cases"][1]["matches_expected"] == 2
    assert result["summary"]["all_expected"] is False


@pytest.mark.asyncio
async def test_batch_non_evaluator_failure_identifies_stopped_case() -> None:
    cases = _preflight_fidelity_evaluation_cases(
        ["derived-sqli-faithful", "derived-csrf-faithful"]
    )

    with pytest.raises(
        FidelityEvaluationBatchError,
        match="batch stopped at derived-sqli-faithful: transport failed",
    ) as caught:
        await _run_atomic_fidelity_evaluation_batch(
            cases=cases,
            gate=SequenceGate([RuntimeError("transport failed")]),
            run_id=uuid4(),
            session_id=uuid4(),
            repeat=1,
        )

    assert caught.value.case_id == "derived-sqli-faithful"


def test_batch_preflight_rejects_unknown_and_duplicate_ids_before_execution() -> None:
    with pytest.raises(
        KeyError,
        match="Unknown fidelity evaluation case IDs: missing-case",
    ):
        _preflight_fidelity_evaluation_cases(
            ["derived-sqli-faithful", "missing-case"]
        )
    with pytest.raises(
        ValueError,
        match="Duplicate fidelity evaluation case IDs: derived-sqli-faithful",
    ):
        _preflight_fidelity_evaluation_cases(
            ["derived-sqli-faithful", "derived-sqli-faithful"]
        )


def test_batch_cli_repeat_is_bounded_one_through_five() -> None:
    parser = _build_parser()

    assert parser.parse_args(
        ["fidelity-eval-batch", "derived-sqli-faithful", "--repeat", "1"]
    ).repeat == 1
    assert parser.parse_args(
        ["fidelity-eval-batch", "derived-sqli-faithful", "--repeat", "5"]
    ).repeat == 5
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["fidelity-eval-batch", "derived-sqli-faithful", "--repeat", "0"]
        )
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["fidelity-eval-batch", "derived-sqli-faithful", "--repeat", "6"]
        )


class FakeRawResponse:
    request_id = "req_atomic"

    def json(self) -> dict[str, object]:
        return {
            "id": "resp_atomic",
            "status": "completed",
            "model": "mock-model",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "output_tokens_details": {"reasoning_tokens": 20},
                "total_tokens": 150,
            },
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": review("pass").model_dump_json(),
                        }
                    ],
                }
            ],
        }


class FakeEndpoint:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def parse(self, **kwargs) -> FakeRawResponse:
        self.calls.append(kwargs)
        return FakeRawResponse()


class RecordingBudgetManager(BudgetManager):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.authorized = []

    def authorize_call(self, **kwargs):
        reservation = super().authorize_call(**kwargs)
        self.authorized.append(reservation)
        return reservation


def knowledge_counts(path: Path) -> dict[str, int]:
    with sqlite3.connect(path) as connection:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in KNOWLEDGE_TABLES
        }


@pytest.mark.asyncio
async def test_real_gate_path_persists_budget_usage_but_no_knowledge_or_forge_state(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "atomic.db"
    settings = Settings(
        _env_file=None,
        database_path=database_path,
        openai_api_key="local-test-key",
        specialist_model="mock-model",
    )
    memory = SQLiteMemoryStore(database_path)
    SQLiteKnowledgeStore(database_path)
    session_id = memory.create_session()
    before = knowledge_counts(database_path)
    endpoint = FakeEndpoint()
    client = SimpleNamespace(
        responses=SimpleNamespace(
            with_raw_response=SimpleNamespace(parse=endpoint.parse)
        )
    )
    budget = RecordingBudgetManager(
        memory,
        settings,
        PricingCatalog({"mock-model": ModelPricing(1.0, 2.0)}),
    )
    gate = SourceFidelityGate(LLMClient(settings, client=client), budget, settings)

    result = await _run_atomic_fidelity_evaluation(
        case=_get_fidelity_evaluation_case("derived-sqli-faithful"),
        gate=gate,
        run_id=uuid4(),
        session_id=session_id,
        repeat=1,
    )

    with sqlite3.connect(database_path) as connection:
        usage_count = int(connection.execute("SELECT COUNT(*) FROM usage").fetchone()[0])
    assert result["pass_count"] == 1
    assert result["knowledge_state_mutated"] is False
    assert result["fidelity_review_persisted"] is False
    assert knowledge_counts(database_path) == before
    assert usage_count == 1
    assert endpoint.calls[0]["max_output_tokens"] == 4000
    assert budget.authorized[0].max_output_tokens == 4000
    assert budget.active_reservation_count() == 0
    provider_input = json.dumps(endpoint.calls[0]["input"], default=str)
    fixture_case = _get_fidelity_evaluation_case("derived-sqli-faithful")
    assert fixture_case.case_id not in provider_input
    assert fixture_case.rationale not in provider_input
    assert "expected_verdict" not in provider_input
    assert "boundary_kind" not in provider_input


@pytest.mark.asyncio
async def test_batch_real_gate_path_uses_budget_without_knowledge_persistence_or_metadata(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "atomic-batch.db"
    settings = Settings(
        _env_file=None,
        database_path=database_path,
        openai_api_key="local-test-key",
        specialist_model="mock-model",
    )
    memory = SQLiteMemoryStore(database_path)
    SQLiteKnowledgeStore(database_path)
    session_id = memory.create_session()
    before = knowledge_counts(database_path)
    endpoint = FakeEndpoint()
    client = SimpleNamespace(
        responses=SimpleNamespace(
            with_raw_response=SimpleNamespace(parse=endpoint.parse)
        )
    )
    budget = RecordingBudgetManager(
        memory,
        settings,
        PricingCatalog({"mock-model": ModelPricing(1.0, 2.0)}),
    )
    cases = _preflight_fidelity_evaluation_cases(
        ["derived-sqli-faithful", "derived-csrf-faithful"]
    )

    result = await _run_atomic_fidelity_evaluation_batch(
        cases=cases,
        gate=SourceFidelityGate(LLMClient(settings, client=client), budget, settings),
        run_id=uuid4(),
        session_id=session_id,
        repeat=1,
    )

    with sqlite3.connect(database_path) as connection:
        usage_count = int(connection.execute("SELECT COUNT(*) FROM usage").fetchone()[0])
    assert result["summary"]["all_expected"] is True
    assert knowledge_counts(database_path) == before
    assert usage_count == 2
    assert len(endpoint.calls) == 2
    assert len(budget.authorized) == 2
    assert budget.active_reservation_count() == 0
    for case, call in zip(cases, endpoint.calls, strict=True):
        provider_input = json.dumps(call["input"], default=str)
        assert case.case_id not in provider_input
        assert case.rationale not in provider_input
        assert "expected_verdict" not in provider_input
        assert "boundary_kind" not in provider_input
        assert call["max_output_tokens"] == 4000


def test_excluded_gate_metadata_case_fails_before_any_call() -> None:
    case = _get_fidelity_evaluation_case("metadata_confidence_excluded")

    with pytest.raises(ValueError, match="not owned by SourceFidelityGate"):
        _build_atomic_fidelity_artifacts(case)


def test_case_dataclass_exposes_normalized_contract() -> None:
    assert set(FidelityEvaluationCase.__dataclass_fields__) == {
        "case_id",
        "semantic_class",
        "source_text",
        "target_field",
        "candidate_value",
        "expected_verdict",
        "rationale",
        "boundary_kind",
    }
