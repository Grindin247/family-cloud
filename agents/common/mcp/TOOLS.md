# Decision System MCP Tool Inventory

Source: `apps/decision-system/apps/mcp/server.py`.

Read tools:
- `server_health`
- `list_families`
- `list_family_members`
- `list_goals`
- `list_decisions`
- `list_roadmap_items`
- `get_budget_summary`

Workflow tools:
- `propose_changes`
- `get_proposal`
- `confirm_proposal`
- `cancel_proposal`
- `commit_proposal`

Notes:
- Mutable operations are expected to go through `propose_changes -> confirm_proposal -> commit_proposal`.
- Actor attribution is carried via `actor_id`/`actor_name` and sent to the API using headers.

