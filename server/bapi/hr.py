"""Departments, employees, leave requests and monthly payroll."""
from datetime import date

from server.db import get_conn, bapi_result, bapi_error, rows_to_dicts, page_args, paged_result
from server.bapi.finance import _cents, _gl_account_id, _post_journal


def _date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
        return parsed
    except (ValueError, TypeError):
        raise ValueError("Date must be in YYYY-MM-DD format")


def BAPI_HR_DEPARTMENT_CREATE(name: str) -> dict:
    if not name or not name.strip():
        return bapi_error("Department name is required")
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM departments WHERE name = ?", (name.strip(),)).fetchone():
            return bapi_error("Department already exists")
        department_id = conn.execute("INSERT INTO departments (name) VALUES (?)", (name.strip(),)).lastrowid
    return bapi_result(data={"department_id": department_id})


def BAPI_HR_DEPARTMENT_GETLIST() -> dict:
    with get_conn() as conn:
        return bapi_result(data=rows_to_dicts(conn.execute("SELECT * FROM departments ORDER BY department_id").fetchall()))


def BAPI_HR_EMPLOYEE_CREATE(name: str, department_id: int, hire_date: str,
                            monthly_salary: float, email: str = "", leave_balance: int = 20) -> dict:
    if not name or not name.strip():
        return bapi_error("Employee name is required")
    try:
        _date(hire_date)
        salary = _cents(monthly_salary)
    except ValueError as exc:
        return bapi_error(str(exc))
    if salary <= 0 or type(leave_balance) is not int or leave_balance < 0:
        return bapi_error("Salary must be positive and leave balance nonnegative")
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM departments WHERE department_id = ?", (department_id,)).fetchone():
            return bapi_error(f"Department {department_id} not found")
        if email and conn.execute("SELECT 1 FROM employees WHERE email = ?", (email,)).fetchone():
            return bapi_error("Employee email already exists")
        employee_id = conn.execute(
            "INSERT INTO employees (department_id, name, email, hire_date, monthly_salary, leave_balance) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (department_id, name.strip(), email or None, hire_date, salary, leave_balance),
        ).lastrowid
    return bapi_result(data={"employee_id": employee_id})


def _employee(row):
    return {**dict(row), "monthly_salary": row["monthly_salary"] / 100}


def BAPI_HR_EMPLOYEE_GETLIST(department_id: int = None, status: str = None,
                             limit: int = 100, after_id: int = 0) -> dict:
    if error := page_args(limit, after_id):
        return bapi_error(error)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM employees WHERE (? IS NULL OR department_id = ?) "
            "AND (? IS NULL OR status = ?) AND employee_id > ? ORDER BY employee_id LIMIT ?",
            (department_id, department_id, status, status, after_id, limit + 1),
        ).fetchall()
    return paged_result(rows, limit, "employee_id", _employee)


def BAPI_HR_EMPLOYEE_GETDETAIL(employee_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM employees WHERE employee_id = ?", (employee_id,)).fetchone()
    return bapi_result(data=_employee(row)) if row else bapi_error(f"Employee {employee_id} not found")


def BAPI_HR_EMPLOYEE_CHANGE_STATUS(employee_id: int, status: str) -> dict:
    if status not in ("ACTIVE", "INACTIVE"):
        return bapi_error("Status must be ACTIVE or INACTIVE")
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM employees WHERE employee_id = ?", (employee_id,)).fetchone():
            return bapi_error(f"Employee {employee_id} not found")
        conn.execute("UPDATE employees SET status = ? WHERE employee_id = ?", (status, employee_id))
    return bapi_result()


def BAPI_HR_LEAVE_REQUEST(employee_id: int, start_date: str, end_date: str) -> dict:
    try:
        start, end = _date(start_date), _date(end_date)
    except ValueError as exc:
        return bapi_error(str(exc))
    if end < start:
        return bapi_error("Leave end date must not precede start date")
    # ponytail: calendar days include weekends/holidays; add a work-calendar if policy needs one.
    days = (end - start).days + 1
    with get_conn() as conn:
        employee = conn.execute("SELECT status, leave_balance FROM employees WHERE employee_id = ?", (employee_id,)).fetchone()
        if not employee or employee["status"] != "ACTIVE":
            return bapi_error("Employee not found or inactive")
        if days > employee["leave_balance"]:
            return bapi_error("Insufficient leave balance")
        if conn.execute(
            "SELECT 1 FROM leave_requests WHERE employee_id = ? AND status != 'REJECTED' "
            "AND start_date <= ? AND end_date >= ?", (employee_id, end_date, start_date),
        ).fetchone():
            return bapi_error("Leave overlaps an existing request")
        leave_id = conn.execute(
            "INSERT INTO leave_requests (employee_id, start_date, end_date, days, requested_date) VALUES (?, ?, ?, ?, ?)",
            (employee_id, start_date, end_date, days, date.today().isoformat()),
        ).lastrowid
    return bapi_result(data={"leave_id": leave_id, "days": days})


def BAPI_HR_LEAVE_DECIDE(leave_id: int, approve: bool) -> dict:
    with get_conn() as conn:
        leave = conn.execute("SELECT * FROM leave_requests WHERE leave_id = ?", (leave_id,)).fetchone()
        if not leave or leave["status"] != "PENDING":
            return bapi_error("Pending leave request not found")
        if approve:
            updated = conn.execute(
                "UPDATE employees SET leave_balance = leave_balance - ? "
                "WHERE employee_id = ? AND status = 'ACTIVE' AND leave_balance >= ?",
                (leave["days"], leave["employee_id"], leave["days"]),
            )
            if not updated.rowcount:
                return bapi_error("Employee inactive or insufficient leave balance")
        conn.execute("UPDATE leave_requests SET status = ?, decision_date = ? WHERE leave_id = ?",
                     ("APPROVED" if approve else "REJECTED", date.today().isoformat(), leave_id))
    return bapi_result()


def BAPI_HR_LEAVE_GETLIST(employee_id: int = None, limit: int = 100, after_id: int = 0) -> dict:
    if error := page_args(limit, after_id):
        return bapi_error(error)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM leave_requests WHERE (? IS NULL OR employee_id = ?) "
            "AND leave_id > ? ORDER BY leave_id LIMIT ?",
            (employee_id, employee_id, after_id, limit + 1),
        ).fetchall()
    return paged_result(rows, limit, "leave_id")


