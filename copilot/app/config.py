"""Configuration from environment."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    signoz_url: str = os.getenv("SIGNOZ_URL", "http://127.0.0.1:8080")
    mcp_url: str = os.getenv("MCP_URL", "http://127.0.0.1:8000/mcp")
    signoz_api_key: str = os.getenv("SIGNOZ_API_KEY", "")
    slack_webhook_url: str = os.getenv("SLACK_WEBHOOK_URL", "")
    llm_provider: str = os.getenv("LLM_PROVIDER", "openai")  # openai | anthropic | groq | mock
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    otel_endpoint: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")
    service_name: str = os.getenv("OTEL_SERVICE_NAME", "incident-sentinel")
    llm_timeout_seconds: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "150"))
    max_steps: int = int(os.getenv("SENTINEL_MAX_STEPS", "8"))
    dedupe_seconds: int = int(os.getenv("SENTINEL_DEDUPE_SECONDS", "600"))
    max_concurrent: int = int(os.getenv("SENTINEL_MAX_CONCURRENT", "2"))
    # USD per 1M tokens (approx) for cost metrics
    price_input_per_mtok: float = float(os.getenv("PRICE_INPUT_PER_MTOK", "0.15"))
    price_output_per_mtok: float = float(os.getenv("PRICE_OUTPUT_PER_MTOK", "0.60"))
    cost_budget_usd: float = float(os.getenv("COST_BUDGET_USD", "5.0"))


settings = Settings()
