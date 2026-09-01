from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import UUID, uuid4

from config import Settings
from llm import UsageDetails
from memory import MemoryStore
from pricing import PricingCatalog
from schemas import AgentName


class BudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class BudgetReservation:
    id: UUID
    run_id: UUID
    session_id: UUID
    agent: AgentName
    model: str
    estimated_input_tokens: int
    reserved_input_tokens: int
    max_output_tokens: int
    max_cost_usd: float


PROTOCOL_ENVELOPE_RESERVE_TOKENS = 512


class BudgetManager:
    """Pre-authorizes conservative call cost and owns durable finalization."""

    def __init__(
        self,
        memory: MemoryStore,
        settings: Settings,
        pricing: PricingCatalog,
    ) -> None:
        self.memory = memory
        self.settings = settings
        self.pricing = pricing
        self._reservations: dict[UUID, BudgetReservation] = {}

    def authorize_call(
        self,
        *,
        run_id: UUID,
        session_id: UUID,
        agent: AgentName,
        model: str,
        system_prompt: str,
        user_input: str,
        context: str,
        max_output_tokens: int | None = None,
    ) -> BudgetReservation:
        effective_max_output_tokens = (
            self.settings.max_output_tokens
            if max_output_tokens is None
            else max_output_tokens
        )
        estimated_input_tokens = self.estimate_input_tokens(
            system_prompt, user_input, context
        )
        reserved_input_tokens = self.reserve_input_tokens(
            system_prompt, user_input, context
        )
        max_tokens = reserved_input_tokens + effective_max_output_tokens
        usd_budgets_enabled = any(
            value > 0
            for value in (
                self.settings.daily_budget_usd,
                self.settings.monthly_budget_usd,
                self.settings.max_cost_per_run_usd,
            )
        )
        max_cost = self.pricing.calculate(
            model, reserved_input_tokens, effective_max_output_tokens
        )
        if max_cost is None:
            if usd_budgets_enabled and self.settings.fail_on_unknown_pricing:
                raise BudgetExceeded(
                    f"No reliable pricing is configured for model {model!r}; USD budget is fail-safe."
                )
            max_cost = 0.0

        reserved_cost = sum(item.max_cost_usd for item in self._reservations.values())
        reserved_tokens = sum(
            item.reserved_input_tokens + item.max_output_tokens
            for item in self._reservations.values()
        )
        run_reserved = sum(
            item.max_cost_usd
            for item in self._reservations.values()
            if item.run_id == run_id
        )

        if self.settings.daily_token_budget > 0:
            projected_tokens = (
                self.memory.get_daily_token_usage() + reserved_tokens + max_tokens
            )
            if projected_tokens > self.settings.daily_token_budget:
                raise BudgetExceeded(
                    f"Daily token budget would be exceeded ({projected_tokens} > "
                    f"{self.settings.daily_token_budget})."
                )

        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = day_start.replace(day=1)
        self._check_usd_limit(
            "daily",
            self.settings.daily_budget_usd,
            self.memory.get_usage_cost_since(day_start) + reserved_cost,
            max_cost,
        )
        self._check_usd_limit(
            "monthly",
            self.settings.monthly_budget_usd,
            self.memory.get_usage_cost_since(month_start) + reserved_cost,
            max_cost,
        )
        self._check_usd_limit(
            "per-run",
            self.settings.max_cost_per_run_usd,
            self.memory.get_run_cost(run_id) + run_reserved,
            max_cost,
        )

        reservation = BudgetReservation(
            id=uuid4(),
            run_id=run_id,
            session_id=session_id,
            agent=agent,
            model=model,
            estimated_input_tokens=estimated_input_tokens,
            reserved_input_tokens=reserved_input_tokens,
            max_output_tokens=effective_max_output_tokens,
            max_cost_usd=max_cost,
        )
        self._reservations[reservation.id] = reservation
        return reservation

    def finalize(
        self,
        reservation: BudgetReservation,
        usage: UsageDetails,
    ) -> UsageDetails:
        if reservation.id not in self._reservations:
            raise RuntimeError(f"Unknown or already finalized reservation: {reservation.id}")
        actual_cost = usage.actual_cost_usd
        if actual_cost is None:
            actual_cost = self.pricing.calculate(
                reservation.model, usage.input_tokens, usage.output_tokens
            )
        finalized = replace(
            usage,
            model=usage.model or reservation.model,
            estimated_cost=actual_cost,
            actual_cost_usd=actual_cost,
        )
        self.memory.save_usage(
            reservation.session_id,
            reservation.agent,
            finalized,
            run_id=reservation.run_id,
        )
        self._reservations.pop(reservation.id, None)
        return finalized

    def finalize_uncertain(
        self,
        reservation: BudgetReservation,
        *,
        reason: str,
    ) -> None:
        """Durably retain the maximum reservation for an ambiguous provider outcome."""

        if reservation.id not in self._reservations:
            raise RuntimeError(
                f"Unknown or already finalized reservation: {reservation.id}"
            )
        self.memory.save_uncertain_usage(
            reservation_id=reservation.id,
            session_id=reservation.session_id,
            run_id=reservation.run_id,
            agent=reservation.agent,
            model=reservation.model,
            reserved_input_tokens=reservation.reserved_input_tokens,
            reserved_output_tokens=reservation.max_output_tokens,
            reserved_cost_usd=reservation.max_cost_usd,
            reason=reason,
        )
        self._reservations.pop(reservation.id, None)

    def cancel(self, reservation: BudgetReservation) -> None:
        self._reservations.pop(reservation.id, None)

    def has_active_reservation(self, reservation: BudgetReservation) -> bool:
        return reservation.id in self._reservations

    def active_reservation_count(self) -> int:
        return len(self._reservations)

    def remaining_context(self, run_id: UUID) -> str:
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = day_start.replace(day=1)
        run_spent = self.memory.get_run_cost(run_id)
        lines = ["BUDGET REMAINING (system-enforced before every call):"]
        lines.append(self._remaining_line("run USD", self.settings.max_cost_per_run_usd, run_spent))
        lines.append(
            self._remaining_line(
                "daily USD",
                self.settings.daily_budget_usd,
                self.memory.get_usage_cost_since(day_start),
            )
        )
        lines.append(
            self._remaining_line(
                "monthly USD",
                self.settings.monthly_budget_usd,
                self.memory.get_usage_cost_since(month_start),
            )
        )
        token_limit = self.settings.daily_token_budget
        token_used = self.memory.get_daily_token_usage()
        lines.append(
            "daily tokens: disabled"
            if token_limit <= 0
            else f"daily tokens: {max(0, token_limit - token_used)} remaining"
        )
        return "\n".join(lines)

    def estimate_input_tokens(self, *parts: str) -> int:
        characters = sum(len(part) for part in parts)
        return max(1, math.ceil(characters / self.settings.estimated_chars_per_token))

    @staticmethod
    def reserve_input_tokens(*parts: str) -> int:
        utf8_bytes = sum(len(part.encode("utf-8")) for part in parts)
        return max(1, utf8_bytes) + PROTOCOL_ENVELOPE_RESERVE_TOKENS

    @staticmethod
    def _check_usd_limit(
        label: str,
        limit: float,
        current_and_reserved: float,
        candidate_max: float,
    ) -> None:
        if limit > 0 and current_and_reserved + candidate_max > limit + 1e-12:
            raise BudgetExceeded(
                f"{label} budget would be exceeded: "
                f"${current_and_reserved + candidate_max:.6f} > ${limit:.6f}."
            )

    @staticmethod
    def _remaining_line(label: str, limit: float, spent: float) -> str:
        if limit <= 0:
            return f"{label}: disabled"
        return f"{label}: ${max(0.0, limit - spent):.6f} remaining"
