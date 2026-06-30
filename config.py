"""应用配置：通过 .env 与 pydantic-settings 加载，所有字段均有默认值，缺 .env 也能启动。"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    database_path: str = "data/app.sqlite"
    openai_api_key: str = ""
    default_llm_provider: str = "openai"
    default_llm_model: str = "gpt-4o-mini"

    fetch_user_agent: str = "AgentScriptRadar/0.1"
    job_heartbeat_timeout_seconds: int = 300
    job_poll_interval_seconds: float = 2.0

    @property
    def database_url(self) -> str:
        return str((BASE_DIR / self.database_path).replace("\\", "/"))

    @property
    def db_path(self) -> Path:
        return BASE_DIR / self.database_path


settings = Settings()
