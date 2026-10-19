"""Material master + stock BAPIs."""
from server.db import get_conn, bapi_result, bapi_error, rows_to_dicts

DEFAULT_PLANT = "1000"


def BAPI_MATERIAL_CREATE(description: str, uom: str = "EA", unit_price: float = 0.0, category: str = "") -> dict:
    if not description:
        return bapi_error("Material description is required")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO materials (description, uom, unit_price, category) VALUES (?, ?, ?, ?)",
            (description, uom, unit_price, category),
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


def BAPI_MATERIAL_GETLIST(category: str = None) -> dict:
    with get_conn() as conn:
        if category:
            rows = conn.execute("SELECT * FROM materials WHERE category = ?", (category,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM materials").fetchall()
    return bapi_result(data=rows_to_dicts(rows))


def BAPI_MATERIAL_STOCK_GETLIST(material_id: int = None, plant: str = None) -> dict:
    """Check stock."""
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
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return bapi_result(data=rows_to_dicts(rows))
