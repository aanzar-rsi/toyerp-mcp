# Toy ERP MCP Server

Toy ERP backend that exposes SAP-style `BAPI_*` functions as MCP tools over
streamable HTTP. It is designed for agent/client integration testing with a
real schema, synthetic seed data, role-based tool access, and auth-protected
MCP calls.

## What you get

- Dockerized Python MCP server (`mcp` 2.x) with SQLite persistence.
- 34 ERP tools across vendor, purchasing, sales, finance/GL, HR, and payroll.
- HTTP auth (`/auth/login`, `/auth/logout`) and admin APIs (`/admin/*`) for
  user, role, and tool-permission management.
- First-boot schema init + synthetic data seeding; restart-safe migrations.
- Test suite covering ERP flows, migration safety, and security behavior.

## Table of contents

- [Quick start (Docker)](#quick-start-docker)
- [Quick start (local)](#quick-start-local)
- [Connect an MCP client](#connect-an-mcp-client)
- [Authentication and admin model](#authentication-and-admin-model)
- [BAPI tools](#bapi-tools)
- [How data and transactions work](#how-data-and-transactions-work)
- [Project structure](#project-structure)
- [Testing](#testing)
- [Deployment notes](#deployment-notes)
- [Documentation map](#documentation-map)

## Quick start (Docker)

```bash
cp .env.example .env
docker compose up --build
```

Then create the first admin user (one-time bootstrap):

```bash
docker compose exec toy-erp python -m server.bootstrap_admin
```

Notes:
- Compose publishes `127.0.0.1:${MCP_PORT}` by default (localhost only).
- On first run, the container initializes `/data/erp.db`, seeds data, and applies
  migrations.
- On later runs, existing data is preserved and pending migrations are applied.

## Quick start (local)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m server.entrypoint
```

Bootstrap admin locally (same DB):

```bash
python -m server.bootstrap_admin
```

## Connect an MCP client

1) Log in and get a bearer token:

```bash
curl -sS http://127.0.0.1:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"your-password"}'
```

2) Use `Authorization: Bearer <access_token>` when calling `/mcp`.

Python MCP SDK example:

```python
import asyncio
import httpx2
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client


async def main():
    token = "<access_token>"
    async with httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {token}"}
    ) as http:
        async with Client(
            streamable_http_client("http://127.0.0.1:8000/mcp", http_client=http),
            mode="legacy",
        ) as client:
            result = await client.call_tool("BAPI_VENDOR_GETLIST", {})
            print(result)


asyncio.run(main())
```

## Authentication and admin model

- `/mcp` requires a valid bearer token.
- Tokens are opaque session tokens stored as SHA-256 hashes in `sessions`.
- Token TTL is 1 hour.
- Failed login lockout: 5 attempts -> 15 minutes locked.
- `POST /auth/logout` revokes the current token.
- `set_user_active=false`, `reset_password`, and `revoke_sessions` revoke active
  sessions for affected users.

Admin operations are HTTP-only (`/admin/{operation}`), not MCP tools:

- `create_user`, `create_role`, `assign_role`, `remove_role`
- `grant_role_tool`, `revoke_role_tool`
- `grant_user_tool`, `deny_user_tool`, `clear_user_tool`
- `set_user_active`, `reset_password`, `revoke_sessions`

Permission resolution:

- Admin users: all registered tools.
- Non-admin users: union of role grants.
- User-level allow/deny overrides role grants.
- Tool visibility and invocation are both enforced at runtime.

## BAPI tools

All tools are discovered automatically by introspecting `BAPI_*` functions in
`server/bapi/*.py`.

Every tool returns:

```json
{"RETURN": [{"type": "S" | "E", "message": "..."}], "DATA": ...}
```

### Vendor

- `BAPI_VENDOR_CREATE`
- `BAPI_VENDOR_GETLIST`
- `BAPI_VENDOR_GETDETAIL`

### Material

- `BAPI_MATERIAL_CREATE`
- `BAPI_MATERIAL_GETLIST`
- `BAPI_MATERIAL_STOCK_GETLIST`

### Purchasing

- `BAPI_PO_CREATE`
- `BAPI_PO_GETDETAIL`
- `BAPI_PO_GETLIST`
- `BAPI_PO_CHANGE`
- `BAPI_GOODSMVT_CREATE`

### Customer/Sales

- `BAPI_CUSTOMER_CREATE`
- `BAPI_CUSTOMER_GETLIST`
- `BAPI_SALESORDER_CREATE`
- `BAPI_SALESORDER_GETLIST`

### Finance/GL

- `BAPI_INCOMINGINVOICE_CREATE`
- `BAPI_AP_PAYMENT_POST`
- `BAPI_AR_INVOICE_CREATE`
- `BAPI_AR_PAYMENT_POST`
- `BAPI_GL_ACCOUNT_GETLIST`
- `BAPI_GL_JOURNAL_POST`
- `BAPI_GL_JOURNAL_GETLIST`
- `BAPI_GL_ACCOUNT_SUMMARY`

### HR/Payroll

- `BAPI_HR_DEPARTMENT_CREATE`
- `BAPI_HR_DEPARTMENT_GETLIST`
- `BAPI_HR_EMPLOYEE_CREATE`
- `BAPI_HR_EMPLOYEE_GETLIST`
- `BAPI_HR_EMPLOYEE_GETDETAIL`
- `BAPI_HR_EMPLOYEE_CHANGE_STATUS`
- `BAPI_HR_LEAVE_REQUEST`
- `BAPI_HR_LEAVE_DECIDE`
- `BAPI_HR_LEAVE_GETLIST`
- `BAPI_HR_PAYROLL_RUN`
- `BAPI_HR_PAYSLIP_GETLIST`

## How data and transactions work

- Each BAPI call opens its own DB transaction via `get_conn()` and commits or
  rolls back atomically.
- `BAPI_GOODSMVT_CREATE` increments stock and marks PO `RECEIVED`.
- `BAPI_SALESORDER_CREATE` checks stock, then decrements stock on success.
- AP/AR payments post balanced journal entries (new flow) while legacy
  `gl_postings` data remains historical.
- Payroll run creates payslips and balanced journal lines per employee in one
  transaction.
- Migrations are versioned via `PRAGMA user_version`.

## Project structure

```text
data/
  schema.sql
  migration_001.sql
  migration_002.sql
  seed.py
server/
  db.py
  entrypoint.py
  mcp_server.py
  bootstrap_admin.py
  security.py
  bapi/
tests/
  test_bapi.py
  test_security.py
```

## Testing

Run everything:

```bash
pytest tests/
```

Run one test function:

```bash
pytest tests/test_bapi.py::test_ap_payment_updates_gl
```

## Deployment notes

- For non-localhost deployment, put HTTPS reverse proxy in front.
- Set `ERP_PUBLIC_URL=https://your-host`.
- Route `/auth/*`, `/admin/*`, and `/mcp` to this service.
- Keep container port private to the proxy.
- Add proxy-level rate limiting on `/auth/login`.

## Documentation map

- Setup and environment: `docs/SETUP.md`
- Architecture and data flow: `docs/ARCHITECTURE.md`
- Security and access control: `docs/SECURITY.md`
- Collaboration workflow: `CONTRIBUTING.md`

## Scope cuts (intentional)

- SQLite backend (single-process toy ERP, not distributed HA storage).
- No ORM (plain `sqlite3` + parameterized SQL).
- No partial PO receipt reconciliation.
- Leave is calendar-day based (no holiday/work-calendar engine).
- Payroll pays full monthly salary for eligible employees (no proration logic).
