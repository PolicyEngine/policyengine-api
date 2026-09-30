FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY policyengine_api ./policyengine_api
COPY gcp/cloud_run/start.sh ./start.sh

RUN chmod +x ./start.sh \
    && uv sync --frozen --no-dev --no-editable

ENV GATEWAY_AUTH_REQUIRED=1

CMD ["/bin/bash", "/app/start.sh"]
