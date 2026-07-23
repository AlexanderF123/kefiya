# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

import unittest

import frappe

from kefiya.permissions import bank

STRANGER = "someone.else@example.com"
ALLOWED = next(iter(bank.ALLOWED_USERS))


class TestBankPrivacyPermissions(unittest.TestCase):
    """The private-account filter must exclude flagged accounts for
    everyone outside the allowlist and stay inert for allowed users."""

    def test_allowed_users_get_no_filter(self):
        for user in (ALLOWED, "Administrator"):
            self.assertEqual(bank.bank_account_query_conditions(user), "")
            self.assertEqual(bank.bank_transaction_query_conditions(user), "")

    def test_stranger_gets_privacy_filter(self):
        if not bank.privacy_field_exists():
            self.skipTest("custom_is_private not created yet (run migrate)")
        for condition in (
            bank.bank_account_query_conditions(STRANGER),
            bank.bank_transaction_query_conditions(STRANGER),
        ):
            self.assertIn(bank.PRIVATE_FIELD, condition)
            # Accounts without the flag set must remain visible.
            self.assertIn("coalesce", condition)

    def test_direct_access_to_private_account_denied(self):
        doc = frappe._dict({bank.PRIVATE_FIELD: 1})
        self.assertIs(
            bank.bank_account_has_permission(doc, user=STRANGER), False
        )
        # Allowed user and Administrator: no opinion -> role permissions apply.
        self.assertIsNone(bank.bank_account_has_permission(doc, user=ALLOWED))
        self.assertIsNone(
            bank.bank_account_has_permission(doc, user="Administrator")
        )

    def test_direct_access_to_public_account_untouched(self):
        for doc in (frappe._dict(), frappe._dict({bank.PRIVATE_FIELD: 0})):
            self.assertIsNone(
                bank.bank_account_has_permission(doc, user=STRANGER)
            )

    def test_transaction_without_account_untouched(self):
        doc = frappe._dict({"bank_account": None})
        self.assertIsNone(
            bank.bank_transaction_has_permission(doc, user=STRANGER)
        )
