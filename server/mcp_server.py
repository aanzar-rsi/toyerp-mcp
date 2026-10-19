"""MCP server exposing the toy ERP's BAPI-style tools over streamable-HTTP."""
import os
import time
from urllib.parse import urlparse

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse

from server.bapi import vendor, material, purchasing, customer, sales, finance, hr
from server.security import ERPTokenVerifier, admin_action, allowed_tools, authenticate, audit, session
from server.db import get_conn

PUBLIC_URL = os.environ.get("ERP_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")
parsed_url = urlparse(PUBLIC_URL)
if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc or parsed_url.path or parsed_url.username or parsed_url.password:
    raise ValueError("ERP_PUBLIC_URL must be an absolute HTTP(S) URL")
if parsed_url.scheme == "http" and parsed_url.hostname not in ("localhost", "127.0.0.1", "::1"):
    raise ValueError("Remote ERP_PUBLIC_URL must use HTTPS")
RESOURCE_URL = PUBLIC_URL + "/mcp"
mcp = MCPServer(
    "toy-erp",
    auth=AuthSettings(issuer_url=PUBLIC_URL, resource_server_url=RESOURCE_URL,
                      validate_token_resource=True, required_scopes=["erp"]),
    token_verifier=ERPTokenVerifier(RESOURCE_URL),
)

TOOL_MODULES = [vendor, material, purchasing, customer, sales, finance, hr]
TOOL_NAMES = {attr for module in TOOL_MODULES for attr in dir(module) if attr.startswith("BAPI_")}

for module in TOOL_MODULES:
    for attr in dir(module):
        if attr.startswith("BAPI_"):
            mcp.add_tool(getattr(module, attr), name=attr)


def _identity():
    access = get_access_token()
    return session(access.token) if access else None


async def _authorize_tools(ctx, call_next):
    if ctx.method not in ("tools/list", "tools/call"):
        # The MCP endpoint requires a bearer token at the HTTP layer.
        return await call_next(ctx)
    user = _identity()
    if not user:
        if ctx.method == "tools/list":
            return {"tools": []}
        return {"content": [{"type": "text", "text": "Not authorized"}], "isError": True}
    permitted = allowed_tools(user["user_id"], TOOL_NAMES)
    if ctx.method == "tools/list":
        result = await call_next(ctx)
        result["tools"] = [tool for tool in result["tools"] if tool["name"] in permitted]
        return result
    name = ctx.params.get("name") if hasattr(ctx.params, "get") else None
    if name not in permitted:
        with get_conn() as conn:
            audit(conn, user["username"], "tool_denied", str(name)[:128])
        return {"content": [{"type": "text", "text": "Tool not available"}], "isError": True}
    try:
        return await call_next(ctx)
    finally:
        with get_conn() as conn:
            audit(conn, user["username"], "tool_call", str(name))


mcp.middleware.append(_authorize_tools)


async def _body(request: Request):
    try:
        length = int(request.headers.get("content-length", "0"))
    except ValueError:
        return None
    if length > 8192:
        return None
    body = await request.body()
    if len(body) > 8192:
        return None
    try:
        data = await request.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


@mcp.custom_route("/auth/login", methods=["POST"])
async def login(request: Request):
    payload = await _body(request)
    if payload is None:
        return JSONResponse({"error": "Invalid request"}, status_code=400)
    credentials = authenticate(payload.get("username"), payload.get("password"))
    if not credentials:
        return JSONResponse({"error": "Invalid credentials"}, status_code=401)
    token, expires = credentials
    return JSONResponse({"access_token": token, "token_type": "Bearer", "expires_at": expires,
                         "expires_in": expires - int(time.time())},
                        headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@mcp.custom_route("/auth/logout", methods=["POST"])
async def logout(request: Request):
    user = _identity()
    if not user:
        return JSONResponse({"error": "Authentication required"}, status_code=401)
    with get_conn() as conn:
        conn.execute("UPDATE sessions SET revoked = 1 WHERE token_hash = ?", (user["token_hash"],))
        audit(conn, user["username"], "logout")
    return JSONResponse({"ok": True})


@mcp.custom_route("/admin/{operation}", methods=["POST"])
async def admin(request: Request):
    user = _identity()
    if not user:
        return JSONResponse({"error": "Authentication required"}, status_code=401)
    if not user["is_admin"]:
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    payload = await _body(request)
    if payload is None:
        return JSONResponse({"error": "Invalid request"}, status_code=400)
    try:
        result = admin_action(user, request.path_params["operation"], payload, TOOL_NAMES)
    except PermissionError:
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(result)

if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host=os.environ.get("MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("MCP_PORT", "8000")),
    )
