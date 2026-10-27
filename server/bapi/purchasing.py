"""Purchase order + goods receipt BAPIs."""
from datetime import date
from server.db import get_conn, bapi_result, bapi_error, rows_to_dicts, page_args, paged_result

DEFAULT_PLANT = "1000"


def BAPI_PO_CREATE(vendor_id: int, items: list) -> dict:
    """Place order. items: [{"material_id": int, "qty": float, "unit_price": float?}]"""
    if not items:
        return bapi_error("At least one line item is required")
    with get_conn() as conn:
        vendor = conn.execute("SELECT 1 FROM vendors WHERE vendor_id = ?", (vendor_id,)).fetchone()
        if not vendor:
            return bapi_error(f"Vendor {vendor_id} not found")

        total = 0.0
        resolved_items = []
        for item in items:
            material = conn.execute(
                "SELECT m.unit_price, vm.unit_price AS vendor_price FROM materials m "
                "LEFT JOIN vendor_materials vm ON vm.material_id=m.material_id AND vm.vendor_id=? AND vm.is_active=1 "
                "WHERE m.material_id = ?", (vendor_id, item["material_id"])
            ).fetchone()
            if not material:
                return bapi_error(f"Material {item['material_id']} not found")
            unit_price = item.get("unit_price", material["vendor_price"] or material["unit_price"])
            qty = item["qty"]
            total += unit_price * qty
            resolved_items.append((item["material_id"], qty, unit_price))

        cur = conn.execute(
            "INSERT INTO purchase_orders (vendor_id, status, created_date, total_amount) VALUES (?, 'OPEN', ?, ?)",
            (vendor_id, date.today().isoformat(), total),
        )
        po_id = cur.lastrowid
        for item_no, (material_id, qty, unit_price) in enumerate(resolved_items, start=1):
            conn.execute(
                "INSERT INTO po_items (po_id, item_no, material_id, qty, unit_price) VALUES (?, ?, ?, ?, ?)",
                (po_id, item_no, material_id, qty, unit_price),
            )
    return bapi_result(
        data={"po_id": po_id, "total_amount": total},
        messages=[{"type": "S", "message": f"Purchase order {po_id} created"}],
    )


def BAPI_PO_GETDETAIL(po_id: int) -> dict:
    with get_conn() as conn:
        po = conn.execute("SELECT * FROM purchase_orders WHERE po_id = ?", (po_id,)).fetchone()
        if not po:
            return bapi_error(f"Purchase order {po_id} not found")
        items = conn.execute("SELECT * FROM po_items WHERE po_id = ?", (po_id,)).fetchall()
    return bapi_result(data={"po": dict(po), "items": rows_to_dicts(items)})


def BAPI_PO_GETLIST(vendor_id: int = None, status: str = None,
                    limit: int = 100, after_id: int = 0) -> dict:
    if error := page_args(limit, after_id):
        return bapi_error(error)
    query = "SELECT * FROM purchase_orders WHERE 1=1"
    params = []
    if vendor_id is not None:
        query += " AND vendor_id = ?"
        params.append(vendor_id)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " AND po_id > ? ORDER BY po_id LIMIT ?"
    params.extend((after_id, limit + 1))
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return paged_result(rows, limit, "po_id")


def BAPI_PO_CHANGE(po_id: int, status: str) -> dict:
    with get_conn() as conn:
        po = conn.execute("SELECT 1 FROM purchase_orders WHERE po_id = ?", (po_id,)).fetchone()
        if not po:
            return bapi_error(f"Purchase order {po_id} not found")
        conn.execute("UPDATE purchase_orders SET status = ? WHERE po_id = ?", (status, po_id))
    return bapi_result(messages=[{"type": "S", "message": f"Purchase order {po_id} updated to {status}"}])


def BAPI_GOODSMVT_CREATE(po_id: int, material_id: int, qty: float) -> dict:
    """Post a goods receipt against a PO; increases on-hand stock."""
    with get_conn() as conn:
        po_item = conn.execute(
            "SELECT 1 FROM po_items WHERE po_id = ? AND material_id = ?", (po_id, material_id)
        ).fetchone()
        if not po_item:
            return bapi_error(f"Material {material_id} is not on purchase order {po_id}")

        cur = conn.execute(
            "INSERT INTO goods_receipts (po_id, material_id, qty, posted_date, accepted_qty, warehouse, quality_status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'PASSED')",
            (po_id, material_id, qty, date.today().isoformat(), qty, DEFAULT_PLANT),
        )
        gr_id = cur.lastrowid
        conn.execute(
            "INSERT INTO stock (material_id, plant, qty_on_hand) VALUES (?, ?, ?) "
            "ON CONFLICT(material_id, plant) DO UPDATE SET qty_on_hand = qty_on_hand + excluded.qty_on_hand",
            (material_id, DEFAULT_PLANT, qty),
        )
        conn.execute(
            "UPDATE purchase_orders SET status = 'RECEIVED' WHERE po_id = ?", (po_id,)
        )
    return bapi_result(
        data={"gr_id": gr_id},
        messages=[{"type": "S", "message": f"Goods receipt {gr_id} posted, stock updated"}],
    )
