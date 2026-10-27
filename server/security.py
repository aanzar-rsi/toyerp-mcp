"""ERP identities, role permissions and opaque bearer sessions."""
import hashlib
import hmac
import re
import secrets
import time
from pathlib import Path

from mcp.server.auth.provider import AccessToken

from server.db import get_conn

TOKEN_TTL = 3600
PASSWORD_ITERATIONS = 600_000
USERNAME = re.compile(r"[a-zA-Z][a-zA-Z0-9_.-]{2,63}\Z")
ROLE_NAME = re.compile(r"[a-zA-Z][a-zA-Z0-9_.-]{1,63}\Z")
DEFAULT_USERS_PATH = Path(__file__).resolve().parents[1] / "scripts" / "default_users.txt"


def default_roles(registered: set[str]) -> dict[str, set[str]]:
    """Return the standard least-privilege role templates."""
    finance = {tool for tool in registered if tool.startswith("BAPI_GL_") or
               tool.startswith(("BAPI_AP_", "BAPI_AR_", "BAPI_INCOMINGINVOICE_"))}
    return {
        "HR_ALL": {tool for tool in registered if tool.startswith("BAPI_HR_")},
        "FINANCE_ALL": finance,
        "PROCUREMENT_ALL": {tool for tool in registered if tool.startswith(
            ("BAPI_VENDOR_", "BAPI_PO_", "BAPI_GOODSMVT_", "BAPI_MATERIAL_"))},
        "SALES_ALL": {tool for tool in registered if tool.startswith(
            ("BAPI_CUSTOMER_", "BAPI_SALESORDER_", "BAPI_AR_"))},
        "INVENTORY_ALL": {tool for tool in registered if tool.startswith(
            ("BAPI_MATERIAL_", "BAPI_GOODSMVT_"))},
        "MASTER_DATA_ALL": {tool for tool in registered if tool.startswith(
            ("BAPI_VENDOR_", "BAPI_CUSTOMER_", "BAPI_MATERIAL_"))},
        "ERP_READ_ONLY": {tool for tool in registered if
                          "_GETLIST" in tool or "_GETDETAIL" in tool or tool.endswith("_SUMMARY")},
    }


def load_default_users(path=DEFAULT_USERS_PATH) -> list[tuple[str, str, str]]:
    """Read username|password|role demo accounts from the configured text file."""
    users = []
    for line_no, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) != 3:
            raise ValueError(f"Invalid default user on line {line_no}: expected username|password|role")
        username, password, role = (part.strip() for part in parts)
        if not USERNAME.fullmatch(username):
            raise ValueError(f"Invalid default username on line {line_no}")
        password_hash(password)  # Validate before opening the provisioning transaction.
        if role != "ADMIN" and not ROLE_NAME.fullmatch(role):
            raise ValueError(f"Invalid default role on line {line_no}")
        users.append((username, password, role))
    if not users or not any(role == "ADMIN" for _, _, role in users):
        raise ValueError("Default users file must contain at least one ADMIN")
    if len({username for username, _, _ in users}) != len(users):
        raise ValueError("Default users file contains duplicate usernames")
    return users


def provision_default_users(registered: set[str], path=DEFAULT_USERS_PATH) -> list[str]:
    """Create missing file-defined users and standard roles without resetting accounts."""
    roles = default_roles(registered)
    users = load_default_users(path)
    unknown = {role for _, _, role in users if role != "ADMIN"} - roles.keys()
    if unknown:
        raise ValueError(f"Unknown default role(s): {', '.join(sorted(unknown))}")
    created = []
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for name, tools in roles.items():
            conn.execute("INSERT OR IGNORE INTO roles (name) VALUES (?)", (name,))
            role_id = conn.execute("SELECT role_id FROM roles WHERE name = ?", (name,)).fetchone()[0]
            conn.executemany("INSERT OR IGNORE INTO role_tools (role_id, tool_name) VALUES (?, ?)",
                             ((role_id, tool) for tool in tools))
        for username, password, role in users:
            existing = conn.execute("SELECT user_id, is_admin FROM users WHERE username = ?", (username,)).fetchone()
            if existing:
                if role == "ADMIN" and not existing["is_admin"]:
                    raise ValueError(f"Default administrator {username!r} belongs to a non-admin user")
                user_id = existing["user_id"]
            else:
                user_id = conn.execute(
                    "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
                    (username, password_hash(password), int(role == "ADMIN")),
                ).lastrowid
                audit(conn, username, "default_user_created", role)
                created.append(username)
            if role != "ADMIN":
                role_id = conn.execute("SELECT role_id FROM roles WHERE name = ?", (role,)).fetchone()[0]
                conn.execute("INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)",
                             (user_id, role_id))
    return created


def provision_security_defaults(registered: set[str], username: str = "super_admin",
                                password: str | None = None) -> str | None:
    """Ensure the default admin and roles exist; return a generated password once."""
    if not USERNAME.fullmatch(username):
        raise ValueError("ERP_SUPER_ADMIN_USERNAME is invalid")
    roles = default_roles(registered)
    if any(not tools for tools in roles.values()):
        raise ValueError("A default role has no registered tools")

    generated = None
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT is_admin FROM users WHERE username = ?", (username,)).fetchone()
        if existing and not existing["is_admin"]:
            raise ValueError(f"Default administrator username {username!r} belongs to a non-admin user")
        if not existing:
            if password is None:
                generated = secrets.token_urlsafe(24)
                password = generated
            conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
                         (username, password_hash(password)))
            audit(conn, username, "default_super_admin_created")

        for name, tools in roles.items():
            conn.execute("INSERT OR IGNORE INTO roles (name) VALUES (?)", (name,))
            role_id = conn.execute("SELECT role_id FROM roles WHERE name = ?", (name,)).fetchone()[0]
            conn.executemany("INSERT OR IGNORE INTO role_tools (role_id, tool_name) VALUES (?, ?)",
                             ((role_id, tool) for tool in tools))
    return generated


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
