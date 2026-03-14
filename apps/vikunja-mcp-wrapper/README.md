# Vikunja MCP Wrapper

This wrapper runs the upstream MCP server package `vikunja-mcp` (PyPI) inside Docker using stdio transport.

## Pinned Version

- Upstream package: `vikunja-mcp`
- Pinned version: `0.9.3`

## Required Environment Variables

- `VIKUNJA_URL` (example: `http://vikunja:3456`)
- `VIKUNJA_TOKEN` (preferred when running directly)
- `VIKUNJA_TOKEN_FILE` (optional, wrapper will export `VIKUNJA_TOKEN` from this file)

## Secret Setup

Create the token secret file used by docker compose:

```bash
mkdir -p secrets
printf '%s\n' '<vikunja-api-token>' > secrets/vikunja_api_token
```

## Run via Docker Compose (stdio)

```bash
docker compose --profile ops up -d vikunja vikunja-db
docker compose --profile ops run --rm -T vikunja-mcp
```

## Local Validation

You can validate registration/tool discovery from your MCP client using the `vikunja-docker` server entry in `infra/openclaw.mcp.json`.

## Upgrade Procedure

1. Update `VIKUNJA_MCP_PYPI_VERSION` default in `.env.example` and compose build arg.
2. Rebuild the image:
   ```bash
   docker compose --profile ops build --no-cache vikunja-mcp
   ```
3. Run smoke checks (list projects, create/update/delete project, create/update/delete task).
