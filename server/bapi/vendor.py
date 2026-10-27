"""Vendor master data BAPIs."""
from datetime import date
from server.db import get_conn, bapi_result, bapi_error, rows_to_dicts, page_args, paged_result


def BAPI_VENDOR_CREATE(name: str, contact_email: str = "", address: str = "", payment_terms: str = "NET30") -> dict:
    """Add vendor."""
    if not name:
        return bapi_error("Vendor name is required")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO vendors (name, contact_email, address, payment_terms, created_date) VALUES (?, ?, ?, ?, ?)",
            (name, contact_email, address, payment_terms, date.today().isoformat()),
        )
        vendor_id = cur.lastrowid
    return bapi_result(
        data={"vendor_id": vendor_id},
        messages=[{"type": "S", "message": f"Vendor {vendor_id} created"}],
    )


def BAPI_VENDOR_GETLIST(status: str = None, limit: int = 100, after_id: int = 0) -> dict:
    """Check vendors."""
    if error := page_args(limit, after_id):
        return bapi_error(error)
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM vendors WHERE status = ? AND vendor_id > ? ORDER BY vendor_id LIMIT ?",
                (status, after_id, limit + 1),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM vendors WHERE vendor_id > ? ORDER BY vendor_id LIMIT ?",
                (after_id, limit + 1),
            ).fetchall()
    return paged_result(rows, limit, "vendor_id")


def BAPI_VENDOR_GETDETAIL(vendor_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM vendors WHERE vendor_id = ?", (vendor_id,)).fetchone()
        catalog = conn.execute(
            "SELECT vm.*, m.description, m.uom FROM vendor_materials vm "
            "JOIN materials m USING (material_id) WHERE vm.vendor_id = ? ORDER BY vm.material_id",
            (vendor_id,),
        ).fetchall() if row else []
    if row is None:
        return bapi_error(f"Vendor {vendor_id} not found")
    return bapi_result(data={**dict(row), "catalog": rows_to_dicts(catalog)})
