from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    """
    Shared runtime settings used by domain agents.

    Keep this intentionally small. Service-specific settings should live alongside
    the service, but agents can depend on these defaults.
    """

    app_env: str = "dev"

    # NATS / JetStream
    nats_url: str = "nats://nats:4222"
    nats_event_stream: str = "FAMILY_EVENTS"

    # Decision system API (when using HTTP adapter instead of MCP transport)
    decision_api_base_url: str = "http://localhost:8000/v1"
    file_api_base_url: str = "http://localhost:8070/v1"
    family_event_api_base_url: str = "http://localhost:8010/v1"
    question_api_base_url: str = "http://localhost:8030/v1"

    # Decision agent behavior
    decision_threshold_1_to_5: float = 4.0
    decision_max_followup_questions: int = 6
    decision_max_alignment_questions: int = 4
    decision_agent_autonomous_mode: bool = True
    decision_agent_shadow_mode: bool = False
    decision_pending_confirmation_ttl_seconds: int = 3600

    # Timeouts/retries for tool calls
    http_timeout_seconds: float = 20.0
    http_max_retries: int = 3

    # Semantic memory
    memory_embed_dim: int = 1536

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = AgentSettings()
