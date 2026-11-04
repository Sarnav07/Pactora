FROM ghcr.io/astral-sh/uv:0.11.15 AS uv
FROM python:3.12-slim-bookworm
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable && \
    useradd --uid 10001 --create-home executor && \
    mkdir /state && chown executor:executor /state
USER 10001:10001
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENTRYPOINT ["pactora", "serve", "--config", "/run/secrets/config.json", "--host", "0.0.0.0"]
