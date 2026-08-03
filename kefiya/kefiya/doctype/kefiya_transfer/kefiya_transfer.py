# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Outgoing SEPA credit transfer with free recipient entry.

One document carries one or more payments. A single row is sent as an
individual transfer (HKCCS, or HKIPZ when instant), several rows go out as one
collective order (HKCCM) that the bank authorises with a single TAN.

Recipients are typed in rather than taken from a Payment Request, so the
document itself has to carry the safeguards that the invoice workflow would
otherwise provide:

* the IBAN is checksum-verified, because a typo silently pays a stranger;
* money only leaves after submit, and submit rights are separate from create
  rights, so the person entering a transfer is not the person releasing it;
* sending is a distinct, explicitly confirmed step -- submit alone moves
  nothing.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, now_datetime

from kefiya.utils import own_transfer


def normalize_iban(value):
    """Strip formatting and upper-case an IBAN."""
    return (value or "").replace(" ", "").replace("-", "").upper()


def is_valid_iban(value):
    """Validate an IBAN's ISO 7064 mod-97 checksum.

    With free recipient entry there is no invoice to check the account against,
    so the checksum is the only automatic defence against a mistyped IBAN
    reaching the bank.
    """
    iban = normalize_iban(value)
    if len(iban) < 15 or len(iban) > 34:
        return False
    if not iban[:2].isalpha() or not iban[2:4].isdigit():
        return False
    if not iban.isalnum():
        return False

    rearranged = iban[4:] + iban[:4]
    digits = ""
    for char in rearranged:
        if char.isdigit():
            digits += char
        elif char.isalpha():
            digits += str(ord(char) - 55)
        else:
            return False
    try:
        return int(digits) % 97 == 1
    except ValueError:
        return False


class KefiyaTransfer(Document):
    def validate(self):
        if not self.items:
            frappe.throw(_("Add at least one payment."))

        total = 0
        for row in self.items:
            # A row that names one of our own accounts takes its IBAN from
            # there. Filled on the server too, not only in the form: a row can
            # arrive from an import or another script that never opened one.
            own_transfer.fill_from_own_account(row)

            row.recipient_iban = normalize_iban(row.recipient_iban)
            if not is_valid_iban(row.recipient_iban):
                frappe.throw(_(
                    "Row {0}: {1} is not a valid IBAN (checksum failed)."
                ).format(row.idx, row.recipient_iban or "-"))

            if row.recipient_bic:
                row.recipient_bic = (row.recipient_bic or "").replace(
                    " ", "").upper()

            if flt(row.amount) <= 0:
                frappe.throw(_(
                    "Row {0}: amount must be greater than zero."
                ).format(row.idx))

            # The SEPA purpose field is capped at 140 characters; truncate here
            # rather than letting the bank reject the whole order.
            if row.purpose:
                row.purpose = row.purpose[:140]

            total += flt(row.amount)

        self.total_amount = total
        self.payment_count = len(self.items)

        # Paying the account the money is drawn from. The bank refuses it as
        # well -- but only after the order went out and a TAN was spent on it.
        own_transfer.refuse_paying_yourself(self)

        if not self.execution_date:
            self.execution_date = now_datetime().date()

        if getdate(self.execution_date) > now_datetime().date():
            if cint(self.instant_payment):
                # A real-time transfer is executed within seconds. A date on it
                # is a contradiction, and no bank offers the combination.
                frappe.throw(_(
                    "An instant payment is executed immediately and cannot"
                    " carry a future execution date."
                ))
        elif not cint(self.manage_due_date):
            # Nothing to hand over: a bank cannot file an order for today or
            # for a day gone by. Silently correcting this is better than an
            # error, because the outcome the user wants -- pay it -- is the
            # same either way.
            self.manage_due_date = 1

        if not self.company and self.kefiya_login:
            self.company = frappe.db.get_value(
                "Kefiya Login", self.kefiya_login, "company")

    def before_submit(self):
        # Submitting approves the transfer; it does not send it. Sending is a
        # separate, explicitly confirmed action so an approval can never move
        # money as a side effect.
        self.status = "On Hold" if self.on_hold else "Approved"
        for row in self.items:
            if not row.end_to_end_id:
                row.end_to_end_id = "{0}-{1}".format(self.name, row.idx)[:35]

    @frappe.whitelist()
    def set_hold(self, on_hold):
        """Hold an approved order back, or release it again.

        Holding changes when an order is sent, never what it says -- amounts
        and recipients stay locked by the submit. That is why this is allowed
        after approval while everything else on the document is not.
        """
        # A whitelisted document method is callable by anyone who may read the
        # document. Releasing a held-back order makes it eligible for the next
        # collective send, so it needs the same right as sending itself.
        frappe.has_permission(
            "Kefiya Transfer", ptype="submit", doc=self, throw=True)

        if self.docstatus != 1:
            frappe.throw(_("Only approved transfers can be held back."))
        if self.status == "Sent":
            frappe.throw(_("This transfer was already sent."))

        on_hold = 1 if cint(on_hold) else 0
        self.db_set("on_hold", on_hold)
        self.db_set("status", "On Hold" if on_hold else "Approved")
        return {"status": self.status, "on_hold": on_hold}

    def on_cancel(self):
        if self.status == "Sent":
            frappe.throw(_(
                "This transfer was already sent to the bank and cannot be"
                " cancelled here. Recall it with your bank if needed."
            ))
        self.status = "Draft"

    def build_pain001(self):
        """Render this document as a pain.001.001.03 credit-transfer message.

        Returns (xml, control_sum, count).
        """
        return build_pain001_for([self])


