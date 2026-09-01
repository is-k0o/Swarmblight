from collections import defaultdict, deque
from pathlib import Path
from uuid import uuid4

import pytest

from budget import BudgetExceeded, BudgetManager
from config import Settings
from llm import LLMResult, UsageDetails
from memory import SQLiteMemoryStore
from pricing import ModelPricing, PricingCatalog
from router import SwarmRouter
from schemas import AgentName, MessageType, StructuredAgentResponse


class CountingLLM:
    def __init__(
        self,
        responses: list[StructuredAgentResponse],
        usage: UsageDetails | None = None,
    ) -> None:
        self.responses = deque(responses)
        self.usage = usage or UsageDetails()
        self.calls: defaultdict[AgentName, int] = defaultdict(int)

    async def ask_agent(self, agent, system_prompt, user_input, context="") -> LLMResult:
        self.calls[agent] += 1
        return LLMResult(self.responses.popleft(), self.usage)


def horned_response() -> StructuredAgentResponse:
    return StructuredAgentResponse(
        agent=AgentName.HORNED_RAT,
        message_type=MessageType.DECISION,
        summary="No specialist needed.",
        reasoning_summary="No supported lead.",
    )


def build_router(
    tmp_path: Path,
    settings: Settings,
    fake: CountingLLM,
    catalog: PricingCatalog,
) -> tuple[SwarmRouter, SQLiteMemoryStore]:
    memory = SQLiteMemoryStore(tmp_path / "budget.db")
    manager = BudgetManager(memory, settings, catalog)
    return SwarmRouter(fake, memory, settings, budget=manager), memory


@pytest.mark.asyncio
async def test_call_refused_before_llm_when_daily_budget_is_insufficient(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_path=tmp_path / "budget.db",
        coordinator_model="priced-model",
        specialist_model="priced-model",
        max_output_tokens=256,
        daily_budget_usd=0.0001,
    )
    catalog = PricingCatalog(
        {"priced-model": ModelPricing(1.0, 10.0)}
    )
    fake = CountingLLM([horned_response()])
    router, memory = build_router(tmp_path, settings, fake, catalog)

    with pytest.raises(BudgetExceeded, match="daily"):
        await router.run(memory.create_session(), "manual data")

    assert sum(fake.calls.values()) == 0


@pytest.mark.asyncio
async def test_actual_cost_is_recorded_after_simulated_call(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "budget.db",
        coordinator_model="priced-model",
        specialist_model="priced-model",
        max_output_tokens=256,
        max_cost_per_run_usd=1.0,
    )
    catalog = PricingCatalog(
        {"priced-model": ModelPricing(1.0, 2.0)}
    )
    fake = CountingLLM(
        [horned_response()],
        UsageDetails(model="priced-model", input_tokens=100, output_tokens=50, total_tokens=150),
    )
    router, memory = build_router(tmp_path, settings, fake, catalog)

    result = await router.run(memory.create_session(), "manual data")

    assert memory.get_run_cost(result.run_id) == pytest.approx(0.0002)


def test_max_cost_per_run_is_checked_before_call(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "budget.db",
        coordinator_model="priced-model",
        specialist_model="priced-model",
        max_output_tokens=256,
        max_cost_per_run_usd=0.0001,
    )
    memory = SQLiteMemoryStore(settings.database_path)
    manager = BudgetManager(
        memory,
        settings,
        PricingCatalog({"priced-model": ModelPricing(1.0, 10.0)}),
    )

    with pytest.raises(BudgetExceeded, match="per-run"):
        manager.authorize_call(
            run_id=memory.create_session(),
            session_id=memory.get_or_create_active_session(),
            agent=AgentName.HORNED_RAT,
            model="priced-model",
            system_prompt="system",
            user_input="input",
            context="context",
        )


def test_unknown_pricing_fails_safe_when_usd_budget_is_enabled(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "budget.db",
        coordinator_model="unknown-model",
        specialist_model="unknown-model",
        max_cost_per_run_usd=1.0,
    )
    memory = SQLiteMemoryStore(settings.database_path)
    manager = BudgetManager(memory, settings, PricingCatalog())
    session_id = memory.create_session()

    with pytest.raises(BudgetExceeded, match="No reliable pricing"):
        manager.authorize_call(
            run_id=session_id,
            session_id=session_id,
            agent=AgentName.HORNED_RAT,
            model="unknown-model",
            system_prompt="system",
            user_input="input",
            context="context",
        )


