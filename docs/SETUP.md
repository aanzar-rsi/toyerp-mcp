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
- `ERP_SEED_PROFILE`: `test`, `medium` (default), or `large`; only used when a
  database is first created
- `ERP_PUBLIC_URL`: public origin used by auth metadata and token validation
- `scripts/default_users.txt`: local/demo users in `username|password|role` format

## Docker setup (recommended)

### First-time setup: administrator, users, and agent testing

1. Copy the environment template and set unique passwords in
   `scripts/default_users.txt`:

   ```bash
   cp .env.example .env
   ```

   Edit `.env`:

   ```env
   MCP_PORT=8000
   ERP_PUBLIC_URL=http://127.0.0.1:8000
   ```

   The users file creates `ahad-anzar` as administrator and standard HR, finance,
   procurement, sales, inventory, master-data, and read-only users. Its checked-in
   passwords are for local demos only; change them before exposing the server.

2. Build and start the server:

   ```bash
   docker compose up --build -d
   docker compose logs -f toy-erp
   ```

   On first startup, the service creates the SQLite database, seeds ERP data,
   applies migrations, creates the file-defined users, and creates the standard role
   groups. Press `Ctrl+C` to stop following logs; the container continues to
   run in the background.

3. Verify the administrator can log in:

   ```bash
   curl -sS http://127.0.0.1:8000/auth/login \
     -H 'Content-Type: application/json' \
     -d '{"username":"ahad-anzar","password":"the-password-from-scripts/default_users.txt"}'
   ```

   The response contains an `access_token` valid for one hour.

4. Create a safe read-only test user and assign the built-in read-only role:

   ```bash
   docker compose exec -it -e ERP_ADMIN_USER=ahad-anzar toy-erp \
     python scripts/erp_admin.py create-user erp-test-agent

   docker compose exec -it -e ERP_ADMIN_USER=ahad-anzar toy-erp \
     python scripts/erp_admin.py assign-role erp-test-agent ERP_READ_ONLY
   ```

   The first command prompts for the test user's new password and the second
   prompts for the administrator password. `ERP_READ_ONLY` permits list, detail,
   and summary tools but no writes.

5. Test MCP access with the repository client:

   ```bash
   # List tools visible to the test user.
   docker compose exec -it toy-erp \
     python scripts/mcp_client.py --username erp-test-agent

   # Call a permitted, non-mutating tool.
   docker compose exec -it toy-erp \
     python scripts/mcp_client.py --username erp-test-agent BAPI_VENDOR_GETLIST
   ```

   Enter the test-user password when prompted. The second command returns seeded
   vendor data. A call to a write tool, such as `BAPI_VENDOR_CREATE`, must be
   denied for this user.

### Create domain users

Create a separate non-admin user for each agent or integration. Assign the
smallest standard role that permits its work:

| Role | Access |
| --- | --- |
| `ERP_READ_ONLY` | All list, detail, and summary tools |
| `HR_ALL` | HR, leave, and payroll tools |
| `FINANCE_ALL` | AP, AR, invoices, payments, and GL tools |
| `PROCUREMENT_ALL` | Vendors, materials, stock, purchase orders, and goods receipts |
| `SALES_ALL` | Customers, sales orders, AR invoices, and AR payments |
| `INVENTORY_ALL` | Materials, stock, and goods receipts |
| `MASTER_DATA_ALL` | Vendor, customer, and material tools |

For example, create a procurement agent:

```bash
docker compose exec -it -e ERP_ADMIN_USER=ahad-anzar toy-erp \
  python scripts/erp_admin.py create-user procurement-agent

docker compose exec -it -e ERP_ADMIN_USER=ahad-anzar toy-erp \
  python scripts/erp_admin.py assign-role procurement-agent PROCUREMENT_ALL
```

`*_ALL` roles can modify ERP data. Begin untrusted or newly developed agents
with `ERP_READ_ONLY`; use user-level grants only for narrowly required extra
tools. Never give an agent the `ahad-anzar` administrator account.

### Connect an MCP agent

Obtain a user token, entering the agent user's password when prompted:

```bash
docker compose exec -it toy-erp \
  python scripts/erp_admin.py login --username erp-test-agent
```

For an agent process running on the host, save the returned token in that shell:

```bash
export TOY_ERP_TOKEN='paste-token-here'
```

Use Streamable HTTP with the following settings:

```text
URL:    http://127.0.0.1:8000/mcp
Header: Authorization: Bearer <token>
```

For OpenCode V2, start OpenCode from the shell containing `TOY_ERP_TOKEN`, then
add this project-local `opencode.jsonc`:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "toy-erp": {
        "type": "remote",
        "url": "http://127.0.0.1:8000/mcp",
        "oauth": false,
        "protocol": "legacy",
        "headers": {
          "Authorization": "Bearer {env:TOY_ERP_TOKEN}"
        }
      }
    }
  }
}
```

Verify the connection:

```bash
opencode mcp list
```

The expected state is `toy-erp connected`. Test with a read-only prompt such as:

> List the available ERP tools, then summarize the first five vendors and open
> purchase orders. Do not make any changes.

Tokens expire after one hour. Obtain a fresh token and restart the agent process
with the updated `TOY_ERP_TOKEN` when that happens. Clear the token when done:

```bash
unset TOY_ERP_TOKEN
```

### Common Docker operations

```bash
# Follow logs
docker compose logs -f toy-erp

# Stop the server while preserving the database volume
docker compose down

# Start it again
docker compose up -d

# Revoke all tokens for a user
docker compose exec -it -e ERP_ADMIN_USER=ahad-anzar toy-erp \
  python scripts/erp_admin.py revoke-sessions erp-test-agent

# Disable a user and revoke their sessions immediately
docker compose exec -it -e ERP_ADMIN_USER=ahad-anzar toy-erp \
  python scripts/erp_admin.py set-user-active erp-test-agent inactive
```

### Basic setup

```bash
cp .env.example .env
docker compose up --build
```

On first boot:

1) Creates database if missing
2) Applies base schema
3) Seeds synthetic ERP data
4) Applies migrations
5) Creates users from `scripts/default_users.txt` and standard role groups
6) Starts MCP server

## Local setup (without Docker)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m server.entrypoint
```

For detailed authentication-table setup, user and role administration, helper
scripts, and agent connection examples, see [Authentication, Users,
Permissions, and Agent Connections](AUTHENTICATION.md).

## Verify setup

### Health smoke checks

1) Login:

```bash
curl -sS http://127.0.0.1:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"ahad-anzar","password":"your-password"}'
```

2) Use returned token to call `/mcp` through your MCP client.

### Run tests

```bash
pytest tests/
```

## Common issues

- `401` on `/mcp`: missing/expired bearer token.
- Changed the users file after first startup: provisioning never replaces existing passwords;
  reset them through an administrator or recreate the local database.
- `Remote ERP_PUBLIC_URL must use HTTPS`: expected for non-localhost HTTP URLs.
