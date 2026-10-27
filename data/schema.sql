PRAGMA foreign_keys = ON;

CREATE TABLE vendors (
    vendor_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    contact_email  TEXT,
    address        TEXT,
    payment_terms  TEXT DEFAULT 'NET30',
    status         TEXT NOT NULL DEFAULT 'ACTIVE',
    created_date   TEXT,
    phone          TEXT,
    country        TEXT,
    currency       TEXT NOT NULL DEFAULT 'USD',
    rating         REAL CHECK (rating BETWEEN 1 AND 5),
    lead_time_days INTEGER,
    contract_start_date TEXT,
    contract_end_date   TEXT,
    active_contract INTEGER NOT NULL DEFAULT 1 CHECK (active_contract IN (0, 1))
);

CREATE TABLE customers (
    customer_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    address        TEXT,
    credit_limit   REAL DEFAULT 10000,
    status         TEXT NOT NULL DEFAULT 'ACTIVE',
    created_date   TEXT,
    contact_email  TEXT,
    phone          TEXT,
    country        TEXT,
    customer_type  TEXT,
    industry       TEXT,
    payment_terms  TEXT DEFAULT 'NET30',
    credit_rating  TEXT,
    risk_level     TEXT
);

CREATE TABLE materials (
    material_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    description    TEXT NOT NULL,
    uom            TEXT NOT NULL DEFAULT 'EA',
    unit_price     REAL NOT NULL,
    category       TEXT,
    sku            TEXT UNIQUE,
    cost_price     REAL,
    brand          TEXT,
    country_of_origin TEXT,
    reorder_level  REAL DEFAULT 0,
    created_date   TEXT,
    status         TEXT NOT NULL DEFAULT 'ACTIVE'
);

CREATE TABLE vendor_materials (
    vendor_id      INTEGER NOT NULL REFERENCES vendors(vendor_id),
    material_id    INTEGER NOT NULL REFERENCES materials(material_id),
    vendor_sku     TEXT NOT NULL,
    unit_price     REAL NOT NULL,
    minimum_order_qty REAL NOT NULL DEFAULT 1,
    lead_time_days INTEGER NOT NULL,
    valid_from     TEXT NOT NULL,
    valid_to       TEXT,
    is_active      INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    PRIMARY KEY (vendor_id, material_id)
);

CREATE TABLE stock (
    material_id    INTEGER NOT NULL REFERENCES materials(material_id),
    plant          TEXT NOT NULL DEFAULT '1000',
    qty_on_hand    REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (material_id, plant)
);

CREATE TABLE purchase_orders (
    po_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id      INTEGER NOT NULL REFERENCES vendors(vendor_id),
    status         TEXT NOT NULL DEFAULT 'OPEN',
    created_date   TEXT NOT NULL,
    total_amount   REAL NOT NULL DEFAULT 0
);

CREATE TABLE po_items (
    po_id          INTEGER NOT NULL REFERENCES purchase_orders(po_id),
    item_no        INTEGER NOT NULL,
    material_id    INTEGER NOT NULL REFERENCES materials(material_id),
    qty            REAL NOT NULL,
    unit_price     REAL NOT NULL,
    PRIMARY KEY (po_id, item_no)
);

CREATE TABLE goods_receipts (
    gr_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id          INTEGER NOT NULL REFERENCES purchase_orders(po_id),
    material_id    INTEGER NOT NULL REFERENCES materials(material_id),
    qty            REAL NOT NULL,
    posted_date    TEXT NOT NULL,
    accepted_qty   REAL,
    rejected_qty   REAL NOT NULL DEFAULT 0,
    warehouse      TEXT,
    quality_status TEXT,
    delivery_note  TEXT
);

CREATE TABLE sales_orders (
    so_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id    INTEGER NOT NULL REFERENCES customers(customer_id),
    status         TEXT NOT NULL DEFAULT 'OPEN',
    created_date   TEXT NOT NULL,
    total_amount   REAL NOT NULL DEFAULT 0,
    requested_delivery_date TEXT,
    fulfilled_date TEXT,
    sales_channel  TEXT,
    priority       TEXT
);

CREATE TABLE so_items (
    so_id          INTEGER NOT NULL REFERENCES sales_orders(so_id),
    item_no        INTEGER NOT NULL,
    material_id    INTEGER NOT NULL REFERENCES materials(material_id),
    qty            REAL NOT NULL,
    unit_price     REAL NOT NULL,
    PRIMARY KEY (so_id, item_no)
);

CREATE TABLE shipments (
    shipment_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    so_id           INTEGER NOT NULL REFERENCES sales_orders(so_id),
    warehouse       TEXT NOT NULL,
    carrier         TEXT NOT NULL,
    tracking_number TEXT NOT NULL UNIQUE,
    shipped_date    TEXT NOT NULL,
    delivered_date  TEXT,
    status           TEXT NOT NULL
);

