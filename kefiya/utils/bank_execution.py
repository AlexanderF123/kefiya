# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Write down what the bank has executed on its own.

Two kinds of order are carried out by the bank without kefiya taking part on
the day, and so far nothing ever recorded that they ran:

* A dated transfer handed to the bank stays "Scheduled at Bank" for good. The
  outgoing payments hide only "Sent", so an order paid weeks ago kept standing
  there as if it were still waiting.
* A standing order the bank keeps (execution_mode "Bank") kept its next
  execution date in the past: only orders kept HERE moved on, because only
  for them does kefiya place a transfer (standing_order_execute.move_on).

Both are settled here from the account statement -- the bank is the referee,
not kefiya's own records. Which debit belongs to which order is decided in
bank_execution_match, without frappe; this module only reads and writes.

Runs after every statement import and once a day. Both are idempotent: an
order already settled is no longer open, and a debit that settled something
is not handed out again in the same run.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, nowdate

from kefiya.utils import bank_execution_match as match

TRANSFER = "Kefiya Transfer"
TRANSFER_ITEM = "Kefiya Transfer Item"
STANDING_ORDER = "Kefiya Standing Order"
SCHEDULED = "Scheduled at Bank"
SENT = "Sent"

#: A standing order that missed several runs is moved on once per run found,
#: never more often than this in one go.
MAX_CYCLES = 12

LOG_TITLE = "Kefiya: execution by the bank not recorded"


def settle_executed(bank_account=None):
    """Settle what the statement shows as executed -- one account, or all.

    Scheduler entry point (daily) and called after each import. Never raises:
    a failure on one account is logged and the next one is tried.
    """
    today = getdate(nowdate())
    for account in _accounts_with_open_orders(bank_account, today):
        try:
            _settle_account(account, today)
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()
            frappe.log_error(title=LOG_TITLE,
                             message="{0}\n\n{1}".format(
                                 account, frappe.get_traceback()))


def _latest_due(today):
    # A debit may come up to DAYS_BEFORE ahead of its date; an order due
    # later than that cannot have been executed yet.
    return add_days(today, match.DAYS_BEFORE)


def _logins_of(account):
    return frappe.get_all("Kefiya Login", filters={"bank_account": account},
                          pluck="name")


def _open_transfers(account, today):
    logins = _logins_of(account)
    if not logins:
        return []
    return frappe.get_all(
        TRANSFER,
        filters={"docstatus": 1, "status": SCHEDULED,
                 "kefiya_login": ("in", logins),
                 "execution_date": ("<=", _latest_due(today))},
        fields=["name", "execution_date", "total_amount"])


def _open_standing_orders(account, today):
    return frappe.get_all(
        STANDING_ORDER,
        filters={"execution_mode": "Bank", "status": "Active",
                 "bank_account": account,
                 "next_execution_date": ("<=", _latest_due(today))},
        fields=["name", "next_execution_date", "amount",
                "counterparty_iban", "purpose"])


def _accounts_with_open_orders(bank_account, today):
    accounts = set()
    transfers = frappe.get_all(
        TRANSFER,
        filters={"docstatus": 1, "status": SCHEDULED,
                 "execution_date": ("<=", _latest_due(today))},
        fields=["kefiya_login"])
    for row in transfers:
        account = frappe.db.get_value("Kefiya Login", row.kefiya_login,
                                      "bank_account")
        if account:
            accounts.add(account)
    for row in frappe.get_all(
            STANDING_ORDER,
            filters={"execution_mode": "Bank", "status": "Active",
                     "next_execution_date": ("<=", _latest_due(today))},
            fields=["bank_account"]):
        if row.bank_account:
            accounts.add(row.bank_account)
    if bank_account:
        return [bank_account] if bank_account in accounts else []
    return sorted(accounts)


def _debits(account, since, today):
    return [dict(row) for row in frappe.get_all(
        "Bank Transaction",
        filters={"bank_account": account, "docstatus": 1,
                 "withdrawal": (">", 0),
                 "date": ("between", [since, today])},
        fields=["name", "date", "withdrawal", "bank_party_iban",
                "description", "reference_number"],
        order_by="date asc, name asc")]


def _taken():
    """Debits already recorded as some standing order's execution."""
    return set(frappe.get_all(
        STANDING_ORDER,
        filters={"last_bank_transaction": ("is", "set")},
        pluck="last_bank_transaction"))


