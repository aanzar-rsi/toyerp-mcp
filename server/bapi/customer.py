"""Customer master data BAPIs."""
from server.db import get_conn, bapi_result, bapi_error, rows_to_dicts


def BAPI_CUSTOMER_CREATE(name: str, address: str = "", credit_limit: float = 10000.0) -> dict:
    if not name:
        return bapi_error("Customer name is required")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO customers (name, address, credit_limit) VALUES (?, ?, ?)",
            (name, address, credit_limit),
        )
        customer_id = cur.lastrowid
    return bapi_result(
        data={"customer_id": customer_id},
        messages=[{"type": "S", "message": f"Customer {customer_id} created"}],
    )


def BAPI_CUSTOMER_GETLIST(status: str = None) -> dict:
    with get_conn() as conn:
        if status:
            rows = conn.execute("SELECT * FROM customers WHERE status = ?", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM customers").fetchall()
    return bapi_result(data=rows_to_dicts(rows))
