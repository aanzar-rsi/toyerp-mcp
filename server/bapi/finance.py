"""AP/AR invoicing, payments, and GL BAPIs."""
from datetime import date
from decimal import Decimal, InvalidOperation
from server.db import get_conn, bapi_result, bapi_error, rows_to_dicts, page_args, paged_result


def _gl_account_id(conn, name: str) -> int:
    row = conn.execute("SELECT account_id FROM gl_accounts WHERE name = ?", (name,)).fetchone()
    return row["account_id"]


def _cents(value) -> int:
    """Convert externally supplied currency to cents without silent rounding."""
    try:
        amount = Decimal(str(value))
        cents = amount * 100
        if not amount.is_finite():
            raise ValueError
        # Legacy PO/SO totals use floats; tolerate only sub-nanocent binary noise.
        if isinstance(value, float) and abs(cents - cents.to_integral_value()) < Decimal("0.0000001"):
            cents = cents.to_integral_value()
        if cents != cents.to_integral_value():
            raise ValueError
        return int(cents)
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        raise ValueError("Amount must be a finite number with at most two decimal places")


def _post_journal(conn, lines, reference: str, posting_date: str) -> int:
    """Insert validated, balanced debit/credit lines in the caller's transaction."""
    if len(lines) < 2 or any(debit < 0 or credit < 0 or (debit > 0) == (credit > 0)
                              for _, debit, credit in lines) or not any(debit for _, debit, _ in lines):
        raise ValueError("Journal needs at least two nonzero debit or credit lines")
    if sum(debit for _, debit, _ in lines) != sum(credit for _, _, credit in lines):
        raise ValueError("Journal debits and credits must balance")
    ids = [line[0] for line in lines]
    found = conn.execute(
        f"SELECT COUNT(*) FROM gl_accounts WHERE account_id IN ({','.join('?' for _ in ids)})", ids
    ).fetchone()[0]
    if found != len(set(ids)):
        raise ValueError("Journal contains an unknown account")
    journal_id = conn.execute(
        "INSERT INTO journal_entries (posting_date, reference) VALUES (?, ?)",
        (posting_date, reference),
    ).lastrowid
    for no, (account_id, debit, credit) in enumerate(lines, 1):
        conn.execute(
            "INSERT INTO journal_lines (journal_id, line_no, account_id, debit, credit) VALUES (?, ?, ?, ?, ?)",
            (journal_id, no, account_id, debit, credit),
        )
    return journal_id


def BAPI_GL_JOURNAL_POST(lines: list, reference: str = "") -> dict:
    """Post lines [{account_id, debit?, credit?}] using two-decimal currency amounts."""
    if not isinstance(lines, list):
        return bapi_error("Journal lines must be a list")
    try:
        parsed = []
        for line in lines:
            account_id = line["account_id"]
            if type(account_id) is not int:
                return bapi_error("Account IDs must be integers")
            parsed.append((account_id, _cents(line.get("debit", 0)), _cents(line.get("credit", 0))))
        with get_conn() as conn:
            journal_id = _post_journal(conn, parsed, reference, date.today().isoformat())
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return bapi_error(str(exc))
    return bapi_result(data={"journal_id": journal_id})


def BAPI_GL_JOURNAL_GETLIST(account_id: int = None, limit: int = 100, after_id: int = 0) -> dict:
    """List balanced journal entries, optionally those touching one account."""
    if error := page_args(limit, after_id):
        return bapi_error(error)
    with get_conn() as conn:
        query = "SELECT * FROM journal_entries WHERE journal_id > ?"
        params = [after_id]
        if account_id is not None:
            query += " AND journal_id IN (SELECT journal_id FROM journal_lines WHERE account_id = ?)"
            params.append(account_id)
        params.append(limit + 1)
        entries = rows_to_dicts(conn.execute(query + " ORDER BY journal_id LIMIT ?", params).fetchall())
        page_entries = entries[:limit]
        lines_by_journal = {entry["journal_id"]: [] for entry in page_entries}
        if page_entries:
            ids = list(lines_by_journal)
            for row in conn.execute(
                f"SELECT journal_id, line_no, account_id, debit, credit FROM journal_lines "
                f"WHERE journal_id IN ({','.join('?' for _ in ids)}) ORDER BY journal_id, line_no", ids
            ):
                lines_by_journal[row["journal_id"]].append({
                    **dict(row), "debit": row["debit"] / 100, "credit": row["credit"] / 100,
                })
        for entry in page_entries:
            entry["lines"] = lines_by_journal[entry["journal_id"]]
    return paged_result(entries, limit, "journal_id", lambda entry: entry)


