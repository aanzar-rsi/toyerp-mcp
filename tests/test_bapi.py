"""Smoke tests: one concise assertion block per BAPI domain."""
import pytest
import sqlite3
from pathlib import Path

from server.db import DB_PATH, init_schema, migrate_schema, get_conn
from server.bapi.vendor import BAPI_VENDOR_CREATE, BAPI_VENDOR_GETLIST, BAPI_VENDOR_GETDETAIL
from server.bapi.material import BAPI_MATERIAL_CREATE, BAPI_MATERIAL_STOCK_GETLIST
from server.bapi.purchasing import BAPI_PO_CREATE, BAPI_GOODSMVT_CREATE, BAPI_PO_GETDETAIL
from server.bapi.customer import BAPI_CUSTOMER_CREATE
from server.bapi.sales import BAPI_SALESORDER_CREATE
from server.bapi.finance import (
    BAPI_INCOMINGINVOICE_CREATE, BAPI_AP_PAYMENT_POST, BAPI_AR_INVOICE_CREATE,
    BAPI_AR_PAYMENT_POST, BAPI_GL_ACCOUNT_GETLIST, BAPI_GL_JOURNAL_POST,
    BAPI_GL_JOURNAL_GETLIST, BAPI_GL_ACCOUNT_SUMMARY,
)
from server.bapi.hr import (
    BAPI_HR_DEPARTMENT_CREATE, BAPI_HR_EMPLOYEE_CREATE, BAPI_HR_EMPLOYEE_GETDETAIL,
    BAPI_HR_EMPLOYEE_CHANGE_STATUS, BAPI_HR_LEAVE_REQUEST, BAPI_HR_LEAVE_DECIDE,
    BAPI_HR_PAYROLL_RUN, BAPI_HR_PAYSLIP_GETLIST,
)


@pytest.fixture(scope="session", autouse=True)
def fresh_db():
    init_schema(DB_PATH)


def test_vendor_lifecycle():
    created = BAPI_VENDOR_CREATE(name="Acme Supplies")
    assert created["RETURN"][0]["type"] == "S"
    vendor_id = created["DATA"]["vendor_id"]

    listed = BAPI_VENDOR_GETLIST()
    assert any(v["vendor_id"] == vendor_id for v in listed["DATA"])

    detail = BAPI_VENDOR_GETDETAIL(vendor_id)
    assert detail["DATA"]["name"] == "Acme Supplies"
    assert BAPI_VENDOR_GETDETAIL(999999)["RETURN"][0]["type"] == "E"


def test_material_and_stock():
    vendor_id = BAPI_VENDOR_CREATE(name="Bolt Vendor")["DATA"]["vendor_id"]
    material_id = BAPI_MATERIAL_CREATE(description="Steel Bolt", unit_price=1.5)["DATA"]["material_id"]

    stock_before = BAPI_MATERIAL_STOCK_GETLIST(material_id=material_id)["DATA"][0]["qty_on_hand"]
    assert stock_before == 0

    po = BAPI_PO_CREATE(vendor_id=vendor_id, items=[{"material_id": material_id, "qty": 50}])
    po_id = po["DATA"]["po_id"]
    assert po["DATA"]["total_amount"] == 75.0

    BAPI_GOODSMVT_CREATE(po_id=po_id, material_id=material_id, qty=50)
    stock_after = BAPI_MATERIAL_STOCK_GETLIST(material_id=material_id)["DATA"][0]["qty_on_hand"]
    assert stock_after == 50

    detail = BAPI_PO_GETDETAIL(po_id)
    assert detail["DATA"]["po"]["status"] == "RECEIVED"


def test_sales_order_checks_stock():
    customer_id = BAPI_CUSTOMER_CREATE(name="Retail Co")["DATA"]["customer_id"]
    material_id = BAPI_MATERIAL_CREATE(description="Widget", unit_price=10)["DATA"]["material_id"]

    short = BAPI_SALESORDER_CREATE(customer_id=customer_id, items=[{"material_id": material_id, "qty": 5}])
    assert short["RETURN"][0]["type"] == "E"

    vendor_id = BAPI_VENDOR_CREATE(name="Widget Vendor")["DATA"]["vendor_id"]
    po_id = BAPI_PO_CREATE(vendor_id=vendor_id, items=[{"material_id": material_id, "qty": 20}])["DATA"]["po_id"]
    BAPI_GOODSMVT_CREATE(po_id=po_id, material_id=material_id, qty=20)

    ok = BAPI_SALESORDER_CREATE(customer_id=customer_id, items=[{"material_id": material_id, "qty": 5}])
    assert ok["RETURN"][0]["type"] == "S"
    remaining = BAPI_MATERIAL_STOCK_GETLIST(material_id=material_id)["DATA"][0]["qty_on_hand"]
    assert remaining == 15


