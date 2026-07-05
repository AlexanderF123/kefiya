# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

import inspect
import unittest

import frappe
from frappe.model.base_document import get_controller


class TestFinTSCompat(unittest.TestCase):
    def test_bank_transaction_controller_has_get_rounded(self):
        """Regression for the statement-import outage.

        When the ALYF ``banking`` app is installed it registers a
        ``before_submit`` doc-event that calls ``doc.get_rounded(...)`` -- a
        method defined on banking's Bank Transaction subclass. Kefiya's override
        wins as the resolved controller, so it MUST inherit that method (by
        extending banking's class) or every ``bank_transaction.insert()`` fails
        with ``AttributeError`` and no transactions are imported.
        """
        if "banking" not in frappe.get_installed_apps():
            self.skipTest("banking app not installed")
        controller = get_controller("Bank Transaction")
        self.assertTrue(
            hasattr(controller, "get_rounded"),
            "Bank Transaction controller must expose get_rounded when the "
            "banking app is installed (kefiya/overrides/bank_transaction).",
        )

    def test_to_jsonable_stringifies_unknown_objects(self):
        """The FinTS fetch wrappers serialise varied library objects best-effort;
        unknown objects must degrade to a string instead of breaking JSON."""
        from kefiya.utils.fints_controller import _to_jsonable

        class _Weird:
            def __repr__(self):
                return "weird-object"

        out = _to_jsonable({"num": 3, "obj": _Weird(), "nested": [_Weird()]})
        self.assertEqual(out["num"], 3)
        self.assertEqual(out["obj"], "weird-object")
        self.assertEqual(out["nested"], ["weird-object"])


class TestMoneyEndpointPermissions(unittest.TestCase):
    """Regression for the review finding "payments can be changed by anyone
    without a permission check".

    Every whitelisted endpoint that moves money or mutates a payment/booking
    MUST perform an explicit ``frappe.has_permission(..., throw=True)`` gate,
    because ``@frappe.whitelist()`` alone makes a method callable by *any*
    logged-in user regardless of DocType permissions.
    """

    # endpoint -> DocType it must guard
    GUARDED_ENDPOINTS = {
        "submit_payment_request_via_fints": "Payment Request",
        "send_transfer_tan": "Kefiya Login",
        "create_payment_entry": "Bank Transaction",
        "add_payment_reference": "Payment Entry",
        "auto_assign_payments": "Payment Entry",
        "change_match_against": "Kefiya Settings",
    }

    def test_endpoints_are_whitelisted(self):
        from kefiya.utils import client

        for name in self.GUARDED_ENDPOINTS:
            fn = getattr(client, name)
            self.assertTrue(
                getattr(fn, "__func__", fn) in frappe.whitelisted
                or fn in frappe.whitelisted,
                f"{name} is expected to be a whitelisted endpoint",
            )

    def test_money_endpoints_have_permission_gate(self):
        from kefiya.utils import client

        for name, doctype in self.GUARDED_ENDPOINTS.items():
            src = inspect.getsource(getattr(client, name))
            self.assertIn(
                "has_permission",
                src,
                f"{name} must call frappe.has_permission before acting",
            )
            self.assertIn(
                "throw=True",
                src,
                f"{name}'s permission check must throw (deny) on failure",
            )
            self.assertIn(
                doctype,
                src,
                f"{name} must guard the {doctype} DocType",
            )

    def test_transfer_needs_explicit_confirmation(self):
        """The money-out endpoint must refuse to send before the confirmation
        gate (and before any permission/DB access), so a stray call can never
        move money by default."""
        from kefiya.utils import client

        res = client.submit_payment_request_via_fints(
            payment_request_name="does-not-matter",
            user_scope="does-not-matter",
            confirmed=0,
        )
        self.assertEqual(res.get("status"), "error")
        self.assertIn("confirm", (res.get("message") or "").lower())
