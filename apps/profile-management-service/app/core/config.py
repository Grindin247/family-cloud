from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    root_path: str = ""
    internal_admin_token: str = "change-me"

    postgres_db: str = "profile_management"
    postgres_user: str = "profile_user"
    postgres_password: str = "profile_pass"
    postgres_host: str = "profile-db"
    postgres_port: int = 5432

    decision_api_base_url: str = "http://decision-api:8000/v1"
    decision_api_timeout_seconds: float = 20.0

    nats_url: str = "nats://nats:4222"
    nats_event_stream: str = "FAMILY_EVENTS"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