def build_pain001_for(docs):
    """Render one or more Kefiya Transfers as a single pain.001 message.

    Several documents collapse into one collective order (HKCCM) that the bank
    authorises with a single TAN -- the point of the outbox. They must all be
    paid from the same account, since one message carries exactly one debtor.

    Returns (xml, control_sum, count). The control sum is what the bank checks
    a collective order against, so it is summed from the very rows that go into
    the message rather than from stored totals that could have drifted.
    """
    from sepaxml import SepaTransfer

    if not docs:
        frappe.throw(_("No transfers to send."))

    logins = {doc.kefiya_login for doc in docs}
    if len(logins) > 1:
        frappe.throw(_(
            "All selected transfers must be paid from the same account."
            " Found: {0}"
        ).format(", ".join(sorted(logins))))

    rows = []
    for doc in docs:
        for row in doc.items:
            rows.append((doc, row))
    if not rows:
        frappe.throw(_("The selected transfers contain no payments."))

    first = docs[0]
    login = frappe.get_doc("Kefiya Login", first.kefiya_login)
    bank_account = login.bank_account
    if not bank_account:
        frappe.throw(_("Kefiya Login {0} has no bank account.").format(
            first.kefiya_login))

    company_bank = frappe.get_doc("Bank Account", bank_account)
    debtor_iban = normalize_iban(company_bank.iban)
    if not debtor_iban:
        frappe.throw(_("Bank account {0} has no IBAN.").format(bank_account))

    company = first.company or login.company
    company_name = frappe.get_cached_value(
        "Company", company, "company_name") or company or ""

    config = {
        "name": (company_name or "")[:70],
        "currency": "EUR",
        "IBAN": debtor_iban,
        # A collective order is a batch; a single payment is not.
        "batch": len(rows) > 1,
    }
    if company_bank.branch_code:
        config["BIC"] = (company_bank.branch_code or "").replace(
            " ", "").upper()

    # clean=False keeps the text exactly as entered, so the XSD validation
    # below is what catches out-of-spec characters instead of silently
    # rewriting a recipient name.
    sepa = SepaTransfer(config, schema="pain.001.001.03", clean=False)

    control_sum = 0
    for doc, row in rows:
        amount_cents = int(round(flt(row.amount) * 100))
        if amount_cents <= 0:
            frappe.throw(_(
                "{0} row {1}: amount must be greater than zero."
            ).format(doc.name, row.idx))
        payment = {
            "name": (row.recipient_name or "")[:70],
            "IBAN": normalize_iban(row.recipient_iban),
            "amount": amount_cents,
            "description": (row.purpose or doc.name)[:140],
            "execution_date": getdate(
                doc.execution_date or now_datetime().date()),
            "endtoend_id": (row.end_to_end_id
                            or "{0}-{1}".format(doc.name, row.idx))[:35],
        }
        if row.recipient_bic:
            payment["BIC"] = row.recipient_bic
        sepa.add_payment(payment)
        control_sum += amount_cents

    try:
        xml = sepa.export(validate=True)
    except Exception as exc:
        frappe.throw(_(
            "Generated SEPA XML failed schema validation: {0}"
        ).format(exc))

    if isinstance(xml, bytes):
        xml = xml.decode("utf-8")
    return xml, control_sum / 100.0, len(rows)
