"""Material master + stock BAPIs."""
from datetime import date
from server.db import get_conn, bapi_result, bapi_error, page_args, paged_result

DEFAULT_PLANT = "1000"


def BAPI_MATERIAL_CREATE(description: str, uom: str = "EA", unit_price: float = 0.0, category: str = "") -> dict:
    if not description:
        return bapi_error("Material description is required")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO materials (description, uom, unit_price, category, created_date) VALUES (?, ?, ?, ?, ?)",
            (description, uom, unit_price, category, date.today().isoformat()),
        )
        material_id = cur.lastrowid
        conn.execute(
            "INSERT INTO stock (material_id, plant, qty_on_hand) VALUES (?, ?, 0)",
            (material_id, DEFAULT_PLANT),
        )
    return bapi_result(
        data={"material_id": material_id},
        messages=[{"type": "S", "message": f"Material {material_id} created"}],
    )


def BAPI_MATERIAL_GETLIST(category: str = None, limit: int = 100, after_id: int = 0) -> dict:
    if error := page_args(limit, after_id):
        return bapi_error(error)
    with get_conn() as conn:
        if category:
            rows = conn.execute(
                "SELECT * FROM materials WHERE category = ? AND material_id > ? ORDER BY material_id LIMIT ?",
                (category, after_id, limit + 1),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM materials WHERE material_id > ? ORDER BY material_id LIMIT ?",
                (after_id, limit + 1),
            ).fetchall()
    return paged_result(rows, limit, "material_id")


def BAPI_MATERIAL_STOCK_GETLIST(material_id: int = None, plant: str = None,
                                limit: int = 100, after_id: int = 0) -> dict:
    """Check stock."""
    if error := page_args(limit, after_id):
        return bapi_error(error)
    query = """
        SELECT s.material_id, m.description, s.plant, s.qty_on_hand
        FROM stock s JOIN materials m ON m.material_id = s.material_id
        WHERE 1=1
    """
    params = []
    if material_id is not None:
        query += " AND s.material_id = ?"
        params.append(material_id)
    if plant:
        query += " AND s.plant = ?"
        params.append(plant)
    query += " AND s.material_id > ? ORDER BY s.material_id LIMIT ?"
    params.extend((after_id, limit + 1))
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return paged_result(rows, limit, "material_id")
