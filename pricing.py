from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelPricing:
    input_usd_per_million_tokens: float
    output_usd_per_million_tokens: float


class PricingCatalog:
    """Central pricing source; intentionally data-driven because prices change."""

    def __init__(self, models: dict[str, ModelPricing] | None = None) -> None:
        self._models = models or {}

    @classmethod
    def from_file(cls, path: str | Path) -> "PricingCatalog":
        pricing_path = Path(path)
        if not pricing_path.exists():
            return cls()
        raw = json.loads(pricing_path.read_text(encoding="utf-8"))
        entries = raw.get("models", {})
        return cls(
            {
                name: ModelPricing(
                    input_usd_per_million_tokens=float(values["input_usd_per_million_tokens"]),
                    output_usd_per_million_tokens=float(values["output_usd_per_million_tokens"]),
                )
                for name, values in entries.items()
            }
        )

    def get(self, model: str) -> ModelPricing | None:
        return self._models.get(model)

    def calculate(self, model: str, input_tokens: int, output_tokens: int) -> float | None:
        pricing = self.get(model)
        if pricing is None:
            return None
        return (
            input_tokens * pricing.input_usd_per_million_tokens
            + output_tokens * pricing.output_usd_per_million_tokens
        ) / 1_000_000
