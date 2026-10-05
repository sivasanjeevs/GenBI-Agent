"""
config.py – Centralised settings via pydantic-settings.

All values are loaded from environment variables / .env file.
Oracle env vars use the ORACLE_ prefix; the spec aliases DB_* are
accepted as well (via validation_alias on each field).

Required at runtime:
  ORACLE_PASSWORD (or DB_PASSWORD)
  GEMINI_API_KEY
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Oracle / DB ───────────────────────────────────────────────────────────
    oracle_host: str = Field(
        "20.102.78.61",
        description="Oracle DB host",
        validation_alias=AliasChoices("ORACLE_HOST", "DB_HOST"),
    )
    oracle_port: int = Field(
        1521,
        description="Oracle DB port",
        validation_alias=AliasChoices("ORACLE_PORT", "DB_PORT"),
    )
    oracle_service: str = Field(
        "FREEPDB1",
        description="Oracle service name",
        validation_alias=AliasChoices("ORACLE_SERVICE", "DB_SERVICE"),
    )
    oracle_user: str = Field(
        "VF_AGENT",
        description="Oracle read-only user",
        validation_alias=AliasChoices("ORACLE_USER", "DB_USER"),
    )
    oracle_password: str = Field(
        ...,
        description="Oracle password (never commit!)",
        validation_alias=AliasChoices("ORACLE_PASSWORD", "DB_PASSWORD"),
    )

    # SCHEMAS: comma-separated string in env, exposed as list[str] via property.
    # Accepts SCHEMAS or ORACLE_SCHEMAS env var.
    oracle_schemas: str = Field(
        "VID,GENAIVF",
        description="Comma-separated schemas to explore",
        validation_alias=AliasChoices("SCHEMAS", "ORACLE_SCHEMAS"),
    )

    @property
    def schemas(self) -> list[str]:
        """Return upper-cased schema names as a list."""
        return [s.strip().upper() for s in self.oracle_schemas.split(",") if s.strip()]

    @property
    def dsn(self) -> str:
        return f"{self.oracle_host}:{self.oracle_port}/{self.oracle_service}"

    # ── LLM ───────────────────────────────────────────────────────────────────
    llm_provider: str = Field(
        "gemini",
        description="LLM provider: gemini | openai | anthropic | ollama",
    )
    llm_model: str = Field(
        "gemini-3.1-pro-preview",
        description="Primary model identifier (LLM_MODEL)",
    )
    llm_model_fast: str = Field(
        "gemini-3.5-flash-lite",
        description=(
            "Fallback / fast model used when the primary model "
            "repeatedly fails (LLM_MODEL_FAST)"
        ),
    )
    gemini_api_key: str = Field("", description="Gemini API key")
    openai_api_key: str = Field("", description="OpenAI API key")
    anthropic_api_key: str = Field("", description="Anthropic API key")
    ollama_base_url: str = Field(
        "http://localhost:11434", description="Ollama base URL"
    )

    # Analytical tasks: deterministic output is essential
    llm_temperature: float = Field(0.0, description="LLM temperature (0 = deterministic)")
    llm_max_tokens: int = Field(8192, description="Max output tokens")

    @field_validator("gemini_api_key")
    @classmethod
    def _require_gemini_key_for_gemini_provider(
        cls, v: str, info: "FieldValidationInfo"  # type: ignore[name-defined]
    ) -> str:
        # We cannot access other fields during a single-field validator reliably
        # across pydantic versions, so just return v; runtime check is in llm.py.
        return v

    # ── LLM Disk Cache ────────────────────────────────────────────────────────
    llm_cache_enabled: bool = Field(True, description="Cache LLM responses to disk")
    llm_cache_dir: Path = Field(Path(".llm_cache"), description="Cache directory")

    # ── Semantic Layer ────────────────────────────────────────────────────────
    semantic_layer_dir: Path = Field(
        Path("semantic_layer"), description="Semantic layer output dir"
    )
    overrides_file: Path = Field(Path("semantic_layer/overrides.yaml"))
    changelog_file: Path = Field(Path("semantic_layer/changelog.json"))

    # ── Eval ──────────────────────────────────────────────────────────────────
    eval_output_dir: Path = Field(Path("eval_output"), description="Eval results dir")
    benchmark_file: Path = Field(Path("benchmark/questions.json"))
    eval_runs: int = Field(3, description="Repetitions per question for consistency")

    # ── Server ────────────────────────────────────────────────────────────────
    api_host: str = Field("0.0.0.0")
    api_port: int = Field(8000)
    log_level: str = Field("INFO")

    # ── SQL Execution ─────────────────────────────────────────────────────────
    sql_max_rows: int = Field(500, description="Hard cap on rows returned")
    sql_timeout_seconds: int = Field(30, description="Query timeout in seconds")
    sql_repair_attempts: int = Field(3, description="Auto-repair retry limit")


# Singleton – import this everywhere
settings = Settings()
