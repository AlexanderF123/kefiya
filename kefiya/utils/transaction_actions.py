# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""The three things one does with a booking one is looking at.

In StarMoney a booking answers to a right-click: print it, forward the money,
mark it for later. All three were missing here -- a Bank Transaction could be
opened and read and that was the end of it.

  print     stays in the browser and needs nothing from this module
  forward   builds the beginning of a Kefiya Transfer from the booking
  mark      sets a follow-up flag on the booking

The follow-up flag is the one that has to survive a submitted document, and
"mark" is not an accounting statement: no amount, no account, no party is
touched by it, only a flag that says somebody wants to come back to this.
"""

import json

import frappe
from frappe import _
from frappe.utils import flt

#: SEPA gives the remittance information 140 characters. A purpose built from a
#: description has to be cut somewhere, and cutting it here beats having the
#: bank cut it or refuse the order.
PURPOSE_LIMIT = 140

FOLLOWUP_FIELD = "kefiya_followup"


def _names(names):
    """Accept one name, a JSON list from the browser, or a Python list."""
    if not names:
        return []
    if isinstance(names, str):
        stripped = names.strip()
        if stripped.startswith("["):
            try:
                names = json.loads(stripped)
            except ValueError:
                return [stripped]
        else:
            return [stripped]
    if isinstance(names, (list, tuple, set)):
        return [str(n) for n in names if n]
    return [str(names)]


@frappe.whitelist()
def set_followup(names, flagged=1):
    """Mark bookings for follow-up, or take the mark off again.

    :param names: one Bank Transaction name, or a list of them
    :param flagged: 1 to mark, 0 to clear
    :return: {"updated": int, "flagged": bool, "skipped": [...]}
    """
    flagged = 1 if str(flagged) not in ("0", "False", "false", "") else 0
    result = {"updated": 0, "flagged": bool(flagged), "skipped": []}

    if not frappe.get_meta("Bank Transaction").has_field(FOLLOWUP_FIELD):
        result["reason"] = _("The follow-up field is not installed.")
        return result

    for name in _names(names):
        # Whoever may not write the booking may not flag it either. Checked per
        # document: User Permissions can allow one company's bookings and not
        # another's, and a list action must not slip past that.
        frappe.has_permission("Bank Transaction", ptype="write", doc=name,
                              throw=True)
        current = frappe.db.get_value("Bank Transaction", name, FOLLOWUP_FIELD)
        if int(current or 0) == flagged:
            result["skipped"].append(name)
            continue
        # A submitted document: db_set is the documented way to change a field
        # on one. The field is allow_on_submit and carries no accounting value.
        frappe.get_doc("Bank Transaction", name).db_set(
            FOLLOWUP_FIELD, flagged, update_modified=False)
        result["updated"] += 1

    return result


def _login_for(bank_account):
    """The Kefiya Login that pays from this bank account, if there is one."""
    if not bank_account:
        return None
    rows = frappe.get_all(
        "Kefiya Login", filters={"bank_account": bank_account},
        fields=["name"], limit=1)
    return rows[0]["name"] if rows else None


@frappe.whitelist()
def transfer_from_transaction(name):
    """The beginning of a transfer, built from a booking.

    Money that arrived is money that can be passed on, and the booking already
    holds most of what the transfer needs. What it cannot know is where the
    money should go next: the counterparty of the original booking is offered
    as the starting point, because forwarding it back is a real case and
    typing an IBAN again is how digits get transposed. It is a suggestion in a
    draft, and every field of it can be overwritten before anything is sent.

    Nothing is created here. The caller receives values and opens a new,
    unsaved Kefiya Transfer with them.

    :param name: Bank Transaction name
    :return: dict with kefiya_login, company and one item
    """
    frappe.has_permission("Bank Transaction", ptype="read", doc=name,
                          throw=True)

    txn = frappe.get_doc("Bank Transaction", name)

    # Forwarding is about the money that came in. Where a booking only has an
    # outgoing amount, that is what there is to repeat.
    amount = flt(txn.get("deposit")) or flt(txn.get("withdrawal"))

    login = _login_for(txn.get("bank_account"))
    company = None
    if login:
        # The login knows the company; the booking does not always.
        company = frappe.db.get_value("Kefiya Login", login, "company")

    purpose = (txn.get("description") or "").strip()
    if txn.get("reference_number") and txn.get("reference_number") not in purpose:
        purpose = "{0} {1}".format(purpose, txn.get("reference_number")).strip()
    purpose = " ".join(purpose.split())[:PURPOSE_LIMIT]

    return {
        "source": name,
        "kefiya_login": login,
        "company": company,
        "amount": flt(amount),
        "item": {
            "recipient_name": (txn.get("bank_party_name") or "").strip(),
            "recipient_iban": (txn.get("bank_party_iban") or "").strip(),
            "amount": flt(amount),
            "purpose": purpose,
        },
    }