def test_ap_payment_updates_gl():
    vendor_id = BAPI_VENDOR_CREATE(name="Finance Test Vendor")["DATA"]["vendor_id"]
    invoice_id = BAPI_INCOMINGINVOICE_CREATE(vendor_id=vendor_id, amount=200)["DATA"]["invoice_id"]

    before = {a["name"]: a["balance"] for a in BAPI_GL_ACCOUNT_GETLIST()["DATA"]}
    result = BAPI_AP_PAYMENT_POST(invoice_id=invoice_id, amount=200)
    assert result["RETURN"][0]["type"] == "S"
    after = {a["name"]: a["balance"] for a in BAPI_GL_ACCOUNT_GETLIST()["DATA"]}

    assert after["Cash"] == before["Cash"] - 200
    assert after["Accounts Payable"] == before["Accounts Payable"] + 200
    assert BAPI_AP_PAYMENT_POST(invoice_id=invoice_id, amount=200)["RETURN"][0]["type"] == "E"


def test_hr_leave_and_payroll_balances():
    department = BAPI_HR_DEPARTMENT_CREATE("Payroll Test")["DATA"]["department_id"]
    employee = BAPI_HR_EMPLOYEE_CREATE("Ada", department, "2024-01-01", 1200.50,
                                       leave_balance=4)["DATA"]["employee_id"]
    assert BAPI_HR_LEAVE_REQUEST(employee, "bad", "2026-09-03")["RETURN"][0]["type"] == "E"
    leave = BAPI_HR_LEAVE_REQUEST(employee, "2026-09-01", "2026-09-03")["DATA"]["leave_id"]
    assert BAPI_HR_LEAVE_REQUEST(employee, "2026-09-02", "2026-09-04")["RETURN"][0]["type"] == "E"
    assert BAPI_HR_LEAVE_DECIDE(leave, True)["RETURN"][0]["type"] == "S"
    assert BAPI_HR_EMPLOYEE_GETDETAIL(employee)["DATA"]["leave_balance"] == 1
    assert BAPI_HR_LEAVE_REQUEST(employee, "2026-09-05", "2026-09-06")["RETURN"][0]["type"] == "E"

    before = {row["name"]: row["balance"] for row in BAPI_GL_ACCOUNT_GETLIST()["DATA"]}
    run = BAPI_HR_PAYROLL_RUN("2026-09", [{"employee_id": employee, "amount": 200.25}])
    assert run["RETURN"][0]["type"] == "S"
    payslip = next(row for row in BAPI_HR_PAYSLIP_GETLIST("2026-09")["DATA"]
                   if row["employee_id"] == employee)
    assert (payslip["gross"], payslip["deduction"], payslip["net"]) == (1200.5, 200.25, 1000.25)
    journal = next(row for row in BAPI_GL_JOURNAL_GETLIST()["DATA"]
                   if row["journal_id"] == payslip["journal_id"])
    assert sum(line["debit"] for line in journal["lines"]) == sum(line["credit"] for line in journal["lines"])
    after = {row["name"]: row["balance"] for row in BAPI_GL_ACCOUNT_GETLIST()["DATA"]}
    assert after["Payroll Expense"] - before["Payroll Expense"] == 1200.5
    assert after["Cash"] - before["Cash"] == -1000.25
    assert after["Payroll Deductions Payable"] - before["Payroll Deductions Payable"] == -200.25
    assert BAPI_HR_PAYROLL_RUN("2026-09")["RETURN"][0]["type"] == "E"
    assert BAPI_HR_EMPLOYEE_CHANGE_STATUS(employee, "INACTIVE")["RETURN"][0]["type"] == "S"
    assert BAPI_HR_LEAVE_REQUEST(employee, "2026-10-01", "2026-10-01")["RETURN"][0]["type"] == "E"


