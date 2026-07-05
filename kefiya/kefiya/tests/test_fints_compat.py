# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

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