def BAPI_GL_ACCOUNT_SUMMARY(start_date: str = None, end_date: str = None) -> dict:
    """Debits/credits from new journals plus historical signed posting balance."""
    for value in (start_date, end_date):
        if value is not None:
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError
            except (ValueError, TypeError):
                return bapi_error("Dates must be in YYYY-MM-DD format")
    if start_date and end_date and start_date > end_date:
        return bapi_error("start_date must not exceed end_date")
    with get_conn() as conn:
        data = []
        for account in conn.execute("SELECT * FROM gl_accounts ORDER BY account_id").fetchall():
            journal = conn.execute(
                "SELECT COALESCE(SUM(l.debit), 0), COALESCE(SUM(l.credit), 0) "
                "FROM journal_lines l JOIN journal_entries e USING (journal_id) "
                "WHERE l.account_id = ? AND (? IS NULL OR e.posting_date >= ?) "
                "AND (? IS NULL OR e.posting_date <= ?)",
                (account["account_id"], start_date, start_date, end_date, end_date),
            ).fetchone()
            legacy = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM gl_postings WHERE account_id = ? "
                "AND (? IS NULL OR posting_date >= ?) AND (? IS NULL OR posting_date <= ?)",
                (account["account_id"], start_date, start_date, end_date, end_date),
            ).fetchone()[0]
            data.append({**dict(account), "debits": journal[0] / 100,
                         "credits": journal[1] / 100, "legacy_balance": legacy,
                         "balance": legacy + (journal[0] - journal[1]) / 100})
    return bapi_result(data=data)


def BAPI_INCOMINGINVOICE_CREATE(vendor_id: int, amount: float, reference: str = "", due_date: str = None) -> dict:
    try:
        if _cents(amount) <= 0:
            return bapi_error("Invoice amount must be positive")
    except ValueError as exc:
        return bapi_error(str(exc))
    with get_conn() as conn:
        vendor = conn.execute("SELECT 1 FROM vendors WHERE vendor_id = ?", (vendor_id,)).fetchone()
        if not vendor:
            return bapi_error(f"Vendor {vendor_id} not found")
        cur = conn.execute(
            "INSERT INTO invoices (direction, party_id, reference, amount, status, due_date, invoice_date) "
            "VALUES ('AP', ?, ?, ?, 'OPEN', ?, ?)",
            (vendor_id, reference, amount, due_date, date.today().isoformat()),
        )
        invoice_id = cur.lastrowid
    return bapi_result(
        data={"invoice_id": invoice_id},
        messages=[{"type": "S", "message": f"AP invoice {invoice_id} posted"}],
    )


