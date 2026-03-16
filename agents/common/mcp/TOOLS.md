# Family Cloud Shared Backend MCP Tool Inventory

Source: `apps/decision-system/apps/mcp/server.py`.

Read tools:
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

Workflow tools:
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

Notes:
- Mutable operations are expected to go through `propose_changes -> confirm_proposal -> commit_proposal`.
- Actor attribution is carried via `actor_id`/`actor_name` and sent to the API using headers.
- Canonical shared family events are recorded through `record_family_event`; legacy `record_agent_event` remains for compatibility.
