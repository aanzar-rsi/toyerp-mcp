"""Synthetic data generator. Populates the ERP by calling the same BAPI
functions the MCP server exposes, so seed data and live-tool data go
through identical code paths.
"""
import os
import random
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from faker import Faker

from server.bapi.vendor import BAPI_VENDOR_CREATE
from server.bapi.customer import BAPI_CUSTOMER_CREATE
from server.bapi.material import BAPI_MATERIAL_CREATE
from server.bapi.purchasing import BAPI_PO_CREATE, BAPI_GOODSMVT_CREATE
from server.bapi.sales import BAPI_SALESORDER_CREATE
from server.bapi.finance import (
    BAPI_INCOMINGINVOICE_CREATE,
    BAPI_AP_PAYMENT_POST,
    BAPI_AR_INVOICE_CREATE,
    BAPI_AR_PAYMENT_POST,
)
from server.bapi.hr import (
    BAPI_HR_DEPARTMENT_CREATE, BAPI_HR_EMPLOYEE_CREATE,
    BAPI_HR_LEAVE_REQUEST, BAPI_HR_LEAVE_DECIDE, BAPI_HR_PAYROLL_RUN,
)

MATERIAL_CATEGORIES = ["Electronics", "Hardware", "Office Supplies", "Raw Materials"]


def run_seed():
    seed = int(os.environ.get("SEED_RANDOM", "42"))
    Faker.seed(seed)
    random.seed(seed)
    fake = Faker()

    vendor_ids = []
    for _ in range(8):
        result = BAPI_VENDOR_CREATE(
            name=fake.company(),
            contact_email=fake.company_email(),
            address=fake.address().replace("\n", ", "),
            payment_terms=random.choice(["NET15", "NET30", "NET45"]),
        )
        vendor_ids.append(result["DATA"]["vendor_id"])

    customer_ids = []
    for _ in range(10):
        result = BAPI_CUSTOMER_CREATE(
            name=fake.company(),
            address=fake.address().replace("\n", ", "),
            credit_limit=random.choice([5000, 10000, 25000, 50000]),
        )
        customer_ids.append(result["DATA"]["customer_id"])

    material_ids = []
    for _ in range(15):
        result = BAPI_MATERIAL_CREATE(
            description=fake.catch_phrase(),
            uom="EA",
            unit_price=round(random.uniform(5, 500), 2),
            category=random.choice(MATERIAL_CATEGORIES),
        )
        material_ids.append(result["DATA"]["material_id"])

    po_ids = []
    for _ in range(12):
        vendor_id = random.choice(vendor_ids)
        items = [
            {"material_id": mid, "qty": random.randint(10, 100)}
            for mid in random.sample(material_ids, k=random.randint(1, 3))
        ]
        result = BAPI_PO_CREATE(vendor_id=vendor_id, items=items)
        po_ids.append((result["DATA"]["po_id"], vendor_id, items, result["DATA"]["total_amount"]))

    for po_id, vendor_id, items, total in po_ids:
        if random.random() < 0.7:
            for item in items:
                BAPI_GOODSMVT_CREATE(po_id=po_id, material_id=item["material_id"], qty=item["qty"])
            total = round(total, 2)
            invoice = BAPI_INCOMINGINVOICE_CREATE(
                vendor_id=vendor_id, amount=total, reference=f"PO {po_id}"
            )
            if random.random() < 0.6:
                BAPI_AP_PAYMENT_POST(invoice_id=invoice["DATA"]["invoice_id"], amount=total)

    for _ in range(10):
        customer_id = random.choice(customer_ids)
        candidate_materials = random.sample(material_ids, k=random.randint(1, 2))
        items = [{"material_id": mid, "qty": random.randint(1, 5)} for mid in candidate_materials]
        result = BAPI_SALESORDER_CREATE(customer_id=customer_id, items=items)
        if result["RETURN"][0]["type"] != "S":
            continue
        total = round(result["DATA"]["total_amount"], 2)
        invoice = BAPI_AR_INVOICE_CREATE(customer_id=customer_id, amount=total, reference="Sales order")
        if random.random() < 0.6:
            BAPI_AR_PAYMENT_POST(invoice_id=invoice["DATA"]["invoice_id"], amount=total)

    departments = [BAPI_HR_DEPARTMENT_CREATE(name)["DATA"]["department_id"]
                   for name in ("Operations", "Finance", "Sales")]
    employee_ids = []
    for _ in range(6):
        employee_ids.append(BAPI_HR_EMPLOYEE_CREATE(
            name=fake.name(), department_id=random.choice(departments),
            hire_date="2024-01-01", monthly_salary=random.choice([3200, 4200, 5500]),
            email=fake.unique.email(),
        )["DATA"]["employee_id"])
    leave = BAPI_HR_LEAVE_REQUEST(employee_ids[0], "2025-01-13", "2025-01-15")
    BAPI_HR_LEAVE_DECIDE(leave["DATA"]["leave_id"], approve=True)
    BAPI_HR_PAYROLL_RUN(date.today().strftime("%Y-%m"),
                        deductions=[{"employee_id": employee_ids[0], "amount": 250}])


if __name__ == "__main__":
    run_seed()
