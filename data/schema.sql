PRAGMA foreign_keys = ON;

CREATE TABLE vendors (
    vendor_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    contact_email  TEXT,
    address        TEXT,
    payment_terms  TEXT DEFAULT 'NET30',
    status         TEXT NOT NULL DEFAULT 'ACTIVE'
);

CREATE TABLE customers (
    customer_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    address        TEXT,
    credit_limit   REAL DEFAULT 10000,
    status         TEXT NOT NULL DEFAULT 'ACTIVE'
);

CREATE TABLE materials (
    material_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    description    TEXT NOT NULL,
    uom            TEXT NOT NULL DEFAULT 'EA',
    unit_price     REAL NOT NULL,
    category       TEXT
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
    posted_date    TEXT NOT NULL
);

CREATE TABLE sales_orders (
    so_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id    INTEGER NOT NULL REFERENCES customers(customer_id),
    status         TEXT NOT NULL DEFAULT 'OPEN',
    created_date   TEXT NOT NULL,
    total_amount   REAL NOT NULL DEFAULT 0
);

CREATE TABLE so_items (
    so_id          INTEGER NOT NULL REFERENCES sales_orders(so_id),
    item_no        INTEGER NOT NULL,
    material_id    INTEGER NOT NULL REFERENCES materials(material_id),
    qty            REAL NOT NULL,
    unit_price     REAL NOT NULL,
    PRIMARY KEY (so_id, item_no)
);

CREATE TABLE invoices (
    invoice_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    direction      TEXT NOT NULL CHECK (direction IN ('AP', 'AR')),
    party_id       INTEGER NOT NULL,
    reference      TEXT,
    amount         REAL NOT NULL,
    status         TEXT NOT NULL DEFAULT 'OPEN',
    due_date       TEXT
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
    status         TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE'))
);

CREATE TABLE leave_requests (
    leave_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id    INTEGER NOT NULL REFERENCES employees(employee_id),
    start_date     TEXT NOT NULL,
    end_date       TEXT NOT NULL,
    days           INTEGER NOT NULL CHECK (days > 0),
    status         TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
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
