"""Manage toy ERP users and permissions through its authenticated HTTP API."""
import argparse
import getpass
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def post(url: str, path: str, payload: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        f"{url.rstrip('/')}{path}",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        try:
            message = json.load(exc).get("error", exc.reason)
        except (ValueError, AttributeError):
            message = exc.reason
        raise RuntimeError(f"HTTP {exc.code}: {message}") from exc
    except URLError as exc:
        raise RuntimeError(f"Cannot reach {url}: {exc.reason}") from exc


def read_password(label: str, confirm: bool = False) -> str:
    password = getpass.getpass(f"{label}: ")
    if confirm and password != getpass.getpass(f"Confirm {label.lower()}: "):
        raise RuntimeError("Passwords do not match")
    return password


def login(url: str, username: str, password: str) -> str:
    return post(url, "/auth/login", {"username": username, "password": password})["access_token"]


def command_payload(args: argparse.Namespace) -> tuple[str, dict]:
    command = args.command.replace("-", "_")
    if command in {"create_user", "reset_password"}:
        return command, {"username": args.username, "password": read_password("New user password", confirm=True)}
    if command == "set_user_active":
        return command, {"username": args.username, "active": args.status == "active"}
    payload = {}
    for name in ("username", "role", "tool"):
        if hasattr(args, name):
            payload[name] = getattr(args, name)
    return command, payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("ERP_URL", "http://127.0.0.1:8000"),
                        help="ERP origin (default: ERP_URL or http://127.0.0.1:8000)")
    parser.add_argument("--admin-user", default=os.environ.get("ERP_ADMIN_USER"),
                        help="administrator username (default: ERP_ADMIN_USER or prompt)")
    sub = parser.add_subparsers(dest="command", required=True)

    login_parser = sub.add_parser("login", help="log in as any user and print a one-hour bearer token")
    login_parser.add_argument("--username", default=os.environ.get("ERP_USERNAME"))

    for name in ("create-user", "reset-password"):
        action = sub.add_parser(name)
        action.add_argument("username")

    active = sub.add_parser("set-user-active")
    active.add_argument("username")
    active.add_argument("status", choices=("active", "inactive"))

    revoke = sub.add_parser("revoke-sessions")
    revoke.add_argument("username")

    role = sub.add_parser("create-role")
    role.add_argument("role")

    for name in ("assign-role", "remove-role"):
        action = sub.add_parser(name)
        action.add_argument("username")
        action.add_argument("role")

    for name in ("grant-role-tool", "revoke-role-tool"):
        action = sub.add_parser(name)
        action.add_argument("role")
        action.add_argument("tool")

    for name in ("grant-user-tool", "deny-user-tool", "clear-user-tool"):
        action = sub.add_parser(name)
        action.add_argument("username")
        action.add_argument("tool")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        if args.command == "login":
            username = args.username or input("Username: ").strip()
            print(login(args.url, username, read_password("Password")))
            return

        operation, payload = command_payload(args)
        supplied_token = os.environ.get("ERP_ADMIN_TOKEN")
        token = supplied_token
        if not token:
            admin_user = args.admin_user or input("Admin username: ").strip()
            token = login(args.url, admin_user, read_password("Admin password"))
        try:
            post(args.url, f"/admin/{operation}", payload, token)
        finally:
            if not supplied_token:
                post(args.url, "/auth/logout", {}, token)
        print(f"{operation} completed")
    except (RuntimeError, KeyError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