def BAPI_HR_PAYROLL_RUN(period: str, deductions: list = None) -> dict:
    """Pay all active staff once for YYYY-MM; deductions: [{employee_id, amount}]."""
    try:
        if len(period) != 7 or _date(period + "-01").strftime("%Y-%m") != period or period == "9999-12":
            raise ValueError
    except (ValueError, TypeError):
        return bapi_error("Period must be YYYY-MM")
    if deductions is not None and not isinstance(deductions, list):
        return bapi_error("Deductions must be a list")
    # ponytail: salary is paid in full for the hire month; prorate if payroll policy requires it.
    amounts = {}
    try:
        for item in deductions or []:
            employee_id = item["employee_id"]
            amount = _cents(item["amount"])
            if type(employee_id) is not int or employee_id in amounts or amount < 0:
                raise ValueError("Deductions require unique employee IDs and nonnegative amounts")
            amounts[employee_id] = amount
    except (ValueError, KeyError, TypeError) as exc:
        return bapi_error(str(exc))
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM payroll_runs WHERE period = ?", (period,)).fetchone():
            return bapi_error(f"Payroll for {period} already posted")
        start = date.fromisoformat(period + "-01")
        next_month = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
        employees = conn.execute("SELECT * FROM employees WHERE status = 'ACTIVE' AND hire_date < ? ORDER BY employee_id",
                                 (next_month.isoformat(),)).fetchall()
        if not employees:
            return bapi_error("No eligible active employees")
        if amounts.keys() - {row["employee_id"] for row in employees}:
            return bapi_error("Deduction references an ineligible employee")
        if any(amounts.get(row["employee_id"], 0) > row["monthly_salary"] for row in employees):
            return bapi_error("Deduction exceeds gross salary")
        today = date.today().isoformat()
        run_id = conn.execute("INSERT INTO payroll_runs (period, posted_date) VALUES (?, ?)",
                              (period, today)).lastrowid
        expense = _gl_account_id(conn, "Payroll Expense")
        payable = _gl_account_id(conn, "Payroll Deductions Payable")
        cash = _gl_account_id(conn, "Cash")
        for employee in employees:
            gross = employee["monthly_salary"]
            deduction = amounts.get(employee["employee_id"], 0)
            net = gross - deduction
            lines = [(expense, gross, 0)]
            if deduction:
                lines.append((payable, 0, deduction))
            if net:
                lines.append((cash, 0, net))
            journal_id = _post_journal(conn, lines, f"Payroll {period} employee {employee['employee_id']}", today)
            conn.execute(
                "INSERT INTO payslips (run_id, employee_id, gross, deduction, net, journal_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, employee["employee_id"], gross, deduction, net, journal_id),
            )
    return bapi_result(data={"run_id": run_id, "employee_count": len(employees)})


def BAPI_HR_PAYSLIP_GETLIST(period: str = None, employee_id: int = None,
                            limit: int = 100, after_id: int = 0) -> dict:
    if error := page_args(limit, after_id):
        return bapi_error(error)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT p.*, r.period FROM payslips p JOIN payroll_runs r ON r.run_id = p.run_id "
            "WHERE (? IS NULL OR r.period = ?) AND (? IS NULL OR p.employee_id = ?) "
            "AND p.payslip_id > ? ORDER BY p.payslip_id LIMIT ?",
            (period, period, employee_id, employee_id, after_id, limit + 1),
        ).fetchall()
    return paged_result(rows, limit, "payslip_id", lambda row: {
        **dict(row), "gross": row["gross"] / 100,
        "deduction": row["deduction"] / 100, "net": row["net"] / 100,
    })
