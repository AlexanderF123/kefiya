# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class KefiyaAutoReplyRule(Document):
    def validate(self):
        self._validate_guardrails()
        self._validate_uniqueness()

    def _validate_guardrails(self):
        if cint(self.response_time_days) < 0:
            frappe.throw(_("Reaktionszeit (Tage) darf nicht negativ sein."))
        if cint(self.daily_limit) <= 0:
            frappe.throw(
                _(
                    "Tageslimit muss größer als 0 sein — die Leitplanke darf "
                    "nicht abgeschaltet werden."
                )
            )
        if cint(self.cooldown_days) < 0:
            frappe.throw(_("Cooldown ohne Vorgang (Tage) darf nicht negativ sein."))

    def _validate_uniqueness(self):
        """One rule per (email account, Vorgangstyp) — otherwise the same
        incoming mail would be acknowledged by two rules."""
        duplicate = frappe.db.exists(
            "Kefiya AutoReply Rule",
            {
                "name": ("!=", self.name),
                "email_account": self.email_account,
                "reference_doctype": self.reference_doctype or "",
            },
        )
        if duplicate:
            frappe.throw(
                _(
                    "Für dieses Postfach und diesen Vorgangstyp existiert bereits "
                    "die Regel {0}."
                ).format(duplicate)
            )
