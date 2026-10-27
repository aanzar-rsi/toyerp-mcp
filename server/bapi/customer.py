"""Customer master data BAPIs."""
from datetime import date
from server.db import get_conn, bapi_result, bapi_error, page_args, paged_result


def BAPI_CUSTOMER_CREATE(name: str, address: str = "", credit_limit: float = 10000.0) -> dict:
    if not name:
        return bapi_error("Customer name is required")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO customers (name, address, credit_limit, created_date) VALUES (?, ?, ?, ?)",
            (name, address, credit_limit, date.today().isoformat()),
        )
        customer_id = cur.lastrowid
    return bapi_result(
        data={"customer_id": customer_id},
        messages=[{"type": "S", "message": f"Customer {customer_id} created"}],
    )


def BAPI_CUSTOMER_GETLIST(status: str = None, limit: int = 100, after_id: int = 0) -> dict:
    if error := page_args(limit, after_id):
        return bapi_error(error)
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM customers WHERE status = ? AND customer_id > ? ORDER BY customer_id LIMIT ?",
                (status, after_id, limit + 1),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM customers WHERE customer_id > ? ORDER BY customer_id LIMIT ?",
                (after_id, limit + 1),
            ).fetchall()
    return paged_result(rows, limit, "customer_id")