CREATE TABLE invoices (
    invoice_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    direction      TEXT NOT NULL CHECK (direction IN ('AP', 'AR')),
    party_id       INTEGER NOT NULL,
    reference      TEXT,
    amount         REAL NOT NULL,
    status         TEXT NOT NULL DEFAULT 'OPEN',
    due_date       TEXT,
    invoice_date   TEXT,
    paid_date      TEXT,
    currency       TEXT NOT NULL DEFAULT 'USD',
    tax_amount     REAL NOT NULL DEFAULT 0,
    source_type    TEXT,
    source_id      INTEGER,
    dispute_status TEXT NOT NULL DEFAULT 'NONE'
);

CREATE TABLE payments (
    payment_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id     INTEGER NOT NULL REFERENCES invoices(invoice_id),
    amount         REAL NOT NULL,
    posted_date    TEXT NOT NULL,
    method         TEXT NOT NULL DEFAULT 'TRANSFER'
);

CREATE TABLE gl_accounts (
    account_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    account_type   TEXT NOT NULL
);

CREATE TABLE gl_postings (
    posting_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id     INTEGER NOT NULL REFERENCES gl_accounts(account_id),
    amount         REAL NOT NULL,
    posting_date   TEXT NOT NULL,
    reference      TEXT
);

-- Journal debit/credit values and HR salary/payslip values are stored in cents.
CREATE TABLE journal_entries (
    journal_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    posting_date   TEXT NOT NULL,
    reference      TEXT
);

CREATE TABLE journal_lines (
    journal_id     INTEGER NOT NULL REFERENCES journal_entries(journal_id),
    line_no        INTEGER NOT NULL,
    account_id     INTEGER NOT NULL REFERENCES gl_accounts(account_id),
    debit          INTEGER NOT NULL DEFAULT 0 CHECK (debit >= 0),
    credit         INTEGER NOT NULL DEFAULT 0 CHECK (credit >= 0),
    PRIMARY KEY (journal_id, line_no),
    CHECK ((debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0))
);

CREATE TABLE departments (
    department_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL UNIQUE
);

CREATE TABLE employees (
    employee_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id  INTEGER NOT NULL REFERENCES departments(department_id),
    name           TEXT NOT NULL,
    email          TEXT UNIQUE,
    hire_date      TEXT NOT NULL,
    monthly_salary INTEGER NOT NULL CHECK (monthly_salary > 0),
    leave_balance  INTEGER NOT NULL DEFAULT 20 CHECK (leave_balance >= 0),
    status         TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE')),
    employee_number TEXT UNIQUE,
    job_title      TEXT,
    manager_id     INTEGER REFERENCES employees(employee_id),
    location       TEXT,
    employment_type TEXT,
    contract_end_date TEXT,
    performance_rating REAL CHECK (performance_rating BETWEEN 1 AND 5)
);

CREATE TABLE leave_requests (
    leave_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id    INTEGER NOT NULL REFERENCES employees(employee_id),
    start_date     TEXT NOT NULL,
    end_date       TEXT NOT NULL,
    days           INTEGER NOT NULL CHECK (days > 0),
    status         TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
    leave_type     TEXT NOT NULL DEFAULT 'ANNUAL',
    requested_date TEXT,
    decision_date  TEXT,
    reason         TEXT,
    CHECK (end_date >= start_date)
);

CREATE TABLE payroll_runs (
    run_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    period         TEXT NOT NULL UNIQUE,
    posted_date    TEXT NOT NULL
);

CREATE TABLE payslips (
    payslip_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         INTEGER NOT NULL REFERENCES payroll_runs(run_id),
    employee_id    INTEGER NOT NULL REFERENCES employees(employee_id),
    gross          INTEGER NOT NULL CHECK (gross > 0),
    deduction      INTEGER NOT NULL CHECK (deduction >= 0),
    net            INTEGER NOT NULL CHECK (net >= 0),
    journal_id     INTEGER NOT NULL REFERENCES journal_entries(journal_id),
    UNIQUE (run_id, employee_id)
);

CREATE TABLE users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0 CHECK (is_admin IN (0, 1)),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE roles (
    role_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE user_roles (
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    role_id INTEGER NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE role_tools (
    role_id INTEGER NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    PRIMARY KEY (role_id, tool_name)
);

CREATE TABLE user_tools (
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    allowed INTEGER NOT NULL CHECK (allowed IN (0, 1)),
    PRIMARY KEY (user_id, tool_name)
);

CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    expires_at INTEGER NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0 CHECK (revoked IN (0, 1))
);

CREATE INDEX sessions_user_idx ON sessions(user_id);

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

CREATE TABLE security_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);

INSERT INTO gl_accounts (name, account_type) VALUES
    ('Accounts Payable', 'LIABILITY'),
    ('Accounts Receivable', 'ASSET'),
    ('Cash', 'ASSET'),
    ('Inventory', 'ASSET'),
    ('Sales Revenue', 'REVENUE'),
    ('Cost of Goods Sold', 'EXPENSE'),
    ('Payroll Expense', 'EXPENSE'),
    ('Payroll Deductions Payable', 'LIABILITY');
