FROM python:3.12-slim

WORKDIR /app

COPY apps/file-management-service/requirements.txt /app/requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt

COPY apps/file-management-service/ /app/
COPY agents /app/agents

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
