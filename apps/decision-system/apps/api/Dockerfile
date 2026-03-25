FROM node:22-bookworm-slim AS node_runtime

FROM python:3.12-slim

WORKDIR /app

COPY --from=node_runtime /usr/local/ /usr/local/

COPY apps/decision-system/apps/api/requirements.txt /app/requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt

# Copy the API code to /app so `uvicorn app.main:app` resolves correctly.
COPY apps/decision-system/apps/api/ /app/

# Repo-level agents (shared across domains).
COPY agents /app/agents

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
