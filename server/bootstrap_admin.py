"""One-time admin creation from inside the running container, never over HTTP/MCP."""
import getpass
import sys

from server.db import DB_PATH, db_exists, init_schema, migrate_schema
from server.security import bootstrap_admin


def main():
    if not db_exists(DB_PATH):
        init_schema(DB_PATH)
    migrate_schema(DB_PATH)
    if not sys.stdin.isatty():
        raise SystemExit("Bootstrap requires an interactive terminal")
    username = input("Admin username: ").strip()
    password = getpass.getpass("Admin password: ")
    if password != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords do not match")
    try:
        bootstrap_admin(username, password)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print("Administrator created")


if __name__ == "__main__":
    main()
