from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    root_path: str = ""
    internal_admin_token: str = "change-me"

    postgres_db: str = "conversation_workspace"
    postgres_user: str = "conversation_user"
    postgres_password: str = "conversation_pass"
    postgres_host: str = "conversation-db"
    postgres_port: int = 5432

    decision_api_base_url: str = "http://decision-api:8000/v1"
    decision_api_timeout_seconds: float = 20.0

    openclaw_bin: str = "openclaw"
    openclaw_home: str = "/home/luvwrk777"
    openclaw_gateway_url: str = ""
    openclaw_gateway_token: str = ""
    openclaw_timeout_seconds: int = 60
    openclaw_followup_timeout_seconds: int = 180
    openclaw_followup_poll_interval_seconds: float = 1.0
    openclaw_delivery_channel: str = "discord"

    uploads_dir: str = "/tmp/conversation-workspace/uploads"
    message_context_limit: int = 10
    summary_context_limit: int = 16

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def uploads_path(self) -> Path:
        return Path(self.uploads_dir)


settings = Settings()
