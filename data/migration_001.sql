CREATE TABLE IF NOT EXISTS journal_entries (
    journal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    posting_date TEXT NOT NULL,
    reference TEXT
);

CREATE TABLE IF NOT EXISTS journal_lines (
    journal_id INTEGER NOT NULL REFERENCES journal_entries(journal_id),
    line_no INTEGER NOT NULL,
    account_id INTEGER NOT NULL REFERENCES gl_accounts(account_id),
    debit INTEGER NOT NULL DEFAULT 0 CHECK (debit >= 0),
    credit INTEGER NOT NULL DEFAULT 0 CHECK (credit >= 0),
    PRIMARY KEY (journal_id, line_no),
    CHECK ((debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0))
);

CREATE TABLE IF NOT EXISTS departments (
    department_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS employees (
    employee_id INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id INTEGER NOT NULL REFERENCES departments(department_id),
    name TEXT NOT NULL,
    email TEXT UNIQUE,
    hire_date TEXT NOT NULL,
    monthly_salary INTEGER NOT NULL CHECK (monthly_salary > 0),
    leave_balance INTEGER NOT NULL DEFAULT 20 CHECK (leave_balance >= 0),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE'))
);

CREATE TABLE IF NOT EXISTS leave_requests (
    leave_id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(employee_id),
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    days INTEGER NOT NULL CHECK (days > 0),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
    CHECK (end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS payroll_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    period TEXT NOT NULL UNIQUE,
    posted_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payslips (
    payslip_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES payroll_runs(run_id),
    employee_id INTEGER NOT NULL REFERENCES employees(employee_id),
    gross INTEGER NOT NULL CHECK (gross > 0),
    deduction INTEGER NOT NULL CHECK (deduction >= 0),
    net INTEGER NOT NULL CHECK (net >= 0),
    journal_id INTEGER NOT NULL REFERENCES journal_entries(journal_id),
    UNIQUE (run_id, employee_id)
);

INSERT INTO gl_accounts (name, account_type)
SELECT 'Payroll Expense', 'EXPENSE'
WHERE NOT EXISTS (SELECT 1 FROM gl_accounts WHERE name = 'Payroll Expense');
INSERT INTO gl_accounts (name, account_type)
SELECT 'Payroll Deductions Payable', 'LIABILITY'
WHERE NOT EXISTS (SELECT 1 FROM gl_accounts WHERE name = 'Payroll Deductions Payable');
