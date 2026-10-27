ALTER TABLE vendors ADD COLUMN created_date TEXT;
ALTER TABLE vendors ADD COLUMN phone TEXT;
ALTER TABLE vendors ADD COLUMN country TEXT;
ALTER TABLE vendors ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD';
ALTER TABLE vendors ADD COLUMN rating REAL CHECK (rating BETWEEN 1 AND 5);
ALTER TABLE vendors ADD COLUMN lead_time_days INTEGER;
ALTER TABLE vendors ADD COLUMN contract_start_date TEXT;
ALTER TABLE vendors ADD COLUMN contract_end_date TEXT;
ALTER TABLE vendors ADD COLUMN active_contract INTEGER NOT NULL DEFAULT 1 CHECK (active_contract IN (0, 1));

ALTER TABLE customers ADD COLUMN created_date TEXT;
ALTER TABLE customers ADD COLUMN contact_email TEXT;
ALTER TABLE customers ADD COLUMN phone TEXT;
ALTER TABLE customers ADD COLUMN country TEXT;
ALTER TABLE customers ADD COLUMN customer_type TEXT;
ALTER TABLE customers ADD COLUMN industry TEXT;
ALTER TABLE customers ADD COLUMN payment_terms TEXT DEFAULT 'NET30';
ALTER TABLE customers ADD COLUMN credit_rating TEXT;
ALTER TABLE customers ADD COLUMN risk_level TEXT;

ALTER TABLE materials ADD COLUMN sku TEXT;
ALTER TABLE materials ADD COLUMN cost_price REAL;
ALTER TABLE materials ADD COLUMN brand TEXT;
ALTER TABLE materials ADD COLUMN country_of_origin TEXT;
ALTER TABLE materials ADD COLUMN reorder_level REAL DEFAULT 0;
ALTER TABLE materials ADD COLUMN created_date TEXT;
ALTER TABLE materials ADD COLUMN status TEXT NOT NULL DEFAULT 'ACTIVE';
CREATE UNIQUE INDEX materials_sku_idx ON materials(sku);

CREATE TABLE vendor_materials (
    vendor_id INTEGER NOT NULL REFERENCES vendors(vendor_id),
    material_id INTEGER NOT NULL REFERENCES materials(material_id),
    vendor_sku TEXT NOT NULL,
    unit_price REAL NOT NULL,
    minimum_order_qty REAL NOT NULL DEFAULT 1,
    lead_time_days INTEGER NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    PRIMARY KEY (vendor_id, material_id)
);

ALTER TABLE goods_receipts ADD COLUMN accepted_qty REAL;
ALTER TABLE goods_receipts ADD COLUMN rejected_qty REAL NOT NULL DEFAULT 0;
ALTER TABLE goods_receipts ADD COLUMN warehouse TEXT;
ALTER TABLE goods_receipts ADD COLUMN quality_status TEXT;
ALTER TABLE goods_receipts ADD COLUMN delivery_note TEXT;

ALTER TABLE sales_orders ADD COLUMN requested_delivery_date TEXT;
ALTER TABLE sales_orders ADD COLUMN fulfilled_date TEXT;
ALTER TABLE sales_orders ADD COLUMN sales_channel TEXT;
ALTER TABLE sales_orders ADD COLUMN priority TEXT;

CREATE TABLE shipments (
    shipment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    so_id INTEGER NOT NULL REFERENCES sales_orders(so_id),
    warehouse TEXT NOT NULL,
    carrier TEXT NOT NULL,
    tracking_number TEXT NOT NULL UNIQUE,
    shipped_date TEXT NOT NULL,
    delivered_date TEXT,
    status TEXT NOT NULL
);

ALTER TABLE invoices ADD COLUMN invoice_date TEXT;
ALTER TABLE invoices ADD COLUMN paid_date TEXT;
ALTER TABLE invoices ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD';
ALTER TABLE invoices ADD COLUMN tax_amount REAL NOT NULL DEFAULT 0;
ALTER TABLE invoices ADD COLUMN source_type TEXT;
ALTER TABLE invoices ADD COLUMN source_id INTEGER;
ALTER TABLE invoices ADD COLUMN dispute_status TEXT NOT NULL DEFAULT 'NONE';

ALTER TABLE employees ADD COLUMN employee_number TEXT;
ALTER TABLE employees ADD COLUMN job_title TEXT;
ALTER TABLE employees ADD COLUMN manager_id INTEGER REFERENCES employees(employee_id);
ALTER TABLE employees ADD COLUMN location TEXT;
ALTER TABLE employees ADD COLUMN employment_type TEXT;
ALTER TABLE employees ADD COLUMN contract_end_date TEXT;
ALTER TABLE employees ADD COLUMN performance_rating REAL CHECK (performance_rating BETWEEN 1 AND 5);
CREATE UNIQUE INDEX employees_number_idx ON employees(employee_number);

ALTER TABLE leave_requests ADD COLUMN leave_type TEXT NOT NULL DEFAULT 'ANNUAL';
ALTER TABLE leave_requests ADD COLUMN requested_date TEXT;
ALTER TABLE leave_requests ADD COLUMN decision_date TEXT;
ALTER TABLE leave_requests ADD COLUMN reason TEXT;

CREATE INDEX vendors_status_idx ON vendors(status);
CREATE INDEX customers_status_idx ON customers(status);
CREATE INDEX vendor_materials_material_idx ON vendor_materials(material_id, is_active);
CREATE INDEX po_vendor_status_date_idx ON purchase_orders(vendor_id, status, created_date);
CREATE INDEX gr_po_date_idx ON goods_receipts(po_id, posted_date);
CREATE INDEX so_customer_status_date_idx ON sales_orders(customer_id, status, created_date);
CREATE INDEX invoice_party_status_due_idx ON invoices(direction, party_id, status, due_date);
CREATE INDEX payment_invoice_date_idx ON payments(invoice_id, posted_date);
CREATE INDEX leave_employee_status_date_idx ON leave_requests(employee_id, status, start_date);
CREATE INDEX journal_posting_date_idx ON journal_entries(posting_date);
