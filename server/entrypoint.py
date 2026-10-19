"""Container entrypoint: init + seed the DB on first boot, then start the MCP server."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.db import DB_PATH, db_exists, init_schema, migrate_schema


def main():
    if not db_exists(DB_PATH):
        print(f"[entrypoint] {DB_PATH} not found, initializing schema + seed data...")
        init_schema(DB_PATH)
        from data.seed import run_seed
        run_seed()
        print("[entrypoint] seed complete")
    else:
        print(f"[entrypoint] using existing database at {DB_PATH}")
    migrate_schema(DB_PATH)

    from server.db import get_conn
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            print("[entrypoint] no admin yet; run `docker compose exec toy-erp python -m server.bootstrap_admin`", flush=True)

    from server.mcp_server import mcp
    mcp.run(
        transport="streamable-http",
        host=os.environ.get("MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("MCP_PORT", "8000")),
    )


if __name__ == "__main__":
    main()
