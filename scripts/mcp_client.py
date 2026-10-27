"""Log in and list or call the toy ERP's MCP tools."""
import argparse
import asyncio
import getpass
import json
import os

import httpx2
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client

try:
    from scripts.erp_admin import login, post
except ModuleNotFoundError:  # Support `python scripts/mcp_client.py`.
    from erp_admin import login, post


def object_json(value: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("arguments must be a JSON object")
    return parsed


async def run(url: str, token: str, tool: str | None, arguments: dict) -> None:
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http:
        async with Client(streamable_http_client(f"{url.rstrip('/')}/mcp", http_client=http),
                          mode="legacy") as client:
            if tool:
                print(await client.call_tool(tool, arguments))
            else:
                for item in (await client.list_tools()).tools:
                    print(item.name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", nargs="?", help="tool to call; omit to list permitted tools")
    parser.add_argument("--arguments", type=object_json, default={}, metavar="JSON")
    parser.add_argument("--url", default=os.environ.get("ERP_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--username", default=os.environ.get("ERP_USERNAME"))
    args = parser.parse_args()

    supplied_token = os.environ.get("ERP_TOKEN")
    token = supplied_token
    if not token:
        username = args.username or input("Username: ").strip()
        token = login(args.url, username, getpass.getpass("Password: "))
    try:
        asyncio.run(run(args.url, token, args.tool, args.arguments))
    finally:
        if not supplied_token:
            post(args.url, "/auth/logout", {}, token)


if __name__ == "__main__":
    main()
