FROM python:3.12-slim

WORKDIR /app

COPY apps/decision-system/apps/worker/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/decision-system/apps/worker/ /app/
COPY agents /app/agents

CMD ["celery", "-A", "worker.celery_app", "worker", "--loglevel=INFO"]
