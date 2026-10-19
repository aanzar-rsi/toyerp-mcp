# Setup Guide

This project can run in Docker (recommended) or directly in a local Python
environment.

## Prerequisites

- Python 3.12+
- Docker + Docker Compose (for containerized run)

## Environment variables

Copy and edit the example file:

```bash
cp .env.example .env
```

Variables:

- `MCP_HOST`: MCP bind host (default `0.0.0.0`)
- `MCP_PORT`: MCP bind port (default `8000`)
- `DB_PATH`: SQLite DB file path (inside container defaults to `/data/erp.db`)
- `SEED_RANDOM`: random seed for deterministic synthetic data
- `ERP_PUBLIC_URL`: public origin used by auth metadata and token validation

## Docker setup (recommended)

```bash
cp .env.example .env
docker compose up --build
```

On first boot:

1) Creates database if missing
2) Applies base schema
3) Seeds synthetic ERP data
4) Applies migrations
5) Starts MCP server

Create the first admin user:

```bash
docker compose exec toy-erp python -m server.bootstrap_admin
```

## Local setup (without Docker)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m server.entrypoint
```

Then bootstrap admin in another terminal (same env):

```bash
python -m server.bootstrap_admin
```

## Verify setup

### Health smoke checks

1) Login:

```bash
curl -sS http://127.0.0.1:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"your-password"}'
```

2) Use returned token to call `/mcp` through your MCP client.

### Run tests

```bash
pytest tests/
```

## Common issues

- `401` on `/mcp`: missing/expired bearer token.
- `Bootstrap is only available before the first user is created`: admin user
  already exists in DB.
- `Remote ERP_PUBLIC_URL must use HTTPS`: expected for non-localhost HTTP URLs.
