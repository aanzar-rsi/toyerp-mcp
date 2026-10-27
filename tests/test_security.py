"""Security integration: real HTTP auth and MCP tool discovery/invocation."""
import asyncio
import sqlite3
import time

import httpx2
import pytest
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client

from server.db import get_conn, init_schema, migrate_schema
from server.mcp_server import RESOURCE_URL, TOOL_NAMES, mcp
from server.security import bootstrap_admin, check_password, default_roles, provision_security_defaults, session


@pytest.fixture
def security_db(tmp_path, monkeypatch):
    import server.db as db
    path = str(tmp_path / "security.db")
    init_schema(path)
    migrate_schema(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    bootstrap_admin("root", "correct horse battery staple")
    return path


async def request(http, route, data, token=None):
    return await http.post(route, json=data, headers={"Authorization": f"Bearer {token}"} if token else {})


def test_admin_login_roles_and_revocation(security_db):
    async def run():
        app = mcp.streamable_http_app(host="127.0.0.1")
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as http:
            assert (await request(http, "/auth/login", {"username": "root", "password": "bad"})).status_code == 401
            login = await request(http, "/auth/login", {"username": "root", "password": "correct horse battery staple"})
            assert login.status_code == 200
            assert login.headers["cache-control"] == "no-store"
            admin = login.json()["access_token"]
            assert session(admin)
            with get_conn() as conn:
                assert conn.execute("SELECT token_hash FROM sessions").fetchone()[0] != admin
                assert "correct horse battery staple" not in conn.execute("SELECT password_hash FROM users WHERE username = 'root'").fetchone()[0]
            assert (await request(http, "/admin/create_user", {"username": "buyer", "password": "another secure password"})).status_code == 401
            assert (await request(http, "/admin/create_user", {"username": "buyer", "password": "another secure password"}, admin)).status_code == 200
            assert (await request(http, "/admin/create_role", {"role": "purchasing"}, admin)).status_code == 200
            assert (await request(http, "/admin/grant_role_tool", {"role": "purchasing", "tool": "UNREGISTERED"}, admin)).status_code == 400
            assert (await request(http, "/admin/grant_role_tool", {"role": "purchasing", "tool": "BAPI_VENDOR_GETLIST"}, admin)).status_code == 200
            assert (await request(http, "/admin/create_role", {"role": "purchasing"}, admin)).status_code == 400
            assert (await request(http, "/admin/assign_role", {"username": "buyer", "role": "purchasing"}, admin)).status_code == 200
            buyer = (await request(http, "/auth/login", {"username": "buyer", "password": "another secure password"})).json()["access_token"]
            assert (await request(http, "/admin/create_user", {"username": "new", "password": "another secure password"}, buyer)).status_code == 403
            assert (await request(http, "/admin/deny_user_tool", {"username": "buyer", "tool": "BAPI_VENDOR_GETLIST"}, admin)).status_code == 200
            assert (await request(http, "/admin/grant_user_tool", {"username": "buyer", "tool": "BAPI_PO_GETLIST"}, admin)).status_code == 200
            from server.security import allowed_tools
            with get_conn() as conn:
                buyer_id = conn.execute("SELECT user_id FROM users WHERE username = 'buyer'").fetchone()[0]
            assert allowed_tools(buyer_id, {"BAPI_VENDOR_GETLIST", "BAPI_PO_GETLIST"}) == {"BAPI_PO_GETLIST"}
            assert (await request(http, "/admin/revoke_sessions", {"username": "buyer"}, admin)).status_code == 200
            assert session(buyer) is None
            assert (await request(http, "/admin/reset_password", {"username": "buyer", "password": "a different secure password"}, admin)).status_code == 200
            assert (await request(http, "/auth/login", {"username": "buyer", "password": "another secure password"})).status_code == 401
            assert (await request(http, "/auth/logout", {}, admin)).status_code == 200
            assert session(admin) is None
            assert (await request(http, "/admin/create_role", {"role": "after-logout"}, admin)).status_code == 401
            with get_conn() as conn:
                assert conn.execute("SELECT COUNT(*) FROM security_events WHERE action = 'tool_denied'").fetchone()[0] == 0
    asyncio.run(run())


def test_tool_discovery_and_call_denial(security_db):
    async def run():
        app = mcp.streamable_http_app(host="127.0.0.1")
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as http:
                assert (await http.post("/mcp", json={}, headers={"Accept": "application/json, text/event-stream"})).status_code == 401
                admin = (await request(http, "/auth/login", {"username": "root", "password": "correct horse battery staple"})).json()["access_token"]
                await request(http, "/admin/create_user", {"username": "buyer", "password": "another secure password"}, admin)
                await request(http, "/admin/create_role", {"role": "purchasing"}, admin)
                await request(http, "/admin/grant_role_tool", {"role": "purchasing", "tool": "BAPI_VENDOR_GETLIST"}, admin)
                await request(http, "/admin/assign_role", {"username": "buyer", "role": "purchasing"}, admin)
                buyer = (await request(http, "/auth/login", {"username": "buyer", "password": "another secure password"})).json()["access_token"]

            # MCP SDK transport uses an HTTP client with bearer headers on each request.
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:8000",
                                          headers={"Authorization": f"Bearer {buyer}"}) as authorized:
                async with Client(streamable_http_client(RESOURCE_URL, http_client=authorized), mode="legacy") as client:
                    names = {tool.name for tool in (await client.list_tools()).tools}
                    assert names == {"BAPI_VENDOR_GETLIST"}
                    assert (await client.call_tool("BAPI_VENDOR_GETLIST", {})).is_error is not True
                    assert (await client.call_tool("BAPI_GL_ACCOUNT_GETLIST", {})).is_error is True
                    with get_conn() as conn:
                        assert conn.execute("SELECT COUNT(*) FROM security_events WHERE action = 'tool_denied'").fetchone()[0] >= 1
                    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as http:
                        await request(http, "/admin/revoke_role_tool", {"role": "purchasing", "tool": "BAPI_VENDOR_GETLIST"}, admin)
                    assert (await client.list_tools()).tools == []
                    assert (await client.call_tool("BAPI_VENDOR_GETLIST", {})).is_error is True
                    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as http:
                        await request(http, "/admin/grant_user_tool", {"username": "buyer", "tool": "BAPI_VENDOR_GETLIST"}, admin)
                    assert {tool.name for tool in (await client.list_tools()).tools} == {"BAPI_VENDOR_GETLIST"}
                    with get_conn() as conn:
                        conn.execute("UPDATE sessions SET expires_at = ? WHERE user_id = "
                                     "(SELECT user_id FROM users WHERE username = 'buyer')", (int(time.time()) - 1,))
                    assert session(buyer) is None
                    # The authenticated SDK endpoint re-verifies on every HTTP request.
                    with pytest.raises(Exception):
                        await client.list_tools()
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:8000",
                                          headers={"Authorization": f"Bearer {admin}"}) as authorized:
                async with Client(streamable_http_client(RESOURCE_URL, http_client=authorized), mode="legacy") as client:
                    assert {tool.name for tool in (await client.list_tools()).tools} == TOOL_NAMES
    asyncio.run(run())


