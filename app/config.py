"""
config.py – centralised settings via pydantic-settings.
All values are loaded from environment variables / .env file.
"""

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Oracle ────────────────────────────────────────────────────────────────
    oracle_host: str = Field("20.102.78.61", description="Oracle DB host")
    oracle_port: int = Field(1521, description="Oracle DB port")
    oracle_service: str = Field("FREEPDB1", description="Oracle service name")
    oracle_user: str = Field("VF_AGENT", description="Oracle read-only user")
    oracle_password: str = Field(..., description="Oracle password (never commit!)")

    # Target schemas to introspect (comma-separated)
    oracle_schemas: str = Field("VID,GENAIVF", description="Schemas to explore")

    @property
    def schemas(self) -> list[str]:
        return [s.strip().upper() for s in self.oracle_schemas.split(",") if s.strip()]

    @property
    def dsn(self) -> str:
        return f"{self.oracle_host}:{self.oracle_port}/{self.oracle_service}"

    # ── LLM ───────────────────────────────────────────────────────────────────
    llm_provider: str = Field("gemini", description="gemini | openai | anthropic | ollama")
    llm_model: str = Field("gemini-2.0-flash", description="Model identifier")
    gemini_api_key: str = Field("", description="Gemini API key")
    openai_api_key: str = Field("", description="OpenAI API key")
    anthropic_api_key: str = Field("", description="Anthropic API key")
    ollama_base_url: str = Field("http://localhost:11434", description="Ollama base URL")

    # Max tokens in LLM response
    llm_max_tokens: int = Field(8192, description="Max output tokens")
    # Temperature for analytical tasks (low = deterministic)
    llm_temperature: float = Field(0.1, description="LLM temperature")

    # ── LLM Disk Cache ────────────────────────────────────────────────────────
    llm_cache_enabled: bool = Field(True, description="Cache LLM responses to disk")
    llm_cache_dir: Path = Field(Path(".llm_cache"), description="Cache directory")

    # ── Semantic Layer ────────────────────────────────────────────────────────
    semantic_layer_dir: Path = Field(Path("semantic_layer"), description="Output dir")
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

    # ── SQL ───────────────────────────────────────────────────────────────────
    sql_max_rows: int = Field(500, description="Hard cap on rows returned")
    sql_timeout_seconds: int = Field(30, description="Query timeout in seconds")
    sql_repair_attempts: int = Field(3, description="Auto-repair retry limit")


# Singleton – import this everywhere
settings = Settings()
