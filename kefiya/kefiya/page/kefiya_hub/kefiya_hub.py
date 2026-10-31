# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import add_days, getdate, nowdate
from frappe.utils.scheduler import is_scheduler_inactive

# A login that has not imported for this many days needs attention
STALE_IMPORT_DAYS = 3


@frappe.whitelist()
def get_overview(company=None):
    """Collect the status of every Kefiya step for the Kefiya page."""
    login_filters = {"company": company} if company else {}
    logins = frappe.get_list(
        "Kefiya Login",
        filters=login_filters,
        fields=[
            "name", "company", "bank_account", "account_iban",
            "erpnext_account", "failed_connection", "tan_state_updated",
            "enable_tan_authentication", "bank_logo", "modified",
        ],
        order_by="login_name asc",
    )
    # only whether a connection state is stored, never the state itself
    with_state = set(frappe.get_list(
        "Kefiya Login",
        filters={**login_filters, "stored_client_state": ["is", "set"]},
        pluck="name",
    ))

    schedule = get_schedule_items()
    last_imports = get_last_imports([d.name for d in logins])
    open_transactions = get_open_transactions(company)

    for login in logins:
        login.has_client_state = login.name in with_state
        login.schedule = schedule.get(login.name)
        login.last_import = last_imports.get(login.name)
        login.open_transactions = open_transactions.get(login.bank_account, {})
        login.import_stale = is_import_stale(login)
        login.status = get_login_status(login)

    return {
        "logins": logins,
        "recent_imports": get_recent_imports(company),
        "bank_accounts": get_bank_account_summary(company, open_transactions),
        "scheduler_active": not is_scheduler_inactive(),
        "steps": get_steps(logins, open_transactions),
    }


@frappe.whitelist()
def record_failed_connection(kefiya_login):
    """Count a failed bank connection, as the Kefiya Login form does.

    The FinTS controller resets the counter on the next successful
    connection. Written with db.set_value, because the server already saved
    the login while connecting and a full save would overwrite that.
    """
    login = frappe.get_doc("Kefiya Login", kefiya_login)
    login.check_permission("write")
    failed = (login.failed_connection or 0) + 1
    frappe.db.set_value("Kefiya Login", login.name, {
        "failed_connection": failed,
        "account_iban": None,
    })
    return failed


def get_login_status(login):
    if login.failed_connection:
        return "error"
    if not login.bank_account or login.import_stale:
        return "warning"
    return "ok"


def is_import_stale(login):
    last_date = login.last_import and login.last_import.get("to_date")
    return not last_date or getdate(last_date) < getdate(
        add_days(nowdate(), -STALE_IMPORT_DAYS)
    )


def get_schedule_items():
    items = frappe.get_all(
        "Kefiya Schedule Item",
        filters={"parent": "Kefiya Schedule"},
        fields=["kefiya_login", "import_frequency", "active", "hour"],
    )
    return {d.kefiya_login: d for d in items}


def get_last_imports(login_names):
    if not login_names:
        return {}
    imports = frappe.get_all(
        "Kefiya Import",
        filters={"kefiya_login": ["in", login_names], "docstatus": 1},
        fields=["name", "kefiya_login", "from_date", "to_date", "creation"],
        order_by="creation desc",
    )
    last = {}
    for d in imports:
        last.setdefault(d.kefiya_login, d)
    return last


def get_recent_imports(company=None):
    filters = {"docstatus": ["<", 2]}
    if company:
        filters["kefiya_login"] = [
            "in",
            frappe.get_all(
                "Kefiya Login", filters={"company": company}, pluck="name"
            ),
        ]
    fints = frappe.get_list(
        "Kefiya Import",
        filters=filters,
        fields=["name", "kefiya_login", "from_date", "to_date", "creation",
                "docstatus"],
        order_by="creation desc",
        limit=5,
    )
    for d in fints:
        d.source = "FinTS"

    # Only System Managers may read statement imports; everyone else still
    # gets the page, just without them
    if not frappe.has_permission("Kefiya Bank Statement Import", "read"):
        return fints

    statement_filters = {"company": company} if company else {}
    statements = frappe.get_list(
        "Kefiya Bank Statement Import",
        filters=statement_filters,
        fields=["name", "bank_account", "status", "payload_count",
                "imported_records", "creation"],
        order_by="creation desc",
        limit=5,
    )
    for d in statements:
        d.source = "Statement"

    return sorted(fints + statements, key=lambda d: d.creation,
                  reverse=True)[:8]


def get_open_transactions(company=None):
    """Unreconciled bank transactions grouped by bank account."""
    filters = {"docstatus": 1, "status": "Unreconciled"}
    if company:
        filters["company"] = company
    rows = frappe.get_list(
        "Bank Transaction",
        filters=filters,
        fields=["bank_account", "count(name) as count",
                "sum(unallocated_amount) as amount", "min(date) as oldest",
                "currency"],
        group_by="bank_account, currency",
    )
    return {d.bank_account: d for d in rows}


def get_bank_account_summary(company, open_transactions):
    filters = {"is_company_account": 1}
    if company:
        filters["company"] = company
    accounts = frappe.get_list(
        "Bank Account",
        filters=filters,
        fields=["name", "account_name", "bank", "iban", "company"],
    )
    linked = set(
        frappe.get_all("Kefiya Login", filters={"bank_account": ["is", "set"]},
                       pluck="bank_account")
    )
    for account in accounts:
        account.has_login = account.name in linked
        account.open = open_transactions.get(account.name, {})
    return accounts


def get_steps(logins, open_transactions):
    connect = "todo" if not logins else (
        "error" if any(d.failed_connection for d in logins) else "done")
    link = "todo" if not logins else (
        "warning" if any(not d.bank_account for d in logins) else "done")
    imported = "todo" if not any(d.last_import for d in logins) else (
        "warning" if any(d.import_stale and d.bank_account
                         for d in logins) else "done")
    open_count = sum(d.count for d in open_transactions.values())
    reconcile = "warning" if open_count else "done"
    return {
        "connect": connect,
        "link": link,
        "import": imported,
        "reconcile": reconcile,
        "open_count": open_count,
    }
