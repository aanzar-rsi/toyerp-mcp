"""Deterministic bulk generator for connected ERP demonstration data."""
import argparse
import os
import random
from datetime import date, timedelta

from faker import Faker

from server import db


PROFILES = {
    "test": {"vendors": 8, "customers": 10, "materials": 15, "employees": 6,
             "purchase_orders": 12, "sales_orders": 10, "leaves": 12},
    "medium": {"vendors": 2_000, "customers": 3_000, "materials": 3_000, "employees": 2_000,
               "purchase_orders": 8_000, "sales_orders": 12_000, "leaves": 5_000},
    "large": {"vendors": 10_000, "customers": 20_000, "materials": 20_000, "employees": 10_000,
              "purchase_orders": 50_000, "sales_orders": 100_000, "leaves": 30_000},
}
CATEGORIES = ("Electronics", "Hardware", "Office Supplies", "Raw Materials", "Safety", "Packaging")
COUNTRIES = ("US", "CA", "GB", "DE", "FR", "IN", "AU", "SG")
DEPARTMENTS = ("Operations", "Finance", "Sales", "Procurement", "IT", "HR", "Logistics", "Support")
START = date(2022, 1, 1)


def _day(rng, earliest=START, latest=None):
    latest = latest or date.today()
    return earliest + timedelta(days=rng.randint(0, max(0, (latest - earliest).days)))


def _chunks(rows, size=10_000):
    rows = iter(rows)
    while batch := list(__import__("itertools").islice(rows, size)):
        yield batch


def _insert_many(conn, sql, rows):
    for batch in _chunks(rows):
        conn.executemany(sql, batch)


