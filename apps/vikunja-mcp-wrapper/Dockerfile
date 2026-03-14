FROM python:3.12-slim

WORKDIR /app

ARG VIKUNJA_MCP_PYPI_VERSION=0.9.3
RUN pip install --no-cache-dir "vikunja-mcp==${VIKUNJA_MCP_PYPI_VERSION}"

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["vikunja-mcp"]
