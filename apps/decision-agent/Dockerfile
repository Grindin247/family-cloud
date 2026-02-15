FROM python:3.12-slim

WORKDIR /app

COPY apps/decision-agent/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/decision-agent/app /app/app
COPY agents /app/agents

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

