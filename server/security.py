"""ERP identities, role permissions and opaque bearer sessions."""
import hashlib
import hmac
import re
import secrets
import time

from mcp.server.auth.provider import AccessToken

from server.db import get_conn

TOKEN_TTL = 3600
PASSWORD_ITERATIONS = 600_000
USERNAME = re.compile(r"[a-zA-Z][a-zA-Z0-9_.-]{2,63}\Z")
ROLE_NAME = re.compile(r"[a-zA-Z][a-zA-Z0-9_.-]{1,63}\Z")


def password_hash(password: str) -> str:
    if not isinstance(password, str) or len(password) < 12 or len(password) > 1024:
        raise ValueError("Password must contain between 12 and 1024 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str | None) -> bool:
    if stored:
        try:
            algorithm, iterations, salt, digest = stored.split("$")
            if algorithm != "pbkdf2_sha256":
                return False
            if int(iterations) != PASSWORD_ITERATIONS:
                return False
            if len(salt) != 32 or len(digest) != 64:
                return False
            candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
            return hmac.compare_digest(candidate, bytes.fromhex(digest))
        except (ValueError, TypeError, OverflowError):
            return False
    hashlib.pbkdf2_hmac("sha256", password.encode(), b"\0" * 16, PASSWORD_ITERATIONS)
    return False


def audit(conn, actor: str, action: str, detail: str = "") -> None:
    conn.execute("INSERT INTO security_events (actor, action, detail) VALUES (?, ?, ?)",
                 (actor, action, detail))


def bootstrap_admin(username: str, password: str) -> None:
    if not USERNAME.fullmatch(username):
        raise ValueError("Username must be 3-64 letters, digits, dots, dashes or underscores")
    hashed = password_hash(password)
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            raise ValueError("Bootstrap is only available before the first user is created")
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
                     (username, hashed))
        audit(conn, username, "bootstrap_admin")


def authenticate(username: str, password: str) -> tuple[str, int] | None:
    if not isinstance(username, str) or len(username) > 64 or not isinstance(password, str) or len(password) > 1024:
        return None
    if not USERNAME.fullmatch(username):
        username = "unknown"
    now = int(time.time())
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not row or not row["active"] or row["locked_until"] > now:
            check_password(password, None)
            audit(conn, username, "login_failed")
            return None
        if not check_password(password, row["password_hash"]):
            failures = row["failed_attempts"] + 1
            locked_until = now + 900 if failures >= 5 else 0
            conn.execute("UPDATE users SET failed_attempts = ?, locked_until = ? WHERE user_id = ?",
                         (failures if failures < 5 else 0, locked_until, row["user_id"]))
            audit(conn, row["username"], "login_failed")
            return None
        token = secrets.token_urlsafe(32)
        expires = now + TOKEN_TTL
        conn.execute("UPDATE users SET failed_attempts = 0, locked_until = 0 WHERE user_id = ?", (row["user_id"],))
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        conn.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                     (hashlib.sha256(token.encode()).hexdigest(), row["user_id"], expires))
        audit(conn, row["username"], "login")
    return token, expires


def session(token: str) -> dict | None:
    if not isinstance(token, str) or not token or len(token) > 256:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT u.user_id, u.username, u.is_admin, s.expires_at, s.token_hash "
            "FROM sessions s JOIN users u ON u.user_id = s.user_id "
            "WHERE s.token_hash = ? AND s.revoked = 0 AND s.expires_at > ? AND u.active = 1",
            (hashlib.sha256(token.encode()).hexdigest(), int(time.time())),
        ).fetchone()
    return dict(row) if row else None


class ERPTokenVerifier:
    def __init__(self, resource: str):
        self.resource = resource

    async def verify_token(self, token: str) -> AccessToken | None:
        user = session(token)
        if not user:
            return None
        return AccessToken(token=token, client_id=str(user["user_id"]), subject=str(user["user_id"]),
                           scopes=["erp"], expires_at=user["expires_at"], resource=self.resource)


