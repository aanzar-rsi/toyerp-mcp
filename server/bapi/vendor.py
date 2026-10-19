"""Vendor master data BAPIs."""
from server.db import get_conn, bapi_result, bapi_error, rows_to_dicts


def BAPI_VENDOR_CREATE(name: str, contact_email: str = "", address: str = "", payment_terms: str = "NET30") -> dict:
    """Add vendor."""
    if not name:
        return bapi_error("Vendor name is required")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO vendors (name, contact_email, address, payment_terms) VALUES (?, ?, ?, ?)",
            (name, contact_email, address, payment_terms),
        )
        vendor_id = cur.lastrowid
    return bapi_result(
        data={"vendor_id": vendor_id},
        messages=[{"type": "S", "message": f"Vendor {vendor_id} created"}],
    )


def BAPI_VENDOR_GETLIST(status: str = None) -> dict:
    """Check vendors."""
    with get_conn() as conn:
        if status:
            rows = conn.execute("SELECT * FROM vendors WHERE status = ?", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM vendors").fetchall()
    return bapi_result(data=rows_to_dicts(rows))


def BAPI_VENDOR_GETDETAIL(vendor_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM vendors WHERE vendor_id = ?", (vendor_id,)).fetchone()
    if row is None:
        return bapi_error(f"Vendor {vendor_id} not found")
    return bapi_result(data=dict(row))
