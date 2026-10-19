# Architecture

## Overview

The server exposes ERP BAPI-like functions as MCP tools over streamable HTTP.
State is persisted in SQLite. Each BAPI call is a single transaction.

## Runtime flow

1) `server.entrypoint` checks DB existence
2) If missing, `init_schema()` + `data.seed.run_seed()`
3) Always runs `migrate_schema()`
4) Starts MCP server via `server.mcp_server`

## Key modules

- `server/db.py`
  - owns sqlite connection lifecycle
  - `get_conn()` commits on success, rolls back on exception
  - `bapi_result()` and `bapi_error()` standardize response shape
- `server/mcp_server.py`
  - creates `MCPServer`
  - discovers/registers all `BAPI_*` functions from `server/bapi/*`
  - enforces tool-level authorization in middleware
  - hosts auth and admin HTTP routes
- `server/security.py`
  - password hashing/verification (PBKDF2-HMAC-SHA256)
  - session token issuance and lookup
  - role/user permission resolution
  - admin mutation operations
- `data/seed.py`
  - creates synthetic data by calling BAPI functions (not raw SQL)

## Tool discovery model

All functions named `BAPI_*` in these modules are auto-registered:

- `server/bapi/vendor.py`
- `server/bapi/material.py`
- `server/bapi/purchasing.py`
- `server/bapi/customer.py`
- `server/bapi/sales.py`
- `server/bapi/finance.py`
- `server/bapi/hr.py`

To add a new tool, define a `BAPI_*` function in the relevant module.

## Data model summary

Core tables:

- Master data: `vendors`, `customers`, `materials`, `stock`
- Purchasing/sales: `purchase_orders`, `po_items`, `goods_receipts`,
  `sales_orders`, `so_items`
- Finance: `invoices`, `payments`, `gl_accounts`, `gl_postings`,
  `journal_entries`, `journal_lines`
- HR/payroll: `departments`, `employees`, `leave_requests`,
  `payroll_runs`, `payslips`
- Security: `users`, `roles`, `user_roles`, `role_tools`, `user_tools`,
  `sessions`, `security_events`

## Transaction boundaries and invariants

- One BAPI call = one DB unit of work.
- `BAPI_GOODSMVT_CREATE` updates stock and marks PO `RECEIVED`.
- `BAPI_SALESORDER_CREATE` validates stock before decrementing.
- AP/AR payment posting requires exact invoice amount.
- Journal postings must balance debits and credits.
- Payroll run posts one payslip + balanced journal entry per employee.

## Migrations

- Base schema: `data/schema.sql`
- Incremental files: `data/migration_001.sql`, `data/migration_002.sql`
- Version tracked by `PRAGMA user_version`.
