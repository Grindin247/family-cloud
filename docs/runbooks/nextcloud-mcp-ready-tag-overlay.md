# Nextcloud MCP Ready-Tag Overlay

FamilyCloud builds `nextcloud-mcp` from the upstream image and adds one MCP tool:

- `nc_webdav_list_ready_files`

Purpose:
- expose real Nextcloud collaborative/system-tag discovery to the note agent
- avoid heuristic ingest based on filenames or markdown content

Build and start:

```bash
docker compose --profile agents up -d --build nextcloud-mcp note-agent
```

Expected startup signal:

```text
registered_custom_tool name=nc_webdav_list_ready_files
```

Ready-tag behavior:
- tag the inbox file in Nextcloud UI with the collaborative tag `ready`
- the note agent ingest endpoint will process only files returned by `nc_webdav_list_ready_files`
- untagged files are ignored even if their filename or content says `ready`

Upgrade guidance:
- keep `NEXTCLOUD_MCP_BASE_IMAGE` pinned to a digest
- rebuild after changing the base image
- if startup fails with an unsupported upstream contract error, re-check the overlay script against the new upstream Python module layout
