# Note Management Agent

Purpose:
- capture note text and attachments from an upstream agent
- file notes into Nextcloud using Inbox + PARA defaults
- keep attachment uploads and note writes behind the Nextcloud MCP server
- support AI best-match note retrieval for recall questions

Environment:
- `DECISION_API_BASE_URL`: internal decision-system API base URL used for note indexing/search, for Docker use `http://decision-api:8000/v1`
- `NEXTCLOUD_MCP_URL` or `MCP_SERVER_URL`: streamable HTTP MCP endpoint, for Docker use `http://nextcloud-mcp:8000/mcp`
- `NOTE_AGENT_ROOT`: root folder for managed notes, default `/Notes/FamilyCloud`
- `NOTE_AGENT_DROP_FOLDER`: optional ingestion folder, default `/Notes/FamilyCloud/Inbox/Drop`
- `NOTE_AGENT_READY_TAG_NAME`: Nextcloud collaborative/system tag used for ingest gating, default `ready`
- `NOTE_AGENT_AUTO_INGEST_READY_ENABLED`: enable background polling for ready inbox files
- `NOTE_AGENT_AUTO_INGEST_INTERVAL_SECONDS`: polling interval when auto-ingest is enabled
- `NOTE_AGENT_AUTO_INGEST_ACTOR`: actor email used for automatic ingest runs
- `NOTE_AGENT_AUTO_INGEST_FAMILY_ID`: family id used for automatic ingest runs
- `NOTE_AGENT_DRY_RUN`: if `true`, skip writes and return planned paths
- `DEBUG`: if `true`, include debug payloads in API responses
- `PYDANTIC_AI_MODEL`: follows the repo-wide LLM pattern used by the decision agent

Folder conventions:
- `Inbox/`: default landing zone when filing confidence is low
- `Projects/`, `Areas/`, `Resources/`, `Archive/`: PARA destinations when confidence is high enough
- `Inbox/Attachments/<session_id>/`: uploaded media path for invoke attachments

Ready-ingest rules:
- `POST /v1/agents/note/ingest` scans `NOTE_AGENT_ROOT/Inbox`
- only inbox files returned by MCP tool `nc_webdav_list_ready_files` are processed
- a file is ready only when it carries the real Nextcloud collaborative/system tag configured by `NOTE_AGENT_READY_TAG_NAME`
- raw sources are archived under `Archive/Raw/<collection>/<year>/`
- polished notes are written with `date-title` filenames, for example `2025-11-30-his-name-will-be.md`
- church/service notes default to `Areas/Church/`
- polished notes include a `## Source` section with a link to the archived raw file
- PDFs and parseable documents are classified from extracted text before filename fallback
- image/document ingest falls back to filename and metadata when OCR/parsed text is weak
- successful capture and ingest operations upsert searchable note documents into the decision-system note index

Retrieval rules:
- `POST /v1/agents/note/retrieve` accepts a natural-language query and returns ranked note matches
- query interpretation resolves simple relative date phrases such as `last week`, `this week`, `today`, and `last month`
- retrieval combines metadata filtering, lexical scoring, semantic scoring, and heuristic reranking
- polished notes are preferred for answerability, but raw-note links are returned when available
- retrieval indexing/search requires the decision-system API profile to be running

Example:

```bash
curl -sS \
  -H 'Content-Type: application/json' \
  -H 'X-Dev-User: mrjamescallender@gmail.com' \
  -d '{
    "session_id":"notes-1",
    "message":"Met with contractor. Need estimate for kitchen remodel; prefer timeline before April. Also check permits.",
    "actor":"mrjamescallender@gmail.com",
    "family_id":2,
    "attachments":[]
  }' \
  http://localhost:8003/v1/agents/note/invoke
```

Manual ingest example:

```bash
curl -sS \
  -H 'Content-Type: application/json' \
  -H 'X-Dev-User: mrjamescallender@gmail.com' \
  -d '{
    "session_id":"ingest-1",
    "actor":"mrjamescallender@gmail.com",
    "family_id":2,
    "max_items":10
  }' \
  http://localhost:8003/v1/agents/note/ingest
```

Retrieval example:

```bash
curl -sS \
  -H 'Content-Type: application/json' \
  -H 'X-Dev-User: mrjamescallender@gmail.com' \
  -d '{
    "actor":"mrjamescallender@gmail.com",
    "family_id":2,
    "query":"What did I learn in sunday service last week?",
    "top_k":5,
    "include_content":true
  }' \
  http://localhost:8003/v1/agents/note/retrieve
```

Verify MCP connectivity:
- `curl http://localhost:8003/healthz`
- `docker compose --profile agents logs --tail=200 note-agent`
- startup logs include discovered Nextcloud MCP tool names
- `docker compose --profile agents logs --tail=200 nextcloud-mcp`
- overlay startup logs include `registered_custom_tool name=nc_webdav_list_ready_files`
