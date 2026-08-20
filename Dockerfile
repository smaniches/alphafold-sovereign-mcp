FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/mcp

# The server persists its local SQLite knowledge graph under the invoking
# user's platform data directory by default. Give the runtime a real home and
# drop root before execution; /app itself only needs to remain readable.
RUN groupadd --gid 1000 mcp && \
    useradd --uid 1000 --gid mcp --shell /bin/sh --create-home mcp

COPY . .
RUN pip install --no-cache-dir .

USER mcp

ENTRYPOINT ["alphafold-sovereign-mcp"]
