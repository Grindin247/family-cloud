from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    root_path: str = ""
    internal_admin_token: str = "change-me"

    postgres_db: str = "question_management_service"
    postgres_user: str = "question_user"
    postgres_password: str = "question_pass"
    postgres_host: str = "question-db"
    postgres_port: int = 5432

    redis_host: str = "decision-redis"
    redis_port: int = 6379

    decision_api_base_url: str = "http://decision-api:8000/v1"
    decision_api_timeout_seconds: float = 20.0

    question_default_timezone: str = "America/New_York"
    question_quiet_hours_start: int = 22
    question_quiet_hours_end: int = 8
    question_daytime_start: int = 10
    question_daytime_end: int = 19
    question_learning_min_attempts: int = 4
    question_delivery_cooldown_minutes: int = 90
    question_post_answer_cooldown_minutes: int = 45
    question_claim_lease_seconds: int = 900
    question_task_auto_cap: int = 25
    question_merge_limit: int = 2
    question_requeue_stale_asked_hours: int = 72
    question_stale_pending_days: int = 45

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