def run_seed(profile=None, seed=None):
    """Populate an empty initialized database and return generated table counts."""
    profile = profile or os.environ.get("ERP_SEED_PROFILE", "medium")
    if profile not in PROFILES:
        raise ValueError(f"Unknown seed profile {profile!r}; choose {', '.join(PROFILES)}")
    seed = int(seed if seed is not None else os.environ.get("SEED_RANDOM", "42"))
    rng, fake = random.Random(seed), Faker()
    Faker.seed(seed)
    scale = PROFILES[profile]

    with db.get_conn() as conn:
        if conn.execute("SELECT EXISTS(SELECT 1 FROM vendors)").fetchone()[0]:
            raise RuntimeError("Refusing to seed a nonempty database")

        vendors = []
        for i in range(1, scale["vendors"] + 1):
            created = _day(rng, latest=date(2024, 12, 31))
            contract_start = created + timedelta(days=rng.randint(0, 180))
            contract_end = contract_start + timedelta(days=rng.randint(365, 1460))
            active = contract_end >= date.today()
            vendors.append((fake.company(), fake.company_email(), fake.address().replace("\n", ", "),
                            rng.choice(("NET15", "NET30", "NET45", "NET60")), "ACTIVE" if active else "INACTIVE",
                            created.isoformat(), fake.phone_number(), rng.choice(COUNTRIES), "USD",
                            round(rng.triangular(1, 5, 4.2), 1), rng.randint(2, 45),
                            contract_start.isoformat(), contract_end.isoformat(), active))
        _insert_many(conn, "INSERT INTO vendors (name,contact_email,address,payment_terms,status,created_date,phone,country,currency,rating,lead_time_days,contract_start_date,contract_end_date,active_contract) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", vendors)

        customers = []
        for _ in range(scale["customers"]):
            risk = rng.choices(("LOW", "MEDIUM", "HIGH"), (75, 20, 5))[0]
            customers.append((fake.company(), fake.address().replace("\n", ", "),
                              rng.choice((10_000, 25_000, 50_000, 100_000)),
                              rng.choices(("ACTIVE", "INACTIVE"), (96, 4))[0],
                              _day(rng, latest=date(2025, 6, 30)).isoformat(), fake.company_email(),
                              fake.phone_number(), rng.choice(COUNTRIES),
                              rng.choice(("RETAIL", "WHOLESALE", "ENTERPRISE", "GOVERNMENT")),
                              rng.choice(("Manufacturing", "Retail", "Healthcare", "Technology", "Construction")),
                              rng.choice(("NET15", "NET30", "NET45")),
                              {"LOW": "A", "MEDIUM": "B", "HIGH": "C"}[risk], risk))
        _insert_many(conn, "INSERT INTO customers (name,address,credit_limit,status,created_date,contact_email,phone,country,customer_type,industry,payment_terms,credit_rating,risk_level) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", customers)

        materials, stock = [], []
        for i in range(1, scale["materials"] + 1):
            cost = round(rng.uniform(2, 600), 2)
            materials.append((fake.catch_phrase(), rng.choice(("EA", "BOX", "KG", "L")),
                              round(cost * rng.uniform(1.15, 1.8), 2), rng.choice(CATEGORIES),
                              f"MAT-{i:07d}", cost, fake.company().split()[0], rng.choice(COUNTRIES),
                              rng.randint(20, 500), _day(rng, latest=date(2025, 12, 31)).isoformat(), "ACTIVE"))
            stock.append((i, "1000", 0))
        _insert_many(conn, "INSERT INTO materials (description,uom,unit_price,category,sku,cost_price,brand,country_of_origin,reorder_level,created_date,status) VALUES (?,?,?,?,?,?,?,?,?,?,?)", materials)
        conn.executemany("INSERT INTO stock (material_id,plant,qty_on_hand) VALUES (?,?,?)", stock)

        catalog = []
        for vendor_id in range(1, scale["vendors"] + 1):
            count = min(scale["materials"], rng.randint(8, 20))
            for material_id in rng.sample(range(1, scale["materials"] + 1), count):
                catalog.append((vendor_id, material_id, f"V{vendor_id:05d}-{material_id:07d}",
                                round(materials[material_id - 1][5] * rng.uniform(.9, 1.15), 2),
                                rng.choice((1, 5, 10, 25)), vendors[vendor_id - 1][10],
                                vendors[vendor_id - 1][11], vendors[vendor_id - 1][12], vendors[vendor_id - 1][13]))
        _insert_many(conn, "INSERT INTO vendor_materials VALUES (?,?,?,?,?,?,?,?,?)", catalog)
        by_vendor = {}
        for row in catalog:
            by_vendor.setdefault(row[0], []).append(row)

        pos, po_items, receipts, inventory = [], [], [], [0] * (scale["materials"] + 1)
        for po_id in range(1, scale["purchase_orders"] + 1):
            vendor_id = rng.randint(1, scale["vendors"])
            item = rng.choice(by_vendor[vendor_id])
            material_id, price = item[1], item[3]
            qty = rng.randint(25, 500)
            created = _day(rng, latest=date.today() - timedelta(days=3))
            posted = created + timedelta(days=max(1, item[5] + rng.randint(-2, 10)))
            posted = min(posted, date.today())
            rejected = qty if rng.random() < .01 else 0
            accepted = qty - rejected
            pos.append((vendor_id, "RECEIVED", created.isoformat(), round(qty * price, 2)))
            po_items.append((po_id, 1, material_id, qty, price))
            receipts.append((po_id, material_id, qty, posted.isoformat(), accepted, rejected,
                             rng.choice(("WH-NORTH", "WH-SOUTH", "WH-CENTRAL")),
                             "REJECTED" if rejected else "PASSED", f"DN-{po_id:08d}"))
            inventory[material_id] += accepted
        _insert_many(conn, "INSERT INTO purchase_orders (vendor_id,status,created_date,total_amount) VALUES (?,?,?,?)", pos)
        _insert_many(conn, "INSERT INTO po_items VALUES (?,?,?,?,?)", po_items)
        _insert_many(conn, "INSERT INTO goods_receipts (po_id,material_id,qty,posted_date,accepted_qty,rejected_qty,warehouse,quality_status,delivery_note) VALUES (?,?,?,?,?,?,?,?,?)", receipts)

        sales, sale_items, shipments, ar_invoice_data = [], [], [], []
        for so_id in range(1, scale["sales_orders"] + 1):
            available = [i for i in range(1, len(inventory)) if inventory[i] > 0]
            material_id = rng.choice(available)
            qty = min(rng.randint(1, 10), inventory[material_id])
            inventory[material_id] -= qty
            created = _day(rng, latest=date.today() - timedelta(days=1))
            requested = created + timedelta(days=rng.randint(2, 14))
            fulfilled = min(requested + timedelta(days=rng.randint(-1, 5)), date.today())
            total = round(qty * materials[material_id - 1][2], 2)
            customer_id = rng.randint(1, scale["customers"])
            sales.append((customer_id, "FULFILLED", created.isoformat(), total, requested.isoformat(),
                          fulfilled.isoformat(), rng.choice(("WEB", "DIRECT", "PARTNER")),
                          rng.choice(("NORMAL", "HIGH", "URGENT"))))
            sale_items.append((so_id, 1, material_id, qty, materials[material_id - 1][2]))
            shipped = max(created, fulfilled - timedelta(days=rng.randint(1, 5)))
            shipments.append((so_id, rng.choice(("WH-NORTH", "WH-SOUTH", "WH-CENTRAL")),
                              rng.choice(("DHL", "UPS", "FEDEX")), f"TRK-{seed}-{so_id:09d}",
                              shipped.isoformat(), fulfilled.isoformat(), "DELIVERED"))
            ar_invoice_data.append((customer_id, total, created, so_id))
        _insert_many(conn, "INSERT INTO sales_orders (customer_id,status,created_date,total_amount,requested_delivery_date,fulfilled_date,sales_channel,priority) VALUES (?,?,?,?,?,?,?,?)", sales)
        _insert_many(conn, "INSERT INTO so_items VALUES (?,?,?,?,?)", sale_items)
        _insert_many(conn, "INSERT INTO shipments (so_id,warehouse,carrier,tracking_number,shipped_date,delivered_date,status) VALUES (?,?,?,?,?,?,?)", shipments)
        conn.executemany("UPDATE stock SET qty_on_hand=? WHERE material_id=? AND plant='1000'",
                         ((qty, material_id) for material_id, qty in enumerate(inventory) if material_id))

        invoices = []
        for po_id, (po, receipt) in enumerate(zip(pos, receipts), 1):
            invoice_date = date.fromisoformat(receipt[3])
            invoices.append(("AP", po[0], f"PO-{po_id}", po[3], "OPEN", (invoice_date + timedelta(days=30)).isoformat(),
                             invoice_date.isoformat(), None, "USD", round(po[3] * .08, 2), "PO", po_id, "NONE"))
        for customer_id, amount, invoice_date, so_id in ar_invoice_data:
            invoices.append(("AR", customer_id, f"SO-{so_id}", amount, "OPEN", (invoice_date + timedelta(days=30)).isoformat(),
                             invoice_date.isoformat(), None, "USD", round(amount * .08, 2), "SO", so_id,
                             "DISPUTED" if rng.random() < .01 else "NONE"))
        _insert_many(conn, "INSERT INTO invoices (direction,party_id,reference,amount,status,due_date,invoice_date,paid_date,currency,tax_amount,source_type,source_id,dispute_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", invoices)

        account_ids = {row["name"]: row["account_id"] for row in conn.execute("SELECT * FROM gl_accounts")}
        payments, journals, journal_lines = [], [], []
        journal_id = 0
        for invoice_id, invoice in enumerate(invoices, 1):
            if rng.random() >= .72 or invoice[12] == "DISPUTED":
                continue
            paid = min(date.fromisoformat(invoice[5]) + timedelta(days=rng.randint(-10, 45)), date.today())
            payments.append((invoice_id, invoice[3], paid.isoformat(), rng.choice(("TRANSFER", "CARD", "ACH"))))
            conn.execute("UPDATE invoices SET status='PAID', paid_date=? WHERE invoice_id=?", (paid.isoformat(), invoice_id))
            journal_id += 1
            journals.append((paid.isoformat(), f"{invoice[0]} invoice {invoice_id}"))
            cents = round(invoice[3] * 100)
            if invoice[0] == "AP":
                lines = ((account_ids["Accounts Payable"], cents, 0), (account_ids["Cash"], 0, cents))
            else:
                lines = ((account_ids["Cash"], cents, 0), (account_ids["Accounts Receivable"], 0, cents))
            journal_lines.extend((journal_id, no, *line) for no, line in enumerate(lines, 1))
        _insert_many(conn, "INSERT INTO payments (invoice_id,amount,posted_date,method) VALUES (?,?,?,?)", payments)

        department_ids = []
        for name in DEPARTMENTS:
            department_ids.append(conn.execute("INSERT INTO departments (name) VALUES (?)", (name,)).lastrowid)
        employees = []
        for employee_id in range(1, scale["employees"] + 1):
            hire = _day(rng, latest=date(2025, 12, 31))
            salary = rng.randint(300_000, 1_200_000)
            employees.append((rng.choice(department_ids), fake.name(), f"employee{employee_id}@example.test", hire.isoformat(),
                              salary, 100, "ACTIVE", f"EMP-{employee_id:07d}",
                              rng.choice(("Analyst", "Specialist", "Manager", "Engineer", "Coordinator")), None,
                              rng.choice(("New York", "London", "Berlin", "Toronto", "Singapore")),
                              rng.choice(("FULL_TIME", "PART_TIME", "CONTRACT")), None,
                              round(rng.triangular(1, 5, 3.8), 1)))
        _insert_many(conn, "INSERT INTO employees (department_id,name,email,hire_date,monthly_salary,leave_balance,status,employee_number,job_title,manager_id,location,employment_type,contract_end_date,performance_rating) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", employees)

        leaves = []
        for _ in range(scale["leaves"]):
            employee_id = rng.randint(1, scale["employees"])
            start = _day(rng, earliest=max(START, date.fromisoformat(employees[employee_id - 1][3])))
            days = rng.randint(1, 7)
            requested = max(date.fromisoformat(employees[employee_id - 1][3]), start - timedelta(days=rng.randint(3, 60)))
            status = rng.choices(("APPROVED", "REJECTED", "PENDING"), (75, 15, 10))[0]
            leaves.append((employee_id, start.isoformat(), (start + timedelta(days=days - 1)).isoformat(), days,
                           status, rng.choice(("ANNUAL", "SICK", "PERSONAL")), requested.isoformat(),
                           None if status == "PENDING" else (requested + timedelta(days=rng.randint(1, 3))).isoformat(),
                           rng.choice(("Vacation", "Medical", "Family", "Personal"))))
        _insert_many(conn, "INSERT INTO leave_requests (employee_id,start_date,end_date,days,status,leave_type,requested_date,decision_date,reason) VALUES (?,?,?,?,?,?,?,?,?)", leaves)

        period = date.today().strftime("%Y-%m")
        run_id = conn.execute("INSERT INTO payroll_runs (period,posted_date) VALUES (?,?)", (period, date.today().isoformat())).lastrowid
        payslips = []
        for employee_id, employee in enumerate(employees, 1):
            gross, deduction = employee[4], round(employee[4] * rng.uniform(.12, .28))
            net = gross - deduction
            journal_id += 1
            journals.append((date.today().isoformat(), f"Payroll {period} employee {employee_id}"))
            journal_lines.extend(((journal_id, 1, account_ids["Payroll Expense"], gross, 0),
                                  (journal_id, 2, account_ids["Payroll Deductions Payable"], 0, deduction),
                                  (journal_id, 3, account_ids["Cash"], 0, net)))
            payslips.append((run_id, employee_id, gross, deduction, net, journal_id))
        _insert_many(conn, "INSERT INTO journal_entries (posting_date,reference) VALUES (?,?)", journals)
        _insert_many(conn, "INSERT INTO journal_lines VALUES (?,?,?,?,?)", journal_lines)
        _insert_many(conn, "INSERT INTO payslips (run_id,employee_id,gross,deduction,net,journal_id) VALUES (?,?,?,?,?,?)", payslips)

        counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in
                  ("vendors", "customers", "materials", "vendor_materials", "purchase_orders", "goods_receipts",
                   "sales_orders", "invoices", "payments", "employees", "leave_requests", "payslips", "journal_entries")}
        if profile != "test":
            required = ("vendors", "customers", "materials", "purchase_orders", "goods_receipts", "sales_orders",
                        "invoices", "employees", "leave_requests", "payslips")
            assert all(counts[name] >= 2_000 for name in required), counts
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        assert conn.execute("SELECT COALESCE(MIN(qty_on_hand),0) FROM stock").fetchone()[0] >= 0
    print(f"[seed] profile={profile} seed={seed}: " + ", ".join(f"{k}={v:,}" for k, v in counts.items()))
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=PROFILES, default=os.environ.get("ERP_SEED_PROFILE", "medium"))
    parser.add_argument("--seed", type=int, default=int(os.environ.get("SEED_RANDOM", "42")))
    parser.add_argument("--database", default=db.DB_PATH)
    parser.add_argument("--reset", action="store_true", help="delete and recreate the selected database")
    args = parser.parse_args()
    if args.reset:
        if os.path.exists(args.database):
            os.remove(args.database)
        db.init_schema(args.database)
    elif not db.db_exists(args.database):
        db.init_schema(args.database)
    old_path, db.DB_PATH = db.DB_PATH, args.database
    try:
        run_seed(args.profile, args.seed)
    finally:
        db.DB_PATH = old_path


if __name__ == "__main__":
    main()
