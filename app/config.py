"""Application settings, loaded from environment. Single source of truth."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "claims-triage-agent"
    environment: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"

    # --- Database (multi-tenant; every row is tenant-scoped) ---
    database_url: str = "postgresql+psycopg2://agent:agent@localhost:5432/agentdb"

    # --- Async workers ---
    redis_url: str = "redis://localhost:6379/0"

    # --- LLM (provider-agnostic client) ---
    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    llm_model: str = "claude-opus-4-8"
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # --- Fraud classifier ---
    # Fixed seed so the trained model is reproducible across runs and in tests.
    fraud_model_seed: int = 42
    # Fraud probability at/above this band routes the claim to closer review.
    fraud_high_threshold: float = 0.60
    fraud_review_threshold: float = 0.30

    # --- Settlement ---
    # Recommended payout = min(claim_amount, policy_limit) * this factor for a
    # standard covered claim (deterministic; the LLM never computes money).
    settlement_factor: float = 1.0

    # --- Auth ---
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"


@lru_cache
def get_settings() -> Settings:
    return Settings()
