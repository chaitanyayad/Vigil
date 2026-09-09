from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://vigil:vigil@localhost:5433/vigil"
    redis_url: str = "redis://localhost:6379/0"

    admin_username: str = "admin"
    admin_password: str = "change-me"
    jwt_secret: str = "dev-secret-do-not-use-in-prod"
    jwt_ttl_hours: int = 12

    # LLM triage — Google Gemini (free tier keys from https://aistudio.google.com/apikey)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_embed_model: str = "gemini-embedding-001"
    triage_timeout_seconds: float = 20.0
    triage_max_output_tokens: int = 1024
    triage_cooldown_minutes: int = 10

    # Ledger / chain
    ledger_enabled: bool = True
    chain_rpc_url: str = "http://localhost:8545"
    chain_id: int = 31337
    ledger_private_key: str = ""
    ledger_contract_address: str = ""
    ledger_batch_interval_seconds: int = 300
    ledger_batch_max_events: int = 500

    # ML
    ml_artifact_dir: str = "./ml_artifacts"
    ml_anomaly_score_threshold: float = -0.15
    ml_resolve_after_normal_minutes: int = 5

    # Watchdog
    heartbeat_offline_seconds: int = 45
    watchdog_interval_seconds: int = 10

    runbooks_dir: str = "./runbooks"


@lru_cache
def get_settings() -> Settings:
    return Settings()
