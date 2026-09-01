from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import httpx
from openai import AsyncOpenAI, BadRequestError

from budget import BudgetExceeded, BudgetManager
from config import Settings
from forge import KnowledgeCardCritic, KnowledgeCardGenerator
from llm import (
    IncompleteLLMResponse,
    InvalidLLMResponse,
    LLMAmbiguousInterruption,
    LLMClient,
    LLMTransportError,
)
from memory import SQLiteMemoryStore
from pricing import ModelPricing, PricingCatalog
from schemas import (
    AgentName,
    KnowledgeCard,
    KnowledgeCardCritique,
    GeneratedKnowledgeCards,
    KnowledgeCardStatus,
    KnowledgeSourceType,
    KnowledgeTopic,
    MessageType,
    StructuredAgentResponse,
)
from source_ingestion import SourceIngestor


class FakeRawResponse:
    def __init__(self, payload: object, request_id: str = "req_test") -> None:
        self.payload = payload
        self.request_id = request_id
        self.parse_called = False

    def json(self):
        return self.payload

    def parse(self):
        self.parse_called = True
        raise AssertionError("raw_response.parse() must never be called")


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


class RaisingStructuredBackend:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    async def ask_structured(self, *args, **kwargs):
        raise self.error


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
    input_tokens: int = 100,
    output_tokens: int = 50,
    reasoning_tokens: int | None = None,
) -> dict[str, object]:
    usage: dict[str, object] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }
    if reasoning_tokens is not None:
        usage["output_tokens_details"] = {"reasoning_tokens": reasoning_tokens}
    return {
        "id": "resp_test",
        "status": status,
        "model": "mock-model",
        "incomplete_details": (
            {"reason": incomplete_reason} if incomplete_reason else None
        ),
        "usage": usage,
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": output_text}],
            }
        ],
    }


def bad_request(
    *,
    message: str,
    error_type: str = "invalid_request_error",
    param: str | None,
    code: str | None,
    request_id: str = "req_bad_request",
) -> BadRequestError:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(
        400,
        request=request,
        headers={"x-request-id": request_id},
    )
    body = {
        "message": message,
        "type": error_type,
        "param": param,
        "code": code,
    }
    return BadRequestError("test provider rejection", response=response, body=body)


def setup_generator(
    tmp_path: Path,
    outcome: object,
    *,
    daily_tokens: int = 0,
    max_output_tokens: int = 256,
    generator_max_output_tokens: int | None = None,
):
    settings = Settings(
        database_path=tmp_path / "lifecycle.db",
        specialist_model="mock-model",
        max_output_tokens=max_output_tokens,
        generator_max_output_tokens=generator_max_output_tokens,
        daily_token_budget=daily_tokens,
        daily_budget_usd=0,
        monthly_budget_usd=0,
        max_cost_per_run_usd=0,
    )
    memory = SQLiteMemoryStore(settings.database_path)
    manager = RecordingBudgetManager(
        memory,
        settings,
        PricingCatalog({"mock-model": ModelPricing(1.0, 2.0)}),
    )
    fake_client = FakeOpenAIClient(outcome)
    llm = LLMClient(settings, client=fake_client)
    generator = KnowledgeCardGenerator(llm, manager, settings)
    source_path = tmp_path / "source.md"
    source_path.write_text("# DOM\n\nAttribute control is not execution.", encoding="utf-8")
    document, chunks = SourceIngestor(500).ingest_file(
        source_path,
        agent=AgentName.IKIT,
        source_type=KnowledgeSourceType.ACADEMY,
        topic=KnowledgeTopic.DOM,
    )
    session_id = memory.create_session()
    return (
        settings,
        memory,
        manager,
        fake_client,
        generator,
        document,
        chunks[0],
        session_id,
    )


