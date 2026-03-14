# Task Management Agent

Purpose:
- extract actionable tasks from messages and attachments
- map tasks into intent-derived lists/projects (no fixed default list)
- reconcile purchase-like extracted content across all managed lists
- auto-create a project list when high-confidence clustering indicates related work and no relevant project exists
- provide read-only insights on request

API:
- `GET /healthz`
- `POST /v1/agents/tasks/invoke`

Tool backend:
- `TASK_AGENT_TOOLS_BACKEND=auto` (default): MCP-first per operation with REST fallback
- `TASK_AGENT_TOOLS_BACKEND=mcp`: strict MCP only
- `TASK_AGENT_TOOLS_BACKEND=rest`: REST only
- `TASK_AGENT_MCP_URL` defaults to `http://vikunja-mcp-http:8000/mcp`
- `TASK_AGENT_MCP_TIMEOUT_SECONDS` defaults to `10`

Auto-create project guardrails:
- cluster confidence `>= 0.86`
- at least 3 related tasks in cluster
- no existing project similarity above `0.72`
- not in explicit read-only mode

Insight mode:
- read-only by default
- returns due-soon/overdue/stale snapshots and recommendations