def allowed_tools(user_id: int, registered: set[str]) -> set[str]:
    with get_conn() as conn:
        user = conn.execute("SELECT active, is_admin FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not user or not user["active"]:
            return set()
        if user["is_admin"]:
            return registered.copy()
        role_grants = {row[0] for row in conn.execute(
            "SELECT rt.tool_name FROM role_tools rt JOIN user_roles ur USING (role_id) WHERE ur.user_id = ?",
            (user_id,),
        )}
        overrides = {row[0]: row[1] for row in conn.execute(
            "SELECT tool_name, allowed FROM user_tools WHERE user_id = ?", (user_id,)
        )}
    return {tool for tool in registered if overrides.get(tool, tool in role_grants)}


def admin_action(actor: dict, operation: str, payload: dict, registered: set[str]) -> dict:
    """Handle a single admin change; all references validated before committing."""
    username = payload.get("username")
    role_name = payload.get("role")
    tool = payload.get("tool")
    if operation in {"create_user", "set_user_active", "reset_password", "assign_role", "remove_role",
                     "grant_user_tool", "deny_user_tool", "clear_user_tool", "revoke_sessions"}:
        if not isinstance(username, str) or not USERNAME.fullmatch(username):
            raise ValueError("Invalid username")
    if operation in {"create_role", "assign_role", "remove_role", "grant_role_tool", "revoke_role_tool"}:
        if not isinstance(role_name, str) or not ROLE_NAME.fullmatch(role_name):
            raise ValueError("Invalid role name")
    if operation in {"grant_user_tool", "deny_user_tool", "clear_user_tool", "grant_role_tool", "revoke_role_tool"}:
        if tool not in registered:
            raise ValueError("Unknown tool")
    if operation in {"create_user", "reset_password"}:
        hashed = password_hash(payload.get("password"))
    if operation not in {"create_user", "create_role", "set_user_active", "reset_password",
                         "assign_role", "remove_role", "grant_user_tool", "deny_user_tool",
                         "clear_user_tool", "revoke_sessions", "grant_role_tool", "revoke_role_tool"}:
        raise ValueError("Unknown admin operation")

    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT 1 FROM users u JOIN sessions s ON s.user_id = u.user_id "
                               "WHERE s.token_hash = ? AND u.is_admin = 1 AND u.active = 1 "
                               "AND s.revoked = 0 AND s.expires_at > ?",
                               (actor["token_hash"], int(time.time()))).fetchone()
        if not current:
            raise PermissionError("Administrator required")
        if operation == "create_user":
            if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                raise ValueError("User already exists")
            conn.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, hashed))
        elif operation == "create_role":
            if conn.execute("SELECT 1 FROM roles WHERE name = ?", (role_name,)).fetchone():
                raise ValueError("Role already exists")
            conn.execute("INSERT INTO roles (name) VALUES (?)", (role_name,))
        else:
            user = None
            role = None
            if username:
                user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
                if not user:
                    raise ValueError("User not found")
            if role_name:
                role = conn.execute("SELECT * FROM roles WHERE name = ?", (role_name,)).fetchone()
                if not role:
                    raise ValueError("Role not found")
            if operation == "set_user_active":
                active = payload.get("active")
                if type(active) is not bool:
                    raise ValueError("active must be a boolean")
                if user["is_admin"] and not active:
                    raise ValueError("Bootstrap admin cannot be disabled")
                conn.execute("UPDATE users SET active = ? WHERE user_id = ?", (int(active), user["user_id"]))
                if not active:
                    conn.execute("UPDATE sessions SET revoked = 1 WHERE user_id = ?", (user["user_id"],))
            elif operation == "reset_password":
                conn.execute("UPDATE users SET password_hash = ?, failed_attempts = 0, locked_until = 0 WHERE user_id = ?",
                             (hashed, user["user_id"]))
                conn.execute("UPDATE sessions SET revoked = 1 WHERE user_id = ?", (user["user_id"],))
            elif operation == "revoke_sessions":
                conn.execute("UPDATE sessions SET revoked = 1 WHERE user_id = ?", (user["user_id"],))
            elif operation in {"assign_role", "remove_role"}:
                if operation == "assign_role":
                    conn.execute("INSERT OR IGNORE INTO user_roles VALUES (?, ?)", (user["user_id"], role["role_id"]))
                else:
                    conn.execute("DELETE FROM user_roles WHERE user_id = ? AND role_id = ?", (user["user_id"], role["role_id"]))
            elif operation in {"grant_role_tool", "revoke_role_tool"}:
                if operation == "grant_role_tool":
                    conn.execute("INSERT OR IGNORE INTO role_tools VALUES (?, ?)", (role["role_id"], tool))
                else:
                    conn.execute("DELETE FROM role_tools WHERE role_id = ? AND tool_name = ?", (role["role_id"], tool))
            elif operation in {"grant_user_tool", "deny_user_tool", "clear_user_tool"}:
                if operation == "clear_user_tool":
                    conn.execute("DELETE FROM user_tools WHERE user_id = ? AND tool_name = ?", (user["user_id"], tool))
                else:
                    conn.execute("INSERT INTO user_tools (user_id, tool_name, allowed) VALUES (?, ?, ?) "
                                 "ON CONFLICT(user_id, tool_name) DO UPDATE SET allowed = excluded.allowed",
                                 (user["user_id"], tool, int(operation == "grant_user_tool")))
            else:
                raise ValueError("Unknown admin operation")
        audit(conn, actor["username"], operation, str(username or role_name) + (f" {tool}" if tool else ""))
    return {"ok": True}