def test_bootstrap_one_time_and_migrate_v1(tmp_path):
    from pathlib import Path
    path = str(tmp_path / "upgrade.db")
    schema = (Path(__file__).resolve().parents[1] / "data" / "schema.sql").read_text()
    conn = sqlite3.connect(path)
    conn.executescript(schema.split("CREATE TABLE users (")[0] + "\nINSERT INTO gl_accounts (name, account_type) VALUES ('Cash', 'ASSET');")
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()
    migrate_schema(path)
    migrate_schema(path)
    with get_conn(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    # Bootstrapping cannot run twice even if the second username is different.
    import server.db as db
    old = db.DB_PATH
    try:
        db.DB_PATH = path
        bootstrap_admin("first", "a long enough password")
        with pytest.raises(ValueError):
            bootstrap_admin("second", "another long password")
    finally:
        db.DB_PATH = old


def test_account_lockout_and_disabled_user(security_db):
    async def run():
        app = mcp.streamable_http_app(host="127.0.0.1")
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as http:
            admin = (await request(http, "/auth/login", {"username": "root", "password": "correct horse battery staple"})).json()["access_token"]
            await request(http, "/admin/create_user", {"username": "locked", "password": "another secure password"}, admin)
            for _ in range(5):
                assert (await request(http, "/auth/login", {"username": "locked", "password": "wrong"})).status_code == 401
            assert (await request(http, "/auth/login", {"username": "locked", "password": "another secure password"})).status_code == 401
            await request(http, "/admin/reset_password", {"username": "locked", "password": "new secure password"}, admin)
            token = (await request(http, "/auth/login", {"username": "locked", "password": "new secure password"})).json()["access_token"]
            await request(http, "/admin/set_user_active", {"username": "locked", "active": False}, admin)
            assert session(token) is None
            assert (await request(http, "/auth/login", {"username": "locked", "password": "new secure password"})).status_code == 401
            assert (await request(http, "/admin/set_user_active", {"username": "root", "active": False}, admin)).status_code == 400
    asyncio.run(run())


def test_legacy_v1_security_migration(tmp_path):
    from pathlib import Path
    path = str(tmp_path / "v1.db")
    sql = (Path(__file__).resolve().parents[1] / "data" / "migration_001.sql").read_text()
    with sqlite3.connect(path) as conn:
        conn.executescript(
            "CREATE TABLE gl_accounts (account_id INTEGER PRIMARY KEY, name TEXT, account_type TEXT); "
            "INSERT INTO gl_accounts VALUES (1, 'Cash', 'ASSET'); "
            "CREATE TABLE gl_postings (posting_id INTEGER PRIMARY KEY, account_id INTEGER, amount REAL, "
            "posting_date TEXT, reference TEXT); "
            "INSERT INTO gl_postings VALUES (1, 1, 17, '2024-01-01', 'legacy'); "
            + sql + "\nPRAGMA user_version = 1;"
        )
    migrate_schema(path)
    migrate_schema(path)
    with get_conn(path) as conn:
        assert conn.execute("SELECT amount FROM gl_postings").fetchone()[0] == 17
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_default_admin_and_roles_are_idempotent(tmp_path, monkeypatch):
    import server.db as db
    path = str(tmp_path / "defaults.db")
    init_schema(path)
    monkeypatch.setattr(db, "DB_PATH", path)

    generated = provision_security_defaults(TOOL_NAMES, password="initial secure password")
    assert generated is None
    assert provision_security_defaults(TOOL_NAMES, password="must not replace password") is None

    expected = default_roles(TOOL_NAMES)
    assert set(expected) == {"HR_ALL", "FINANCE_ALL", "PROCUREMENT_ALL", "SALES_ALL",
                             "INVENTORY_ALL", "MASTER_DATA_ALL", "ERP_READ_ONLY"}
    assert "BAPI_HR_PAYROLL_RUN" in expected["HR_ALL"]
    assert "BAPI_GL_JOURNAL_POST" in expected["FINANCE_ALL"]
    assert "BAPI_PO_CREATE" in expected["PROCUREMENT_ALL"]
    assert "BAPI_SALESORDER_CREATE" in expected["SALES_ALL"]
    assert "BAPI_GOODSMVT_CREATE" in expected["INVENTORY_ALL"]
    assert "BAPI_CUSTOMER_CREATE" in expected["MASTER_DATA_ALL"]
    assert "BAPI_VENDOR_GETLIST" in expected["ERP_READ_ONLY"]
    assert "BAPI_VENDOR_CREATE" not in expected["ERP_READ_ONLY"]
    with get_conn() as conn:
        admin = conn.execute("SELECT * FROM users WHERE username = 'super_admin'").fetchone()
        assert admin["is_admin"] == 1
        assert check_password("initial secure password", admin["password_hash"])
        assert not check_password("must not replace password", admin["password_hash"])
        assert {row[0] for row in conn.execute("SELECT name FROM roles")} == set(expected)
        for role, tools in expected.items():
            actual = {row[0] for row in conn.execute(
                "SELECT tool_name FROM role_tools JOIN roles USING (role_id) WHERE name = ?", (role,)
            )}
            assert actual == tools


def test_default_admin_generates_password(tmp_path, monkeypatch):
    import server.db as db
    path = str(tmp_path / "generated.db")
    init_schema(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    password = provision_security_defaults(TOOL_NAMES)
    assert password and len(password) >= 12
    with get_conn() as conn:
        stored = conn.execute("SELECT password_hash FROM users WHERE username = 'super_admin'").fetchone()[0]
    assert check_password(password, stored)


def test_file_default_users_are_created_and_assigned_once(tmp_path, monkeypatch):
    import server.db as db
    from server.security import provision_default_users
    path = str(tmp_path / "file-defaults.db")
    users = tmp_path / "users.txt"
    users.write_text(
        "ahad-anzar|a secure admin password|ADMIN\n"
        "hr-user|a secure human resources password|HR_ALL\n"
        "finance-user|a secure finance password|FINANCE_ALL\n",
        encoding="utf-8",
    )
    init_schema(path)
    monkeypatch.setattr(db, "DB_PATH", path)

    assert provision_default_users(TOOL_NAMES, users) == ["ahad-anzar", "hr-user", "finance-user"]
    assert provision_default_users(TOOL_NAMES, users) == []
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT u.username, u.is_admin, r.name FROM users u "
            "LEFT JOIN user_roles ur USING (user_id) LEFT JOIN roles r USING (role_id) "
            "WHERE u.username IN ('ahad-anzar','hr-user','finance-user') ORDER BY u.username"
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("ahad-anzar", 1, None),
            ("finance-user", 0, "FINANCE_ALL"),
            ("hr-user", 0, "HR_ALL"),
        ]


def test_default_admin_does_not_promote_existing_user(tmp_path, monkeypatch):
    import server.db as db
    path = str(tmp_path / "collision.db")
    init_schema(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    with get_conn() as conn:
        conn.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                     ("super_admin", "not-used"))
    with pytest.raises(ValueError, match="non-admin"):
        provision_security_defaults(TOOL_NAMES, password="initial secure password")