def test_dense_json_receives_conservative_token_reservation(tmp_path: Path) -> None:
    settings = Settings(database_path=tmp_path / "budget.db")
    memory = SQLiteMemoryStore(settings.database_path)
    manager = BudgetManager(memory, settings, PricingCatalog())
    session_id = memory.create_session()
    dense_json = '{"payload":"' + "\\u003cscript\\u003e" * 100 + '"}'

    reservation = manager.authorize_call(
        run_id=uuid4(),
        session_id=session_id,
        agent=AgentName.IKIT,
        model="unknown-model",
        system_prompt="system",
        user_input=dense_json,
        context="JSON analysis",
    )

    content_bytes = sum(
        len(part.encode("utf-8")) for part in ("system", dense_json, "JSON analysis")
    )
    assert reservation.reserved_input_tokens > reservation.estimated_input_tokens
    assert reservation.reserved_input_tokens >= content_bytes
    manager.cancel(reservation)


class FailingUsageStore(SQLiteMemoryStore):
    def save_usage(self, *args, **kwargs):
        raise RuntimeError("simulated durable write failure")


def test_persistence_failure_does_not_release_reservation(tmp_path: Path) -> None:
    settings = Settings(database_path=tmp_path / "failing.db")
    memory = FailingUsageStore(settings.database_path)
    manager = BudgetManager(
        memory,
        settings,
        PricingCatalog({"priced-model": ModelPricing(1.0, 2.0)}),
    )
    session_id = memory.create_session()
    reservation = manager.authorize_call(
        run_id=uuid4(),
        session_id=session_id,
        agent=AgentName.HORNED_RAT,
        model="priced-model",
        system_prompt="system",
        user_input="input",
        context="context",
    )

    with pytest.raises(RuntimeError, match="durable write failure"):
        manager.finalize(
            reservation,
            UsageDetails(input_tokens=10, output_tokens=5, total_tokens=15),
        )

    assert manager.has_active_reservation(reservation)
    assert memory.get_daily_token_usage() == 0


def test_successful_finalize_persists_then_releases_reservation(tmp_path: Path) -> None:
    settings = Settings(database_path=tmp_path / "budget.db")
    memory = SQLiteMemoryStore(settings.database_path)
    manager = BudgetManager(
        memory,
        settings,
        PricingCatalog({"priced-model": ModelPricing(1.0, 2.0)}),
    )
    session_id = memory.create_session()
    run_id = uuid4()
    reservation = manager.authorize_call(
        run_id=run_id,
        session_id=session_id,
        agent=AgentName.HORNED_RAT,
        model="priced-model",
        system_prompt="system",
        user_input="input",
        context="context",
    )

    finalized = manager.finalize(
        reservation,
        UsageDetails(input_tokens=100, output_tokens=50, total_tokens=150),
    )

    assert finalized.actual_cost_usd == pytest.approx(0.0002)
    assert memory.get_run_cost(run_id) == pytest.approx(0.0002)
    assert not manager.has_active_reservation(reservation)


def test_subsequent_authorization_sees_finalized_usage(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "budget.db",
        max_output_tokens=256,
        daily_budget_usd=0.001,
    )
    memory = SQLiteMemoryStore(settings.database_path)
    manager = BudgetManager(
        memory,
        settings,
        PricingCatalog({"priced-model": ModelPricing(1.0, 1.0)}),
    )
    session_id = memory.create_session()
    run_id = uuid4()
    first = manager.authorize_call(
        run_id=run_id,
        session_id=session_id,
        agent=AgentName.HORNED_RAT,
        model="priced-model",
        system_prompt="system",
        user_input="input",
        context="context",
    )
    manager.finalize(
        first,
        UsageDetails(input_tokens=200, output_tokens=200, total_tokens=400),
    )

    with pytest.raises(BudgetExceeded, match="daily"):
        manager.authorize_call(
            run_id=run_id,
            session_id=session_id,
            agent=AgentName.HORNED_RAT,
            model="priced-model",
            system_prompt="system",
            user_input="input",
            context="context",
        )
