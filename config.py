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
    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_user: str = "koubo"
    db_password: str = "koubo"
    db_name: str = "koubo"

    openai_api_key: str = ""
    default_llm_provider: str = "openai"
    default_llm_model: str = "gpt-4o-mini"

    # 默认 UA 改用浏览器 UA，避免被 SSR 站点（如 InfoQ）当作爬虫返回空壳 HTML
    fetch_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    job_poll_interval_seconds: float = 2.0

    # 定时抓取调度。scheduler_enabled 关闭则不自动抓取。
    # scheduler_fetch_check_interval_minutes：调度器轮询间隔，到期源才会入队抓取。
    # scheduler_topic_enabled 默认关闭——generate_topic 会消耗 LLM，按约束不自动触发。
    scheduler_enabled: bool = True
    scheduler_fetch_check_interval_minutes: int = 30
    scheduler_topic_enabled: bool = False
    scheduler_topic_cron: str = "30 9 * * *"

    # 联网搜索（V0.3）。默认关闭，需配置 TAVILY_API_KEY 并开启开关才会发起联网搜索。
    web_search_enabled: bool = False
    web_search_provider: str = "tavily"
    tavily_api_key: str = ""
    tavily_search_depth: str = "basic"  # basic=1 credit, advanced=2 credits
    tavily_max_results: int = 10
    tavily_extract_max_urls: int = 5  # 每 5 个 URL 约 1 credit
    tavily_monthly_credit_budget: int = 800  # 预留 200 安全余量
    tavily_per_topic_credit_budget: int = 3


settings = Settings()
