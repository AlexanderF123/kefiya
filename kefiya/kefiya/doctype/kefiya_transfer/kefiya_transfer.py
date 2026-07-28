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
from frappe.utils import flt, getdate, now_datetime


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

        if not self.execution_date:
            self.execution_date = now_datetime().date()

        if not self.company and self.kefiya_login:
            self.company = frappe.db.get_value(
                "Kefiya Login", self.kefiya_login, "company")

    def before_submit(self):
        # Submitting approves the transfer; it does not send it. Sending is a
        # separate, explicitly confirmed action so an approval can never move
        # money as a side effect.
        self.status = "Approved"
        for row in self.items:
            if not row.end_to_end_id:
                row.end_to_end_id = "{0}-{1}".format(self.name, row.idx)[:35]

    def on_cancel(self):
        if self.status == "Sent":
            frappe.throw(_(
                "This transfer was already sent to the bank and cannot be"
                " cancelled here. Recall it with your bank if needed."
            ))
        self.status = "Draft"

    def build_pain001(self):
        """Render this document as a pain.001.001.03 credit-transfer message.

        Returns (xml, control_sum, count). The control sum is what the bank
        checks a collective order against, so it is derived from the same rows
        that go into the message rather than from the stored total.
        """
        from sepaxml import SepaTransfer

        login = frappe.get_doc("Kefiya Login", self.kefiya_login)
        bank_account = login.bank_account
        if not bank_account:
            frappe.throw(_("Kefiya Login {0} has no bank account.").format(
                self.kefiya_login))

        company_bank = frappe.get_doc("Bank Account", bank_account)
        debtor_iban = normalize_iban(company_bank.iban)
        if not debtor_iban:
            frappe.throw(_("Bank account {0} has no IBAN.").format(
                bank_account))

        company_name = frappe.get_cached_value(
            "Company", self.company, "company_name") or self.company or ""

        config = {
            "name": (company_name or self.company or "")[:70],
            "currency": "EUR",
            "IBAN": debtor_iban,
            # A collective order is a batch; a single payment is not.
            "batch": len(self.items) > 1,
        }
        if company_bank.branch_code:
            config["BIC"] = (company_bank.branch_code or "").replace(
                " ", "").upper()

        # clean=False keeps the text exactly as entered, so the XSD validation
        # below is what catches out-of-spec characters instead of silently
        # rewriting a recipient name.
        sepa = SepaTransfer(config, schema="pain.001.001.03", clean=False)

        control_sum = 0
        execution_date = getdate(self.execution_date or now_datetime().date())
        for row in self.items:
            amount_cents = int(round(flt(row.amount) * 100))
            if amount_cents <= 0:
                frappe.throw(_(
                    "Row {0}: amount must be greater than zero."
                ).format(row.idx))
            payment = {
                "name": (row.recipient_name or "")[:70],
                "IBAN": normalize_iban(row.recipient_iban),
                "amount": amount_cents,
                "description": (row.purpose or self.name)[:140],
                "execution_date": execution_date,
                "endtoend_id": (row.end_to_end_id
                                or "{0}-{1}".format(self.name, row.idx))[:35],
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
        return xml, control_sum / 100.0, len(self.items)
