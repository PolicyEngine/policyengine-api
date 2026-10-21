FROM python:3.12
RUN uv sync --frozen --no-dev
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/
