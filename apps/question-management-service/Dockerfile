FROM python:3.12-slim

WORKDIR /app

COPY apps/question-management-service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/question-management-service/ /app/
COPY agents /app/agents

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