def test_finance_validation_and_balanced_journal():
    accounts = {row["name"]: row["account_id"] for row in BAPI_GL_ACCOUNT_GETLIST()["DATA"]}
    cash, expense = accounts["Cash"], accounts["Cost of Goods Sold"]
    bad = BAPI_GL_JOURNAL_POST([{"account_id": cash, "debit": 10},
                                {"account_id": expense, "credit": 9}])
    assert bad["RETURN"][0]["type"] == "E"
    assert BAPI_GL_JOURNAL_POST([{"account_id": cash, "debit": 0},
                                {"account_id": expense, "credit": 0}])["RETURN"][0]["type"] == "E"
    assert BAPI_GL_JOURNAL_POST([{"account_id": cash, "debit": 0.001},
                                {"account_id": expense, "credit": 0.001}])["RETURN"][0]["type"] == "E"
    before = BAPI_GL_JOURNAL_GETLIST()["DATA"]
    ok = BAPI_GL_JOURNAL_POST([{"account_id": cash, "debit": 10.25},
                               {"account_id": expense, "credit": 10.25}], "Test")
    assert ok["RETURN"][0]["type"] == "S"
    assert len(BAPI_GL_JOURNAL_GETLIST(cash)["DATA"]) >= 1
    assert len(BAPI_GL_JOURNAL_GETLIST()["DATA"]) == len(before) + 1
    assert any(row["debits"] > 0 for row in BAPI_GL_ACCOUNT_SUMMARY()["DATA"])

    customer = BAPI_CUSTOMER_CREATE("Finance Customer")["DATA"]["customer_id"]
    invoice = BAPI_AR_INVOICE_CREATE(customer, 55.75)["DATA"]["invoice_id"]
    assert BAPI_AR_PAYMENT_POST(invoice, 55)["RETURN"][0]["type"] == "E"
    assert BAPI_AR_PAYMENT_POST(invoice, 55.75)["RETURN"][0]["type"] == "S"
    with get_conn() as conn:
        assert conn.execute("SELECT status FROM invoices WHERE invoice_id = ?", (invoice,)).fetchone()[0] == "PAID"


def test_migrate_existing_database_preserves_history(tmp_path):
    path = tmp_path / "legacy.db"
    schema = Path(__file__).resolve().parents[1] / "data" / "schema.sql"
    old_schema = schema.read_text().split("CREATE TABLE journal_entries")[0]
    old_schema += "\nINSERT INTO gl_accounts (name, account_type) VALUES ('Cash', 'ASSET');"
    conn = sqlite3.connect(path)
    conn.executescript(old_schema)
    conn.execute("INSERT INTO gl_postings (account_id, amount, posting_date) VALUES (1, 42, '2024-01-01')")
    conn.commit()
    conn.close()
    migrate_schema(str(path))
    migrate_schema(str(path))
    with get_conn(str(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert conn.execute("SELECT amount FROM gl_postings").fetchone()[0] == 42
        assert conn.execute("SELECT COUNT(*) FROM gl_accounts WHERE name = 'Payroll Expense'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM departments").fetchone()[0] == 0


def test_payroll_validation_keeps_transactions_atomic():
    department = BAPI_HR_DEPARTMENT_CREATE("Payroll Atomicity")["DATA"]["department_id"]
    employee = BAPI_HR_EMPLOYEE_CREATE("Bex", department, "2026-01-01", 500)["DATA"]["employee_id"]
    assert BAPI_HR_PAYROLL_RUN("2026-02", [{"employee_id": employee, "amount": 501}])["RETURN"][0]["type"] == "E"
    assert BAPI_HR_PAYSLIP_GETLIST("2026-02")["DATA"] == []
    assert BAPI_HR_PAYROLL_RUN("2026-02", [{"employee_id": employee, "amount": 500}])["RETURN"][0]["type"] == "S"
    payslip = next(p for p in BAPI_HR_PAYSLIP_GETLIST("2026-02")["DATA"] if p["employee_id"] == employee)
    assert payslip["net"] == 0
    assert BAPI_HR_PAYROLL_RUN("2026-13")["RETURN"][0]["type"] == "E"


def test_new_schema_migration_is_safe(tmp_path):
    path = str(tmp_path / "fresh.db")
    init_schema(path)
    migrate_schema(path)
    migrate_schema(path)
    with get_conn(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM gl_accounts WHERE name = 'Payroll Expense'").fetchone()[0] == 1


def test_seed_hr_and_finance_on_new_database(tmp_path, monkeypatch):
    from data.seed import run_seed
    import server.db as db
    path = str(tmp_path / "seed.db")
    init_schema(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    run_seed()
    with get_conn(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == 6
        assert conn.execute("SELECT COUNT(*) FROM payslips").fetchone()[0] == 6
        assert conn.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0] > 6
