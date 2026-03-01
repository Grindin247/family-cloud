from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from agents.common.settings import settings as common_settings


class NoteAgentSettings(BaseSettings):
    nextcloud_mcp_url: str = Field(
        default="http://127.0.0.1:8002/mcp",
        validation_alias=AliasChoices("NEXTCLOUD_MCP_URL", "MCP_SERVER_URL"),
    )
    nextcloud_base_url: str = Field(
        default="https://nextcloud.family.callender",
        validation_alias=AliasChoices("NOTE_AGENT_NEXTCLOUD_BASE_URL", "NEXTCLOUD_PUBLIC_BASE_URL", "NEXTCLOUD_PUBLIC_ISSUER_URL"),
    )
    note_agent_root: str = "/Notes/FamilyCloud"
    note_agent_drop_folder: str = "/Notes/FamilyCloud/Inbox/Drop"
    note_agent_ready_tag_name: str = Field(default="ready", validation_alias=AliasChoices("NOTE_AGENT_READY_TAG_NAME", "NEXTCLOUD_READY_TAG_NAME"))
    note_agent_para_confidence_threshold: float = 0.75
    note_agent_scanned_pdf_vision_enabled: bool = True
    note_agent_scanned_pdf_vision_min_text_chars: int = 180
    note_agent_scanned_pdf_vision_max_initial_pages: int = 4
    note_agent_scanned_pdf_vision_max_total_pages: int = 10
    note_agent_scanned_pdf_render_dpi: int = 144
    note_agent_scanned_pdf_vision_confidence_threshold: float = 0.72
    note_agent_auto_ingest_ready_enabled: bool = False
    note_agent_auto_ingest_interval_seconds: int = 60
    note_agent_auto_ingest_actor: str = ""
    note_agent_auto_ingest_family_id: int = 0
    note_agent_dry_run: bool = False
    debug: bool = False
    pydantic_ai_model: str = common_settings.pydantic_ai_model
    http_timeout_seconds: float = common_settings.http_timeout_seconds
    http_max_retries: int = common_settings.http_max_retries

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


note_settings = NoteAgentSettings()
