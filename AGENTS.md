# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A toy ERP simulated as a Docker container that hosts an MCP server. The
server exposes 20 SAP-BAPI-style functions (`BAPI_<OBJECT>_<OP>`) as MCP
tools over streamable-HTTP, backed by SQLite. See README.md for the full
tool list and how to run/connect.

## Commands

```
python -m venv .venv && .venv/Scripts/activate     # or source .venv/bin/activate
pip install -r requirements.txt
pytest tests/                                       # run the test suite
python -m server.entrypoint                          # run the server locally (no Docker)
docker compose up --build                            # run containerized
```

There is no single-test-file shortcut needed — `tests/test_bapi.py` is one
file with one test function per domain (`pytest tests/test_bapi.py::test_ap_payment_updates_gl`
to run just one).

## Architecture

- **`data/schema.sql`** — the full table set (vendors, customers, materials,
  stock, purchase_orders/po_items, goods_receipts, sales_orders/so_items,
  invoices, payments, gl_accounts, gl_postings). `gl_accounts` is seeded with
  6 fixed rows (Accounts Payable/Receivable, Cash, Inventory, Sales Revenue,
  COGS) as part of the schema itself, not the data seeder.
- **`server/db.py`** — the only place that touches `sqlite3` directly.
  `get_conn()` is a context manager (commits on success, rolls back on
  exception); every BAPI function opens and closes its own connection — each
  BAPI call is one unit of work, mirroring how a real BAPI/RFC call commits
  its own LUW. `bapi_result()` / `bapi_error()` build the SAP-style
  `{"RETURN": [...], "DATA": ...}` response shape every tool returns.
- **`server/bapi/*.py`** — the 20 tool functions, grouped by domain (vendor,
  material, purchasing, customer, sales, finance). Plain functions, no
  decorators — `server/mcp_server.py` discovers every `BAPI_*` attribute
  across these modules by introspection and registers it via
  `mcp.add_tool(fn, name=attr)`. **To add a new tool: write a `BAPI_*`
  function in the right domain module — it is picked up automatically, no
  registration step needed.**
- **`server/mcp_server.py`** — builds the `MCPServer` instance and does the
  `BAPI_*` discovery/registration described above.
- **`server/entrypoint.py`** — container entrypoint. Checks whether the
  SQLite file at `DB_PATH` exists; if not, applies `schema.sql` and runs
  `data/seed.py`, then starts the MCP server. This is the only init path —
  there's no separate init container/job.
- **`data/seed.py`** — synthetic data generator. Deliberately calls the same
  `BAPI_*` functions the server exposes (rather than raw INSERTs) so seeded
  data and live-tool data go through identical code paths. Seeded with
  `SEED_RANDOM` (default 42) for reproducibility.

## MCP SDK version note

This project targets **`mcp` 2.x**. In 2.x, `FastMCP` was renamed to
`MCPServer` and moved to `mcp.server.mcpserver` (the old `mcp.server.fastmcp`
import raises immediately with a migration pointer). `host`/`port` are
passed to `.run(transport="streamable-http", host=..., port=...)`, not the
constructor. If `pip install` ever resolves `mcp` 1.x instead, the imports in
`server/mcp_server.py` will fail loudly — don't silently downgrade the
`mcp` pin to work around it without checking which API is actually installed
(`python -c "import mcp.server.mcpserver"` to confirm 2.x is present).

## Data flow / invariants worth knowing before changing tools

- `BAPI_GOODSMVT_CREATE` (goods receipt) is the only thing that increments
  `stock.qty_on_hand`, and it also unconditionally sets the PO's status to
  `RECEIVED` (no partial-quantity tracking — deliberate scope cut, see
  README).
- `BAPI_SALESORDER_CREATE` checks `stock.qty_on_hand` per line item before
  decrementing it; insufficient stock returns a `RETURN` error entry rather
  than raising.
- `BAPI_AP_PAYMENT_POST` / `BAPI_AR_PAYMENT_POST` are the only functions that
  write to `gl_postings` — they post two offsetting rows (AP/AR account and
  Cash) per payment. `BAPI_GL_ACCOUNT_GETLIST` computes balances by summing
  `gl_postings` at read time; there's no stored running balance.
- Every write is a single `with get_conn() as conn:` block per BAPI call —
  don't span a business transaction across two separate BAPI calls expecting
  atomicity between them (e.g. PO creation and its first goods receipt are
  two separate commits, matching real BAPI semantics).
