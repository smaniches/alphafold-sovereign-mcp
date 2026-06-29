FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir alphafold-sovereign-mcp

ENTRYPOINT ["alphafold-sovereign-mcp"]
