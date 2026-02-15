# Domain Agent Template

Copy this folder to `agents/<your_agent>/` and implement:

- `agent.py`: main workflow/orchestration
- `tools.py`: tool adapters (MCP/HTTP/etc.)
- `prompts/`: prompt fragments (if using an LLM)
- `schemas.py`: Pydantic I/O contracts
- `tests/`: unit tests

