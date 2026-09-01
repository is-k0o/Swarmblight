from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    discord_token: str = ""
    discord_channel_id: int | None = None
    openai_api_key: str = ""
    coordinator_model: str = ""
    specialist_model: str = ""
    max_agent_rounds: int = Field(default=2, ge=0, le=10)
    max_specialists_per_round: int = Field(default=3, ge=1, le=3)
    max_knowledge_fragments: int = Field(default=5, ge=0, le=10)
    max_card_chars: int = Field(default=2500, ge=500, le=10000)
    source_chunk_max_chars: int = Field(default=6000, ge=200, le=50000)
    max_card_revisions: int = Field(default=1, ge=0, le=3)
    source_fidelity_gate_enabled: bool = False
    skaven_level: int = Field(default=2, ge=0, le=3)
    database_path: Path = Path("data/warpstone.db")
    knowledge_path: Path = Path("knowledge")
    pricing_path: Path = Path("pricing.json")
    max_output_tokens: int = Field(default=4000, ge=256)
    generator_max_output_tokens: int | None = Field(default=None, ge=256)
    critic_max_output_tokens: int | None = Field(default=None, ge=256)
    fidelity_max_output_tokens: int = Field(default=4000, ge=256, le=10000)
    daily_token_budget: int = Field(default=0, ge=0)
    daily_budget_usd: float = Field(default=0.0, ge=0.0)
    monthly_budget_usd: float = Field(default=0.0, ge=0.0)
    max_cost_per_run_usd: float = Field(default=0.0, ge=0.0)
    fail_on_unknown_pricing: bool = True
    estimated_chars_per_token: int = Field(default=4, ge=1, le=20)

    @field_validator("coordinator_model", "specialist_model")
    @classmethod
    def model_names_must_not_be_whitespace(cls, value: str) -> str:
        return value.strip()

    @field_validator("discord_channel_id", mode="before")
    @classmethod
    def empty_channel_id_means_all_channels(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def effective_generator_max_output_tokens(self) -> int:
        return (
            self.max_output_tokens
            if self.generator_max_output_tokens is None
            else self.generator_max_output_tokens
        )

    @property
    def effective_critic_max_output_tokens(self) -> int:
        return (
            self.max_output_tokens
            if self.critic_max_output_tokens is None
            else self.critic_max_output_tokens
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