def BAPI_AP_PAYMENT_POST(invoice_id: int, amount: float, method: str = "TRANSFER") -> dict:
    """Make payment (vendor invoice)."""
    try:
        paid = _cents(amount)
    except ValueError as exc:
        return bapi_error(str(exc))
    with get_conn() as conn:
        invoice = conn.execute(
            "SELECT * FROM invoices WHERE invoice_id = ? AND direction = 'AP'", (invoice_id,)
        ).fetchone()
        if not invoice:
            return bapi_error(f"AP invoice {invoice_id} not found")
        if invoice["status"] == "PAID":
            return bapi_error(f"AP invoice {invoice_id} is already paid")
        try:
            due = _cents(invoice["amount"])
        except ValueError:
            return bapi_error("Invoice amount is invalid")
        if paid <= 0 or paid != due:
            return bapi_error("Payment must be positive and match the invoice amount")

        conn.execute(
            "INSERT INTO payments (invoice_id, amount, posted_date, method) VALUES (?, ?, ?, ?)",
            (invoice_id, amount, date.today().isoformat(), method),
        )
        conn.execute("UPDATE invoices SET status = 'PAID', paid_date = ? WHERE invoice_id = ?",
                     (date.today().isoformat(), invoice_id))

        ap_account = _gl_account_id(conn, "Accounts Payable")
        cash_account = _gl_account_id(conn, "Cash")
        ref = f"AP invoice {invoice_id}"
        _post_journal(conn, [(ap_account, paid, 0), (cash_account, 0, paid)],
                      ref, date.today().isoformat())
    return bapi_result(messages=[{"type": "S", "message": f"Payment posted for AP invoice {invoice_id}"}])


def BAPI_AR_INVOICE_CREATE(customer_id: int, amount: float, reference: str = "", due_date: str = None) -> dict:
    try:
        if _cents(amount) <= 0:
            return bapi_error("Invoice amount must be positive")
    except ValueError as exc:
        return bapi_error(str(exc))
    with get_conn() as conn:
        customer = conn.execute("SELECT 1 FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()
        if not customer:
            return bapi_error(f"Customer {customer_id} not found")
        cur = conn.execute(
            "INSERT INTO invoices (direction, party_id, reference, amount, status, due_date, invoice_date) "
            "VALUES ('AR', ?, ?, ?, 'OPEN', ?, ?)",
            (customer_id, reference, amount, due_date, date.today().isoformat()),
        )
        invoice_id = cur.lastrowid
    return bapi_result(
        data={"invoice_id": invoice_id},
        messages=[{"type": "S", "message": f"AR invoice {invoice_id} posted"}],
    )


def BAPI_AR_PAYMENT_POST(invoice_id: int, amount: float, method: str = "TRANSFER") -> dict:
    """Receive payment (customer invoice)."""
    try:
        paid = _cents(amount)
    except ValueError as exc:
        return bapi_error(str(exc))
    with get_conn() as conn:
        invoice = conn.execute(
            "SELECT * FROM invoices WHERE invoice_id = ? AND direction = 'AR'", (invoice_id,)
        ).fetchone()
        if not invoice:
            return bapi_error(f"AR invoice {invoice_id} not found")
        if invoice["status"] == "PAID":
            return bapi_error(f"AR invoice {invoice_id} is already paid")
        try:
            due = _cents(invoice["amount"])
        except ValueError:
            return bapi_error("Invoice amount is invalid")
        if paid <= 0 or paid != due:
            return bapi_error("Payment must be positive and match the invoice amount")

        conn.execute(
            "INSERT INTO payments (invoice_id, amount, posted_date, method) VALUES (?, ?, ?, ?)",
            (invoice_id, amount, date.today().isoformat(), method),
        )
        conn.execute("UPDATE invoices SET status = 'PAID', paid_date = ? WHERE invoice_id = ?",
                     (date.today().isoformat(), invoice_id))

        ar_account = _gl_account_id(conn, "Accounts Receivable")
        cash_account = _gl_account_id(conn, "Cash")
        ref = f"AR invoice {invoice_id}"
        _post_journal(conn, [(cash_account, paid, 0), (ar_account, 0, paid)],
                      ref, date.today().isoformat())
    return bapi_result(messages=[{"type": "S", "message": f"Payment received for AR invoice {invoice_id}"}])


def BAPI_GL_ACCOUNT_GETLIST() -> dict:
    summary = BAPI_GL_ACCOUNT_SUMMARY()
    return bapi_result(data=[{key: row[key] for key in ("account_id", "name", "account_type", "balance")}
                             for row in summary["DATA"]])
