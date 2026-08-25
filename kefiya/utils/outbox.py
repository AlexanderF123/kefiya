# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""The outgoing-payments page, as data.

The outbox is where an order stands between "entered" and "at the bank". Three
states, and they are not the same thing:

    draft (docstatus 0)        entered, not approved yet -- still changeable
    approved (docstatus 1)     amounts and recipients are fixed
    held back (on_hold)        approved, but deliberately not going out

This used to be a Server Script stored on one site, and two things about that
were wrong rather than merely inconvenient.

The first is the reason it is being read here now: it wrote the reasons an
order is not going out as German literals -- "Zurueckgestellt", "Faellig erst
am", "Empfaengerpruefung offen". Umlauts do not survive being typed into a
script editor by whoever is nearest, and there is nothing in a stored script
that notices. Here they are English source strings, translated in
translations/de.csv, where a test reads every one of them.

The second is that a page's data source living outside the app means the page
works on that site and nowhere else, and nothing in the app's tests can see
the dependency. The same reason payee_check.known_payees() exists.

Two things also got better on the way in, both because a Server Script cannot
do them: permissions are asked with frappe.has_permission instead of reading
DocPerm rows by hand, and which accounts may pay is asked of
account_kind.transfer_sources() instead of being reimplemented.
"""

import re

import frappe
from frappe import _

from kefiya.utils.account_kind import transfer_sources


def _blocked_reason(row, today):
    """Why this order is not going out today, in words.

    In words rather than as a flag, because "not sendable" is the answer to a
    question nobody asked: the person looking at the list wants to know what
    to DO about it, and "held back" and "due on the 3rd" call for opposite
    things.
    """
    if row["docstatus"] == 0:
        return _("Not approved yet")
    if row.get("on_hold"):
        return _("Held back")
    if row.get("status") == "Sent":
        return _("Already sent")
    if row.get("status") == "Scheduled at Bank":
        return _("With the bank until its date")
    if (row.get("manage_due_date") and row.get("execution_date")
            and str(row["execution_date"]) > today):
        return _("Not due until {0}").format(
            frappe.utils.formatdate(row["execution_date"]))
    if row.get("vop_pending"):
        return _("Payee verification still open")
    return ""


#: Document names as they appear inside a purpose line -- BT-0001,
#: KEF-TRF-2026-00001. The same rule the detail view uses; see
#: kefiya.DOCNAME_IN_TEXT in transfer_details.js. Deliberately narrow, because
#: a looser pattern matches the recipient's own invoice numbers and goes
#: looking for documents that are not ours.
DOCNAME_IN_TEXT = r"\b[A-Z]{2,8}(?:-[A-Z0-9]{2,6})*-\d{3,}\b"


def _referenced_documents(items, own_name):
    """Document names named in the purpose lines of one order."""
    found = []
    for item in items or []:
        for hit in re.findall(DOCNAME_IN_TEXT, str(item.get("purpose") or "")):
            if hit != own_name and hit not in found:
                found.append(hit)
    return found


def _receipt_counts(items_by, names):
    """How many receipts each order has, counting the ones it does not hold.

    Nobody attaches the travel expense PDF to the transfer. It is created on
    the Business Trip and stays there, and the transfer says "Reisekosten
    BT-0001" in its purpose. So the purpose is read, and the attachments of
    what it names are counted too -- a receipt that cannot be found from the
    payment is a receipt that gets asked for twice.

    One query for the whole page: asking per row would be a request per order
    to show a single number.
    """
    wanted = {}
    for name in names:
        for other in [name] + _referenced_documents(items_by.get(name), name):
            wanted.setdefault(other, []).append(name)

    if not wanted:
        return {}

    counts = {name: 0 for name in names}
    for row in frappe.get_all(
            "File", filters={"attached_to_name": ["in", list(wanted)]},
            fields=["attached_to_name"], limit_page_length=0):
        for owner in wanted.get(row["attached_to_name"], []):
            counts[owner] = counts.get(owner, 0) + 1
    return counts


@frappe.whitelist()
def outbox_data(q=None, show_sent=0):
    """Everything the outgoing-payments page shows.

    :param q: free-text filter over recipient, IBAN, reference, amount
    :param show_sent: include orders already handed to the bank
    :return: {"today", "rows", "payers", "can"}
    """
    frappe.has_permission("Kefiya Transfer", ptype="read", throw=True)

    q = (q or "").strip()
    show_sent = 1 if str(show_sent or "") in ("1", "true", "True") else 0

    filters = {"docstatus": ["<", 2]}
    if not show_sent:
        filters["status"] = ["!=", "Sent"]

    # get_list, not get_all: somebody who may not see an order must not find
    # it again inside a total at the bottom of the page.
    rows = frappe.get_list(
        "Kefiya Transfer", filters=filters,
        fields=["name", "kefiya_login", "company", "execution_date", "status",
                "docstatus", "total_amount", "payment_count", "on_hold",
                "instant_payment", "manage_due_date", "bank_reference",
                "vop_pending", "owner", "modified", "creation"],
        order_by='docstatus asc, ifnull(execution_date, "2999-12-31") asc,'
                 " creation asc",
        limit_page_length=0)

    names = [r["name"] for r in rows]
    items_by = {}
    if names:
        for item in frappe.get_all(
                "Kefiya Transfer Item", parent_doctype="Kefiya Transfer",
                filters={"parenttype": "Kefiya Transfer",
                         "parent": ["in", names], "parentfield": "items"},
                fields=["parent", "recipient_name", "recipient_iban",
                        "recipient_bic", "amount", "purpose", "own_account",
                        "idx"],
                order_by="parent, idx", limit_page_length=0):
            items_by.setdefault(item["parent"], []).append({
                "recipient_name": item.get("recipient_name"),
                "recipient_iban": item.get("recipient_iban"),
                "recipient_bic": item.get("recipient_bic"),
                "amount": frappe.utils.flt(item.get("amount")),
                "purpose": item.get("purpose"),
                "own_account": item.get("own_account"),
            })

    # The paying account hangs on the access. Without it the list would show a
    # login name, and that tells nobody which account is being debited.
    accounts = {row["name"]: row for row in frappe.get_list(
        "Kefiya Login", fields=["name", "bank_account", "company"],
        limit_page_length=0)}

    receipts = _receipt_counts(items_by, names)
    today = frappe.utils.today()

    out = []
    for row in rows:
        login = accounts.get(row["kefiya_login"]) or {}
        items = items_by.get(row["name"]) or []

        if q and not _matches(q, row, login, items):
            continue

        blocked = _blocked_reason(row, today)
        out.append({
            "name": row["name"],
            "kefiya_login": row["kefiya_login"],
            "bank_account": login.get("bank_account") or row["kefiya_login"],
            "company": row.get("company") or login.get("company"),
            "execution_date": (str(row["execution_date"])
                               if row.get("execution_date") else None),
            "manage_due_date": frappe.utils.cint(row.get("manage_due_date")),
            "instant_payment": frappe.utils.cint(row.get("instant_payment")),
            "status": row.get("status"),
            "docstatus": row["docstatus"],
            "on_hold": frappe.utils.cint(row.get("on_hold")),
            "vop_pending": frappe.utils.cint(row.get("vop_pending")),
            "bank_reference": row.get("bank_reference"),
            "total_amount": frappe.utils.flt(row.get("total_amount")),
            "payment_count": (frappe.utils.cint(row.get("payment_count"))
                              or len(items)),
            "owner": row.get("owner"),
            "modified": str(row.get("modified")),
            "items": items,
            "receipts": receipts.get(row["name"], 0),
            "referenced": _referenced_documents(items, row["name"]),
            "blocked": blocked,
            "sendable": 1 if (row["docstatus"] == 1 and not blocked) else 0,
        })

    return {
        "today": today, "q": q, "show_sent": show_sent, "rows": out,
        "payers": transfer_sources(),
        "can": {
            "submit": _may("submit"),
            "write": _may("write"),
            "create": _may("create"),
            "delete": _may("delete"),
        },
    }


def _matches(q, row, login, items):
    """Free text over everything a person would search this list by."""
    haystack = [row["name"], row.get("company") or "",
                login.get("bank_account") or "", row.get("status") or ""]
    for item in items:
        haystack += [item.get("recipient_name") or "",
                     item.get("recipient_iban") or "",
                     item.get("purpose") or "", str(item.get("amount") or "")]
    return q.lower() in " ".join(str(p) for p in haystack).lower()


def _may(action):
    """Whether the caller may do this to a transfer.

    Only what the page SHOWS is decided here. Every action is asked again at
    the endpoint that carries it out, so a hidden button is a courtesy and
    never the safeguard.
    """
    return 1 if frappe.has_permission("Kefiya Transfer", ptype=action) else 0
