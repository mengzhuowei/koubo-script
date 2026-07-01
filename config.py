"""应用配置：通过 .env 与 pydantic-settings 加载，所有字段均有默认值，缺 .env 也能启动。"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    # MySQL 连接配置
    # 连接目标：本地 127.0.0.1，Docker compose 内为 mysql；端口固定 3306
    db_host: str = "127.0.0.1"
    db_port: int = 3306
    # 凭据/库名：与 docker-compose.yml 的 MySQL 容器初始化参数共用一套
    # （DB_USER / DB_PASSWORD / DB_NAME），避免重复配置
    db_user: str = "koubo"
    db_password: str = "koubo"
    db_name: str = "koubo"

    openai_api_key: str = ""
    default_llm_provider: str = "openai"
    default_llm_model: str = "gpt-4o-mini"

    fetch_user_agent: str = "AgentScriptRadar/0.1"
    job_poll_interval_seconds: float = 2.0

    # 定时抓取调度。scheduler_enabled 关闭则不自动抓取。
    # scheduler_fetch_check_interval_minutes：调度器轮询间隔，到期源才会入队抓取。
    # scheduler_topic_enabled 默认关闭——generate_topic 会消耗 LLM，按约束不自动触发。
    scheduler_enabled: bool = True
    scheduler_fetch_check_interval_minutes: int = 30
    scheduler_topic_enabled: bool = False
    scheduler_topic_cron: str = "30 9 * * *"


settings = Settings()
