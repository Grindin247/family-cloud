ARG NEXTCLOUD_MCP_BASE_IMAGE=ghcr.io/cbcoutinho/nextcloud-mcp-server@sha256:a48f8f30bd7a5bc4d102e95ab0acca445a8969da460285926053805a83dbbf56
FROM ${NEXTCLOUD_MCP_BASE_IMAGE}

WORKDIR /opt/family-cloud

COPY entrypoint.sh /opt/family-cloud/entrypoint.sh
COPY patches/custom_nextcloud_mcp.py /opt/family-cloud/custom_nextcloud_mcp.py

RUN chmod +x /opt/family-cloud/entrypoint.sh

ENTRYPOINT ["sh", "/opt/family-cloud/entrypoint.sh"]
