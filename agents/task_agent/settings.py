from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from agents.common.settings import settings as common_settings


class TaskAgentSettings(BaseSettings):
    pydantic_ai_model: str = common_settings.pydantic_ai_model
    http_timeout_seconds: float = common_settings.http_timeout_seconds
    http_max_retries: int = common_settings.http_max_retries

    task_agent_vikunja_url: str = Field(
        default="http://vikunja:3456",
        validation_alias=AliasChoices("TASK_AGENT_VIKUNJA_URL", "VIKUNJA_URL"),
    )
    task_agent_vikunja_api_prefix: str = Field(default="/api/v1", validation_alias=AliasChoices("TASK_AGENT_VIKUNJA_API_PREFIX"))
    task_agent_vikunja_token: str = Field(default="", validation_alias=AliasChoices("TASK_AGENT_VIKUNJA_TOKEN", "VIKUNJA_TOKEN"))
    task_agent_vikunja_token_file: str = Field(default="", validation_alias=AliasChoices("TASK_AGENT_VIKUNJA_TOKEN_FILE", "VIKUNJA_TOKEN_FILE"))
    task_agent_tools_backend: Literal["auto", "mcp", "rest"] = Field(default="auto", validation_alias=AliasChoices("TASK_AGENT_TOOLS_BACKEND"))
    task_agent_mcp_url: str = Field(default="http://vikunja-mcp-http:8000/mcp", validation_alias=AliasChoices("TASK_AGENT_MCP_URL"))
    task_agent_mcp_timeout_seconds: float = Field(default=10.0, validation_alias=AliasChoices("TASK_AGENT_MCP_TIMEOUT_SECONDS"))
    task_agent_default_timezone: str = Field(default="America/New_York", validation_alias=AliasChoices("TASK_AGENT_DEFAULT_TIMEZONE"))
    task_agent_advanced_features_require_confirmation: bool = Field(
        default=False,
        validation_alias=AliasChoices("TASK_AGENT_ADVANCED_FEATURES_REQUIRE_CONFIRMATION"),
    )
    task_agent_relation_default: str = Field(default="relates_to", validation_alias=AliasChoices("TASK_AGENT_RELATION_DEFAULT"))

    task_agent_project_autocreate_cluster_confidence: float = 0.86
    task_agent_project_autocreate_min_tasks: int = 3
    task_agent_project_existing_similarity_threshold: float = 0.72
    task_agent_reconcile_autocomplete_threshold: float = 0.78
    task_agent_reconcile_ambiguous_threshold: float = 0.55
    debug: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


task_settings = TaskAgentSettings()