def _settle_account(account, today):
    transfers = _open_transfers(account, today)
    orders = _open_standing_orders(account, today)
    if not transfers and not orders:
        return

    dues = [getdate(t.execution_date) for t in transfers if t.execution_date]
    dues += [getdate(o.next_execution_date) for o in orders]
    if not dues:
        return
    since = add_days(min(dues), -match.DAYS_BEFORE)
    txns = _debits(account, since, today)
    if not txns:
        return

    taken = _taken()
    items = _transfer_items([t.name for t in transfers])

    payments = []
    for transfer in transfers:
        for item in items.get(transfer.name, []):
            payments.append({
                "key": ("T", transfer.name, item.idx),
                "iban": item.recipient_iban, "amount": item.amount,
                "purpose": item.purpose,
                "end_to_end_id": item.end_to_end_id,
                "due": transfer.execution_date})
    for order in orders:
        payments.append(_standing_payment(order))

    found = match.assign(payments, txns, taken)
    for txn in found.values():
        taken.add(txn.get("name"))

    for transfer in transfers:
        rows = items.get(transfer.name, [])
        executed = [found.get(("T", transfer.name, row.idx)) for row in rows]
        if rows and all(executed):
            _mark_transfer_executed(transfer.name, executed)
            continue
        if len(rows) > 1 and not any(executed):
            batch = match.batch_booking(transfer.name, transfer.total_amount,
                                        transfer.execution_date, txns, taken)
            if batch:
                taken.add(batch.get("name"))
                _mark_transfer_executed(transfer.name, [batch])

    for order in orders:
        txn = found.get(("S", order.name))
        if txn:
            _move_standing_order_on(order.name, txn, txns, taken, today)


def _transfer_items(names):
    if not names:
        return {}
    by_parent = {}
    for row in frappe.get_all(
            TRANSFER_ITEM,
            filters={"parent": ("in", names), "parenttype": TRANSFER},
            fields=["parent", "idx", "recipient_iban", "amount", "purpose",
                    "end_to_end_id"],
            order_by="idx asc",
            parent_doctype=TRANSFER):
        by_parent.setdefault(row.parent, []).append(row)
    return by_parent


def _standing_payment(order):
    return {"key": ("S", order.name), "iban": order.counterparty_iban,
            "amount": order.amount, "purpose": order.purpose,
            "end_to_end_id": None, "due": order.next_execution_date}


def _mark_transfer_executed(name, txns):
    """"Sent" is what takes an order out of the outgoing payments.

    Written with db_set: the status is all that changes, and nothing the
    document's hooks guard -- dates, amounts, recipients -- is touched.
    """
    doc = frappe.get_doc(TRANSFER, name)
    if doc.status != SCHEDULED:
        return
    doc.db_set("status", SENT)
    booked = max(getdate(t.get("date")) for t in txns)
    doc.add_comment("Comment", _(
        "Executed by the bank: debited on {0} ({1})."
    ).format(frappe.utils.formatdate(booked),
             ", ".join(t.get("name") for t in txns)))


def _move_standing_order_on(name, txn, txns, taken, today):
    """Record one run and move the order to its next date.

    The next date is not computed here: validate() works it out from
    last_executed_for, exactly as for an order kept here. If the order missed
    more than one run, the following ones are looked for too.
    """
    for _cycle in range(MAX_CYCLES):
        order = frappe.get_doc(STANDING_ORDER, name)
        due = order.next_execution_date
        if not due:
            return
        order.last_executed_for = str(due)
        order.last_bank_transaction = txn.get("name")
        booked = getdate(txn.get("date"))
        if not order.last_seen or getdate(order.last_seen) < booked:
            order.last_seen = booked
        if not order.first_seen:
            order.first_seen = booked
        order.occurrences = cint(order.occurrences) + 1
        try:
            order.save(ignore_permissions=True)
        except Exception:
            frappe.log_error(title=LOG_TITLE,
                             message="{0}\n\n{1}".format(
                                 name, frappe.get_traceback()),
                             reference_doctype=STANDING_ORDER,
                             reference_name=name)
            return

        following = order.next_execution_date
        if (not following or getdate(following) <= getdate(due)
                or getdate(following) > _latest_due(today)):
            return
        payment = _standing_payment(order)
        txn = match.assign([payment], txns, taken).get(payment["key"])
        if not txn:
            return
        taken.add(txn.get("name"))