def setup_critic(
    tmp_path: Path,
    outcome: object,
    *,
    max_output_tokens: int = 256,
    critic_max_output_tokens: int | None = None,
):
    settings = Settings(
        database_path=tmp_path / "critic-lifecycle.db",
        openai_api_key="API_SECRET_MUST_NOT_APPEAR",
        specialist_model="mock-model",
        max_output_tokens=max_output_tokens,
        critic_max_output_tokens=critic_max_output_tokens,
        daily_budget_usd=0,
        monthly_budget_usd=0,
        max_cost_per_run_usd=0,
    )
    memory = SQLiteMemoryStore(settings.database_path)
    manager = RecordingBudgetManager(
        memory,
        settings,
        PricingCatalog({"mock-model": ModelPricing(1.0, 2.0)}),
    )
    fake_client = FakeOpenAIClient(outcome)
    llm = LLMClient(settings, client=fake_client)
    critic = KnowledgeCardCritic(llm, manager, settings)
    source_path = tmp_path / "critic-source.md"
    source_path.write_text(
        "# Source\n\nSOURCE_SECRET_MUST_NOT_APPEAR describes a bounded distinction.",
        encoding="utf-8",
    )
    document, chunks = SourceIngestor(500).ingest_file(
        source_path,
        agent=AgentName.IKIT,
        source_type=KnowledgeSourceType.ACADEMY,
        topic=KnowledgeTopic.DOM,
    )
    card = KnowledgeCard(
        agent=AgentName.IKIT,
        topic=KnowledgeTopic.DOM,
        title="Bounded distinction",
        principle="Retain only the source-supported distinction.",
        source_type=document.source_type,
        source_title=document.title,
        source_reference=document.source_reference,
        source_chunk_id=chunks[0].id,
        status=KnowledgeCardStatus.CANDIDATE,
    )
    return (
        settings,
        memory,
        manager,
        fake_client,
        critic,
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
async def test_forge_stage_output_limits_reach_api_and_budget(tmp_path: Path) -> None:
    generator_raw = FakeRawResponse(response_payload('{"cards":[]}'))
    (
        generator_settings,
        _,
        generator_budget,
        generator_api,
        generator,
        document,
        chunk,
        session_id,
    ) = setup_generator(
        tmp_path,
        generator_raw,
        max_output_tokens=768,
        generator_max_output_tokens=4000,
    )

    await generator.generate(
        document,
        chunk,
        run_id=uuid4(),
        session_id=session_id,
    )

    assert generator_settings.effective_generator_max_output_tokens == 4000
    assert generator_api.endpoint.calls[0]["max_output_tokens"] == 4000
    assert "verbosity" not in generator_api.endpoint.calls[0]
    assert generator_budget.authorized[0].max_output_tokens == 4000

    critic_raw = FakeRawResponse(
        response_payload(
            '{"critique":{"decision":"approve","reasons":["Source-supported."]}}'
        )
    )
    (
        critic_settings,
        _,
        critic_budget,
        critic_api,
        critic,
        card,
        critic_document,
        critic_chunk,
        critic_session_id,
    ) = setup_critic(
        tmp_path,
        critic_raw,
        max_output_tokens=768,
        critic_max_output_tokens=6000,
    )

    await critic.review(
        card,
        critic_document,
        critic_chunk,
        run_id=uuid4(),
        session_id=critic_session_id,
    )

    assert critic_settings.effective_critic_max_output_tokens == 6000
    assert critic_api.endpoint.calls[0]["max_output_tokens"] == 6000
    assert "verbosity" not in critic_api.endpoint.calls[0]
    assert critic_api.endpoint.calls[0]["text"] == {"verbosity": "low"}
    assert critic_budget.authorized[0].max_output_tokens == 6000


@pytest.mark.asyncio
async def test_critic_verbosity_is_nested_under_text_on_the_wire(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    async def reject(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            400,
            request=request,
            headers={"x-request-id": "req_wire_shape"},
            json={
                "error": {
                    "message": "Unknown parameter: 'legacy_probe'.",
                    "type": "invalid_request_error",
                    "param": "legacy_probe",
                    "code": "unknown_parameter",
                }
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(reject))
    sdk = AsyncOpenAI(
        api_key="local-test-key",
        base_url="https://local.test/v1",
        http_client=http_client,
        max_retries=0,
    )
    settings = Settings(
        database_path=tmp_path / "wire.db",
        specialist_model="gpt-5-mini",
        max_output_tokens=256,
    )
    client = LLMClient(settings, client=sdk)

    try:
        with pytest.raises(LLMTransportError):
            await client.ask_structured(
                AgentName.IKIT,
                "system",
                "input",
                KnowledgeCardCritique,
                max_output_tokens=256,
                verbosity="low",
            )
    finally:
        await sdk.close()

    assert "verbosity" not in captured
    text = captured["text"]
    assert isinstance(text, dict)
    assert text["verbosity"] == "low"
    response_format = text["format"]
    assert isinstance(response_format, dict)
    assert response_format["name"] == "KnowledgeCardCritique"
    assert response_format["strict"] is True


@pytest.mark.asyncio
async def test_forge_stage_output_limits_fall_back_to_global_max(
    tmp_path: Path,
) -> None:
    fallback = 768
    generator_raw = FakeRawResponse(response_payload('{"cards":[]}'))
    (
        generator_settings,
        _,
        generator_budget,
        generator_api,
        generator,
        document,
        chunk,
        session_id,
    ) = setup_generator(tmp_path, generator_raw, max_output_tokens=fallback)

    await generator.generate(
        document,
        chunk,
        run_id=uuid4(),
        session_id=session_id,
    )

    assert generator_settings.generator_max_output_tokens is None
    assert generator_settings.effective_generator_max_output_tokens == fallback
    assert generator_api.endpoint.calls[0]["max_output_tokens"] == fallback
    assert generator_budget.authorized[0].max_output_tokens == fallback

    critic_raw = FakeRawResponse(
        response_payload(
            '{"critique":{"decision":"approve","reasons":["Source-supported."]}}'
        )
    )
    (
        critic_settings,
        _,
        critic_budget,
        critic_api,
        critic,
        card,
        critic_document,
        critic_chunk,
        critic_session_id,
    ) = setup_critic(tmp_path, critic_raw, max_output_tokens=fallback)

    await critic.review(
        card,
        critic_document,
        critic_chunk,
        run_id=uuid4(),
        session_id=critic_session_id,
    )

    assert critic_settings.critic_max_output_tokens is None
    assert critic_settings.effective_critic_max_output_tokens == fallback
    assert critic_api.endpoint.calls[0]["max_output_tokens"] == fallback
    assert critic_budget.authorized[0].max_output_tokens == fallback


@pytest.mark.asyncio
async def test_incomplete_raw_response_preserves_and_finalizes_actual_usage(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    partial_output = '{"cards":[{"title":"SENSITIVE_PARTIAL_OUTPUT'
    raw = FakeRawResponse(
        response_payload(
            partial_output,
            status="incomplete",
            incomplete_reason="max_output_tokens",
            input_tokens=120,
            output_tokens=200,
            reasoning_tokens=64,
        )
    )
    settings, memory, manager, fake, generator, document, chunk, session_id = (
        setup_generator(tmp_path, raw)
    )
    caplog.set_level("INFO", logger="llm")

    with pytest.raises(IncompleteLLMResponse) as caught:
        await generator.generate(
            document,
            chunk,
            run_id=uuid4(),
            session_id=session_id,
        )

    error = caught.value
    assert error.usage is not None
    assert error.usage.total_tokens == 320
    assert error.usage.reasoning_tokens == 64
    assert error.metadata.response_id == "resp_test"
    assert error.metadata.incomplete_reason == "max_output_tokens"
    assert error.metadata.output_character_length == len(partial_output)
    diagnostics = error.incomplete_diagnostics
    assert diagnostics is not None
    assert diagnostics.raw_decode_succeeded is False
    assert diagnostics.semantically_complete is False
    assert diagnostics.lexically_inside_string is True
    assert diagnostics.unclosed_structure_depth == 3
    assert partial_output not in repr(error.metadata)
    assert partial_output not in caplog.text
    assert error.retryable is True
    assert memory.get_daily_token_usage() == 320
    assert accounting_rows(settings.database_path) == (1, 0)
    assert manager.active_reservation_count() == 0
    assert raw.parse_called is False
    assert fake.endpoint.calls[0]["text_format"] is GeneratedKnowledgeCards


@pytest.mark.parametrize(
    "suffix",
    ["   ", "\t", "\r", "\n", " \t\r\n  \r"],
)
@pytest.mark.asyncio
async def test_incomplete_semantically_complete_json_is_detected_but_rejected(
    tmp_path: Path,
    suffix: str,
) -> None:
    semantic_json = (
        '{"critique":{"decision":"approve",'
        '"reasons":["Source-supported."]}}'
    )
    raw = FakeRawResponse(
        response_payload(
            semantic_json + suffix,
            status="incomplete",
            incomplete_reason="max_output_tokens",
            input_tokens=90,
            output_tokens=10_000,
            reasoning_tokens=1_920,
        )
    )
    (
        settings,
        memory,
        manager,
        _,
        critic,
        card,
        document,
        chunk,
        session_id,
    ) = setup_critic(tmp_path, raw)

    with pytest.raises(IncompleteLLMResponse) as caught:
        await critic.review(
            card,
            document,
            chunk,
            run_id=uuid4(),
            session_id=session_id,
        )

    error = caught.value
    diagnostics = error.incomplete_diagnostics
    assert diagnostics is not None
    assert diagnostics.raw_decode_succeeded is True
    assert diagnostics.decoded_end == len(semantic_json)
    assert diagnostics.post_document_suffix_length == len(suffix)
    assert diagnostics.post_document_suffix_only_json_whitespace is True
    assert diagnostics.schema_validation_succeeded is True
    assert diagnostics.semantically_complete is True
    assert diagnostics.trailing_whitespace_start == len(semantic_json)
    assert diagnostics.trailing_whitespace_length == len(suffix)
    assert diagnostics.trailing_spaces == suffix.count(" ")
    assert diagnostics.trailing_tabs == suffix.count("\t")
    assert diagnostics.trailing_cr == suffix.count("\r")
    assert diagnostics.trailing_lf == suffix.count("\n")
    assert error.usage is not None
    assert error.usage.output_tokens == 10_000
    assert error.usage.reasoning_tokens == 1_920
    assert memory.get_daily_token_usage() == 10_090
    assert accounting_rows(settings.database_path) == (1, 0)
    assert manager.active_reservation_count() == 0


@pytest.mark.asyncio
async def test_incomplete_whitespace_loop_before_required_closers_fails_closed(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    incomplete_prefix = (
        '{"critique":{"decision":"revise",'
        '"reasons":["OUTPUT_SECRET_MUST_NOT_APPEAR"],'
        '"revised_card":{"title":"Bounded",'
        '"principle":"Supported.","speculative_extensions":[]'
    )
    whitespace_loop = (" \r" * 40) + "\n"
    raw = FakeRawResponse(
        response_payload(
            incomplete_prefix + whitespace_loop,
            status="incomplete",
            incomplete_reason="max_output_tokens",
            input_tokens=90,
            output_tokens=10_000,
            reasoning_tokens=1_920,
        )
    )
    (
        settings,
        memory,
        manager,
        _,
        critic,
        card,
        document,
        chunk,
        session_id,
    ) = setup_critic(tmp_path, raw)
    caplog.set_level("WARNING", logger="llm")

    with pytest.raises(IncompleteLLMResponse) as caught:
        await critic.review(
            card,
            document,
            chunk,
            run_id=uuid4(),
            session_id=session_id,
        )

    error = caught.value
    diagnostics = error.incomplete_diagnostics
    assert diagnostics is not None
    assert diagnostics.raw_decode_succeeded is False
    assert diagnostics.decoded_end is None
    assert diagnostics.schema_validation_succeeded is None
    assert diagnostics.semantically_complete is False
    assert diagnostics.trailing_whitespace_start == len(incomplete_prefix)
    assert diagnostics.trailing_whitespace_length == len(whitespace_loop)
    assert diagnostics.trailing_spaces == 40
    assert diagnostics.trailing_cr == 40
    assert diagnostics.trailing_lf == 1
    assert diagnostics.lexically_inside_string is False
    assert diagnostics.unclosed_structure_depth == 3
    assert error.usage is not None
    assert error.usage.output_tokens == 10_000
    assert error.usage.reasoning_tokens == 1_920
    assert memory.get_daily_token_usage() == 10_090
    assert accounting_rows(settings.database_path) == (1, 0)
    assert manager.active_reservation_count() == 0
    combined = caplog.text + str(error) + repr(diagnostics)
    assert "OUTPUT_SECRET_MUST_NOT_APPEAR" not in combined
    assert incomplete_prefix not in combined


@pytest.mark.asyncio
async def test_incomplete_json_with_non_whitespace_suffix_is_not_semantically_complete(
    tmp_path: Path,
) -> None:
    semantic_json = (
        '{"critique":{"decision":"approve",'
        '"reasons":["Source-supported."]}}'
    )
    raw = FakeRawResponse(
        response_payload(
            semantic_json + " trailing-content",
            status="incomplete",
            incomplete_reason="max_output_tokens",
        )
    )
    _, _, _, _, critic, card, document, chunk, session_id = setup_critic(
        tmp_path,
        raw,
    )

    with pytest.raises(IncompleteLLMResponse) as caught:
        await critic.review(
            card,
            document,
            chunk,
            run_id=uuid4(),
            session_id=session_id,
        )

    diagnostics = caught.value.incomplete_diagnostics
    assert diagnostics is not None
    assert diagnostics.raw_decode_succeeded is True
    assert diagnostics.schema_validation_succeeded is True
    assert diagnostics.post_document_suffix_only_json_whitespace is False
    assert diagnostics.semantically_complete is False


@pytest.mark.asyncio
async def test_incomplete_complete_json_failing_schema_is_not_semantically_complete(
    tmp_path: Path,
) -> None:
    invalid_critique = '{"critique":{"decision":"approve","reasons":[]}}   '
    raw = FakeRawResponse(
        response_payload(
            invalid_critique,
            status="incomplete",
            incomplete_reason="max_output_tokens",
        )
    )
    _, _, _, _, critic, card, document, chunk, session_id = setup_critic(
        tmp_path,
        raw,
    )

    with pytest.raises(IncompleteLLMResponse) as caught:
        await critic.review(
            card,
            document,
            chunk,
            run_id=uuid4(),
            session_id=session_id,
        )

    diagnostics = caught.value.incomplete_diagnostics
    assert diagnostics is not None
    assert diagnostics.raw_decode_succeeded is True
    assert diagnostics.post_document_suffix_only_json_whitespace is True
    assert diagnostics.schema_validation_succeeded is False
    assert diagnostics.semantically_complete is False


@pytest.mark.asyncio
async def test_incomplete_other_reason_has_no_whitespace_recovery_diagnostics(
    tmp_path: Path,
) -> None:
    raw = FakeRawResponse(
        response_payload(
            '{"critique":{"decision":"approve","reasons":["Valid."]}}   ',
            status="incomplete",
            incomplete_reason="content_filter",
        )
    )
    _, _, _, _, critic, card, document, chunk, session_id = setup_critic(
        tmp_path,
        raw,
    )

    with pytest.raises(IncompleteLLMResponse) as caught:
        await critic.review(
            card,
            document,
            chunk,
            run_id=uuid4(),
            session_id=session_id,
        )

    assert caught.value.retryable is False
    assert caught.value.incomplete_diagnostics is None


@pytest.mark.asyncio
async def test_completed_malformed_structured_json_is_accounted(tmp_path: Path) -> None:
    raw = FakeRawResponse(
        response_payload(
            '{"cards":[{"title":"truncated',
            input_tokens=80,
            output_tokens=40,
        )
    )
    settings, memory, manager, _, generator, document, chunk, session_id = (
        setup_generator(tmp_path, raw)
    )

    with pytest.raises(InvalidLLMResponse) as caught:
        await generator.generate(
            document,
            chunk,
            run_id=uuid4(),
            session_id=session_id,
        )

    assert caught.value.usage is not None
    assert caught.value.usage.total_tokens == 120
    assert caught.value.metadata.response_status == "completed"
    assert memory.get_daily_token_usage() == 120
    assert accounting_rows(settings.database_path) == (1, 0)
    assert manager.active_reservation_count() == 0
    assert raw.parse_called is False


@pytest.mark.asyncio
async def test_completed_invalid_critique_has_safe_diagnostics_and_actual_accounting(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    output_text = (
        '{"critique":{"decision":"revise","reasons":["A revision was requested"]}}'
    )
    raw = FakeRawResponse(
        response_payload(output_text, input_tokens=90, output_tokens=30)
    )
    (
        settings,
        memory,
        manager,
        _,
        critic,
        card,
        document,
        chunk,
        session_id,
    ) = setup_critic(tmp_path, raw)
    caplog.set_level("WARNING", logger="llm")

    with pytest.raises(InvalidLLMResponse) as caught:
        await critic.review(
            card,
            document,
            chunk,
            run_id=uuid4(),
            session_id=session_id,
        )

    error = caught.value
    diagnostics = error.validation_diagnostics
    assert error.retryable is True
    assert error.usage is not None
    assert error.usage.total_tokens == 120
    assert diagnostics is not None
    assert diagnostics.response_id == "resp_test"
    assert diagnostics.provider_status == "completed"
    assert diagnostics.schema_name == "KnowledgeCardCritique"
    assert diagnostics.output_character_length == len(output_text)
    assert diagnostics.error_count == len(diagnostics.issues)
    assert diagnostics.error_count > 0
    assert any("revised_card" in issue.location for issue in diagnostics.issues)
    assert all(issue.error_type and issue.message for issue in diagnostics.issues)
    assert memory.get_daily_token_usage() == 120
    assert accounting_rows(settings.database_path) == (1, 0)
    assert manager.active_reservation_count() == 0
    assert raw.parse_called is False

    diagnostic_text = repr(asdict(diagnostics))
    combined_diagnostics = diagnostic_text + caplog.text + str(error)
    assert "resp_test" in caplog.text
    assert "KnowledgeCardCritique" in caplog.text
    assert "SOURCE_SECRET_MUST_NOT_APPEAR" not in combined_diagnostics
    assert "API_SECRET_MUST_NOT_APPEAR" not in combined_diagnostics
    assert output_text not in combined_diagnostics


@pytest.mark.asyncio
async def test_valid_raw_structured_response_finalizes_once(tmp_path: Path) -> None:
    raw = FakeRawResponse(response_payload('{"cards":[]}'))
    settings, memory, manager, _, generator, document, chunk, session_id = (
        setup_generator(tmp_path, raw)
    )

    cards = await generator.generate(
        document,
        chunk,
        run_id=uuid4(),
        session_id=session_id,
    )

    assert cards == []
    assert memory.get_daily_token_usage() == 150
    assert accounting_rows(settings.database_path) == (1, 0)
    assert manager.active_reservation_count() == 0
    assert raw.parse_called is False


@pytest.mark.asyncio
async def test_definite_transport_failure_cancels_without_fake_usage(
    tmp_path: Path,
) -> None:
    settings, memory, manager, _, _, document, chunk, session_id = setup_generator(
        tmp_path,
        FakeRawResponse(response_payload('{"cards":[]}')),
    )
    generator = KnowledgeCardGenerator(
        RaisingStructuredBackend(LLMTransportError("definite pre-response failure")),
        manager,
        settings,
    )

    with pytest.raises(LLMTransportError):
        await generator.generate(
            document,
            chunk,
            run_id=uuid4(),
            session_id=session_id,
        )

    assert memory.get_daily_token_usage() == 0
    assert accounting_rows(settings.database_path) == (0, 0)
    assert manager.active_reservation_count() == 0


@pytest.mark.asyncio
async def test_bad_request_diagnostics_are_safe_and_cancel_reservation(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    outcome = bad_request(
        message="Unsupported parameter: 'verbosity' is not supported with this model.",
        param=None,
        code="unsupported_parameter",
        request_id="req_critic_400",
    )
    (
        settings,
        memory,
        manager,
        _,
        critic,
        card,
        document,
        chunk,
        session_id,
    ) = setup_critic(tmp_path, outcome)
    caplog.set_level("WARNING", logger="llm")

    with pytest.raises(LLMTransportError) as caught:
        await critic.review(
            card,
            document,
            chunk,
            run_id=uuid4(),
            session_id=session_id,
        )

    diagnostics = caught.value.diagnostics
    assert diagnostics is not None
    assert diagnostics.status_code == 400
    assert diagnostics.error_type == "invalid_request_error"
    assert diagnostics.error_code == "unsupported_parameter"
    assert diagnostics.param is None
    assert diagnostics.message == (
        "Unsupported parameter: 'verbosity' is not supported with this model."
    )
    assert diagnostics.request_id == "req_critic_400"
    assert "code=unsupported_parameter" in str(caught.value)
    assert "req_critic_400" in caplog.text
    assert "SOURCE_SECRET_MUST_NOT_APPEAR" not in caplog.text
    assert "API_SECRET_MUST_NOT_APPEAR" not in caplog.text
    assert memory.get_daily_token_usage() == 0
    assert accounting_rows(settings.database_path) == (0, 0)
    assert manager.active_reservation_count() == 0


@pytest.mark.asyncio
async def test_bad_request_input_body_is_not_exposed(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    unsafe = "SOURCE_SECRET_MUST_NOT_APPEAR API_SECRET_MUST_NOT_APPEAR"
    outcome = bad_request(
        message=unsafe,
        param="input",
        code="invalid_request",
    )
    (
        _,
        _,
        _,
        _,
        critic,
        card,
        document,
        chunk,
        session_id,
    ) = setup_critic(tmp_path, outcome)
    caplog.set_level("WARNING", logger="llm")

    with pytest.raises(LLMTransportError) as caught:
        await critic.review(
            card,
            document,
            chunk,
            run_id=uuid4(),
            session_id=session_id,
        )

    diagnostics = caught.value.diagnostics
    assert diagnostics is not None
    assert diagnostics.message is None
    combined = caplog.text + str(caught.value) + repr(diagnostics)
    assert "SOURCE_SECRET_MUST_NOT_APPEAR" not in combined
    assert "API_SECRET_MUST_NOT_APPEAR" not in combined


@pytest.mark.asyncio
async def test_ambiguous_cancellation_is_durably_accounted_fail_closed(
    tmp_path: Path,
) -> None:
    (
        settings,
        memory,
        manager,
        _,
        generator,
        document,
        chunk,
        session_id,
    ) = setup_generator(tmp_path, asyncio.CancelledError(), daily_tokens=100_000)
    run_id = uuid4()

    with pytest.raises(LLMAmbiguousInterruption):
        await generator.generate(
            document,
            chunk,
            run_id=run_id,
            session_id=session_id,
        )

    conservative_tokens = memory.get_daily_token_usage()
    assert conservative_tokens > settings.max_output_tokens
    assert accounting_rows(settings.database_path) == (0, 1)
    assert manager.active_reservation_count() == 0

    settings.daily_token_budget = conservative_tokens
    with pytest.raises(BudgetExceeded, match="Daily token budget"):
        manager.authorize_call(
            run_id=run_id,
            session_id=session_id,
            agent=AgentName.IKIT,
            model="mock-model",
            system_prompt="system",
            user_input="input",
            context="context",
        )


@pytest.mark.asyncio
async def test_ask_agent_uses_same_raw_lifecycle(tmp_path: Path) -> None:
    response = StructuredAgentResponse(
        agent=AgentName.HORNED_RAT,
        message_type=MessageType.DECISION,
        summary="No specialist needed.",
        reasoning_summary="No supported lead.",
    )
    raw = FakeRawResponse(response_payload(response.model_dump_json()))
    settings = Settings(
        database_path=tmp_path / "agent.db",
        coordinator_model="mock-model",
        max_output_tokens=256,
    )
    fake = FakeOpenAIClient(raw)
    client = LLMClient(settings, client=fake)

    result = await client.ask_agent(
        AgentName.HORNED_RAT,
        "system",
        "input",
    )

    assert result.response == response
    assert result.usage.total_tokens == 150
    assert result.metadata is not None
    assert result.metadata.response_id == "resp_test"
    assert result.usage.reasoning_tokens == 0
    assert raw.parse_called is False
    assert fake.endpoint.calls[0]["max_output_tokens"] == settings.max_output_tokens
