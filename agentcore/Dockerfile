# AgentCore Runtime expects a linux/arm64 container listening on 8080.
FROM --platform=linux/arm64 python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY agentcore/ ./agentcore/

ENV PYTHONUNBUFFERED=1
ENV GNA_DB_PATH=/app/goodneighbor.db

EXPOSE 8080

CMD ["python", "agentcore/app.py"]
