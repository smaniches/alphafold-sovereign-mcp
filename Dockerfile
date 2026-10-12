FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

COPY --from=ghcr.io/astral-sh/uv:0.12.3@sha256:2d890623d310b57771ce840f0da5eed5fc6d657da05ffaa45d82797b53fa3abc /uv /usr/local/bin/uv

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/mcp \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH"

# The server persists its local SQLite knowledge graph under the invoking
# user's platform data directory by default. Give the runtime a real home and
# drop root before execution; /app itself only needs to remain readable.
RUN groupadd --gid 1000 mcp && \
    useradd --uid 1000 --gid mcp --shell /bin/sh --create-home mcp

COPY . .
RUN uv sync --locked --no-dev --no-editable

USER mcp

ENTRYPOINT ["alphafold-sovereign-mcp"]
