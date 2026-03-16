# Family Cloud Shared Backend MCP Server

This MCP server is the repo-owned tool surface for OpenClaw agents. It exposes safe, structured tools for family data, decision workflows, shared ops, file-index metadata, and canonical family events.

## Safety Model

All mutable operations must follow:

1. `propose_changes`
2. `confirm_proposal`
3. `commit_proposal`

Nothing is persisted until `commit_proposal`.

Destructive operations (`delete_*`) are blocked unless `allow_destructive=true` is set during proposal.

## Attribution

Every proposal/confirmation/commit includes:

- `actor_id` (required)
- `actor_name` (optional)

These are:

- Logged to `DECISION_MCP_AUDIT_LOG_PATH` (JSONL).
- Sent to API as `X-Decision-Actor-Id` and `X-Decision-Actor-Name` headers.

## Run (local)

```bash
cd apps/mcp
pip install -r requirements.txt
DECISION_API_BASE_URL=http://localhost:8000/v1 python server.py
```

## Run (docker compose)

```bash
docker compose --profile agent up -d mcp
```

## Example Agent Config (stdio)

```json
{
  "mcpServers": {
    "decision-system": {
      "command": "python",
      "args": ["apps/mcp/server.py"],
      "env": {
        "DECISION_API_BASE_URL": "http://localhost:8000/v1",
        "DECISION_MCP_AUDIT_LOG_PATH": ".decision_mcp_audit.jsonl"
      }
    }
  }
}
```

## Read Tools

- `server_health`
- `list_families`
- `list_family_members`
- `list_goals`
- `get_goal`
- `list_decisions`
- `get_decision`
- `list_roadmap_items`
- `get_budget_summary`
- `get_family_dna`
- `search_family_memory`
- `search_notes`
- `search_files`
- `list_family_events`
- `get_family_timeline`
- `get_family_event_counts`
- `get_family_event_time_series`
- `get_agent_session`

## Workflow Tools

- `propose_changes`
- `get_proposal`
- `confirm_proposal`
- `cancel_proposal`
- `commit_proposal`
- `put_agent_session`
- `delete_agent_session`
- `index_file_document`
- `record_family_event`
- `write_family_memory`
- `propose_family_dna_patch`
- `commit_family_dna_patch`
- `create_agent_question`
- `list_agent_questions`
- `update_agent_question`
- `mark_agent_question_asked`
- `resolve_agent_question`
- `record_agent_event`
- `query_agent_metrics`
- `get_playback_timeline`

## OpenClaw Guidance

- OpenClaw `decision-agent` should prefer this MCP server over container-local HTTP `exec` patterns for Family Cloud backend access.
- `tasks-agent` remains direct-to-Vikunja for core task CRUD in phase 1, but can use this MCP server for shared queue, telemetry, playback, metrics, and family-context support.
- `file-agent` should continue using Nextcloud MCP for file operations and use this MCP server for shared index, queue, telemetry, playback, and metadata support.
