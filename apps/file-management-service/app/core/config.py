from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    root_path: str = ""
    internal_admin_token: str = "change-me"
    decision_internal_admin_token: str = "change-me"

    postgres_db: str = "file_management_service"
    postgres_user: str = "file_user"
    postgres_password: str = "file_pass"
    postgres_host: str = "file-db"
    postgres_port: int = 5432

    redis_host: str = "decision-redis"
    redis_port: int = 6379

    decision_api_base_url: str = "http://decision-api:8000/v1"
    decision_api_timeout_seconds: float = 20.0
    question_api_base_url: str = "http://question-api:8000/v1"
    question_api_timeout_seconds: float = 20.0

    nextcloud_mcp_url: str = "http://nextcloud-mcp:8000/mcp"
    file_self_api_base_url: str = "http://file-api:8000/v1"

    file_embedding_model_id: str = "BAAI/bge-small-en-v1.5"
    file_embedding_dim: int = 384
    file_embedding_batch_size: int = 8
    file_embedding_max_length: int = 512
    file_embedding_query_instruction: str = "Represent this sentence for searching relevant passages: "
    file_embedding_cache_dir: str = "/tmp/file-management-model-cache"

    file_chunk_size_chars: int = 1400
    file_chunk_overlap_chars: int = 200
    file_max_inline_content_chars: int = 4000
    file_max_body_chars: int = 16000
    file_max_excerpt_chars: int = 500
    file_max_text_extract_bytes: int = 4 * 1024 * 1024
    file_defer_ocr_page_limit: int = 12
    file_defer_ocr_size_limit_bytes: int = 20 * 1024 * 1024
    file_agent_new_doc_idle_minutes: int = 10
    file_agent_autofile_confidence_threshold: float = 0.70

    file_discovery_enabled: bool = True
    file_discovery_family_ids: str = "2"
    file_discovery_roots: str = "/Notes"
    file_discovery_scan_limit: int = 1000

    file_memory_mirror_enabled: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_broker_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    @property
    def redis_backend_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/1"

    @property
    def discovery_family_id_values(self) -> list[int]:
        values: list[int] = []
        for raw in self.file_discovery_family_ids.split(","):
            candidate = raw.strip()
            if not candidate:
                continue
            try:
                values.append(int(candidate))
            except ValueError:
                continue
        return values or [2]

    @property
    def discovery_root_values(self) -> list[str]:
        roots = [item.strip() for item in self.file_discovery_roots.split(",") if item.strip()]
        return roots or ["/Notes"]


settings = Settings()
