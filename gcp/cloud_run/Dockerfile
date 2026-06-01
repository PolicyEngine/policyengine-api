FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential redis-server \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY policyengine_api ./policyengine_api
COPY gcp/cloud_run/start.sh ./start.sh

RUN chmod +x ./start.sh \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e .

ENV GATEWAY_AUTH_REQUIRED=1
ENV CACHE_REDIS_HOST=127.0.0.1
ENV CACHE_REDIS_PORT=6379
ENV CACHE_REDIS_DB=0

CMD ["/bin/sh", "/app/start.sh"]
