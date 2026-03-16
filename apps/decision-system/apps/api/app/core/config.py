from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    auth_mode: str = "none"  # none | forwardauth
    internal_admin_token: str = "change-me"
    root_path: str = ""

    postgres_db: str = "decision_system"
    postgres_user: str = "decision_user"
    postgres_password: str = "decision_pass"
    postgres_host: str = "db"
    postgres_port: int = 5432
    redis_host: str = "redis"
    redis_port: int = 6379

    # Keycloak (for group -> family sync)
    keycloak_base_url: str = "http://keycloak:8080"
    keycloak_realm: str = "familycloud"
    keycloak_sync_client_id: str = "decision-system-sync"
    keycloak_sync_client_secret: str = ""
    keycloak_sync_group_suffix: str = "_family"
    openai_api_key: str = ""
    note_embedding_model: str = "text-embedding-3-small"
    note_embedding_timeout_seconds: float = 20.0
    task_vikunja_url: str = "http://vikunja:3456"
    task_vikunja_api_prefix: str = "/api/v1"
    task_vikunja_token: str = ""
    task_vikunja_token_file: str = ""
    task_hygiene_stale_days: int = 14
    task_hygiene_member_overload_open_tasks: int = 12

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
