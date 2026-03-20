from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    root_path: str = ""
    internal_admin_token: str = "change-me"

    postgres_db: str = "family_event_service"
    postgres_user: str = "family_event_user"
    postgres_password: str = "family_event_pass"
    postgres_host: str = "family-event-db"
    postgres_port: int = 5432

    redis_host: str = "decision-redis"
    redis_port: int = 6379

    decision_api_base_url: str = "http://decision-api:8000/v1"
    decision_api_timeout_seconds: float = 20.0

    task_vikunja_url: str = "http://vikunja:3456"
    task_vikunja_api_prefix: str = "/api/v1"
    task_vikunja_token: str = ""
    task_vikunja_token_file: str = ""
    task_vikunja_family_id: int = 2
    task_vikunja_webhook_secret: str = ""
    task_vikunja_webhook_target_url: str = ""
    task_vikunja_reconcile_lookback_minutes: int = 30

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
