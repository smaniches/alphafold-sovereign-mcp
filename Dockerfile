FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

COPY . .
RUN pip install --no-cache-dir .

ENTRYPOINT ["alphafold-sovereign-mcp"]
