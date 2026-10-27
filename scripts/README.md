# Helper scripts

Run these from the repository root after installing `requirements.txt`.

- `python scripts/erp_admin.py --help` — create users and roles, change
  passwords, and manage permissions through the supported admin API.
- `python scripts/mcp_client.py` — log in and list the tools visible to a user.
- `python scripts/mcp_client.py BAPI_VENDOR_GETLIST` — call a tool.

Passwords are prompted securely; neither script accepts a password on the
command line. See [`docs/AUTHENTICATION.md`](../docs/AUTHENTICATION.md) for the
complete setup, command examples, environment variables, and agent connection
instructions.
