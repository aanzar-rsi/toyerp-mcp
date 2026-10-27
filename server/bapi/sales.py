"""Sales order BAPIs."""
from datetime import date
from server.db import get_conn, bapi_result, bapi_error, page_args, paged_result

DEFAULT_PLANT = "1000"


def BAPI_SALESORDER_CREATE(customer_id: int, items: list) -> dict:
    """items: [{"material_id": int, "qty": float, "unit_price": float?}]. Decrements stock."""
    if not items:
        return bapi_error("At least one line item is required")
    with get_conn() as conn:
        customer = conn.execute("SELECT 1 FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()
        if not customer:
            return bapi_error(f"Customer {customer_id} not found")

        resolved_items = []
        total = 0.0
        for item in items:
            material = conn.execute(
                "SELECT unit_price FROM materials WHERE material_id = ?", (item["material_id"],)
            ).fetchone()
            if not material:
                return bapi_error(f"Material {item['material_id']} not found")
            stock_row = conn.execute(
                "SELECT qty_on_hand FROM stock WHERE material_id = ? AND plant = ?",
                (item["material_id"], DEFAULT_PLANT),
            ).fetchone()
            available = stock_row["qty_on_hand"] if stock_row else 0
            if available < item["qty"]:
                return bapi_error(
                    f"Insufficient stock for material {item['material_id']}: "
                    f"requested {item['qty']}, available {available}"
                )
            unit_price = item.get("unit_price", material["unit_price"])
            total += unit_price * item["qty"]
            resolved_items.append((item["material_id"], item["qty"], unit_price))

        cur = conn.execute(
            "INSERT INTO sales_orders (customer_id, status, created_date, total_amount) VALUES (?, 'OPEN', ?, ?)",
            (customer_id, date.today().isoformat(), total),
        )
        so_id = cur.lastrowid
        for item_no, (material_id, qty, unit_price) in enumerate(resolved_items, start=1):
            conn.execute(
                "INSERT INTO so_items (so_id, item_no, material_id, qty, unit_price) VALUES (?, ?, ?, ?, ?)",
                (so_id, item_no, material_id, qty, unit_price),
            )
            conn.execute(
                "UPDATE stock SET qty_on_hand = qty_on_hand - ? WHERE material_id = ? AND plant = ?",
                (qty, material_id, DEFAULT_PLANT),
            )
    return bapi_result(
        data={"so_id": so_id, "total_amount": total},
        messages=[{"type": "S", "message": f"Sales order {so_id} created"}],
    )


def BAPI_SALESORDER_GETLIST(customer_id: int = None, status: str = None,
                            limit: int = 100, after_id: int = 0) -> dict:
    if error := page_args(limit, after_id):
        return bapi_error(error)
    query = "SELECT * FROM sales_orders WHERE 1=1"
    params = []
    if customer_id is not None:
        query += " AND customer_id = ?"
        params.append(customer_id)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " AND so_id > ? ORDER BY so_id LIMIT ?"
    params.extend((after_id, limit + 1))
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return paged_result(rows, limit, "so_id")
