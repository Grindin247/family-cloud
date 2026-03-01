FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends antiword catdoc \
    && rm -rf /var/lib/apt/lists/*

COPY apps/note-agent/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/note-agent/app /app/app
COPY agents /app/agents

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
