# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""A Payment Entry made from a booking moves money at the bank's rate.

Example throughout: a company that books in EUR, a bank account in CHF, and
the bank's statement saying 1 EUR = 0.94 CHF for the conversion it did.
"""

import os
import unittest

from kefiya.utils.bank_exchange_rate import FIELDS, payment_entry_values

EUR_CHF = {"from": "EUR", "to": "CHF", "rate": 0.94}


class TestTwoCurrenciesOneRate(unittest.TestCase):

    def test_a_euro_customer_paying_into_the_franc_account(self):
        values = payment_entry_values("Receive", 940.0, "CHF", "EUR", "EUR",
                                      EUR_CHF)
        self.assertAlmostEqual(values["paid_amount"], 1000.0)
        self.assertEqual(values["received_amount"], 940.0)
        self.assertEqual(values["source_exchange_rate"], 1.0)
        self.assertAlmostEqual(values["target_exchange_rate"], 1 / 0.94)

    def test_paying_a_euro_supplier_from_the_franc_account(self):
        values = payment_entry_values("Pay", 470.0, "CHF", "EUR", "EUR",
                                      EUR_CHF)
        self.assertEqual(values["paid_amount"], 470.0)
        self.assertAlmostEqual(values["received_amount"], 500.0)
        self.assertAlmostEqual(values["source_exchange_rate"], 1 / 0.94)
        self.assertEqual(values["target_exchange_rate"], 1.0)

    def test_a_franc_customer_paying_into_the_franc_account(self):
        values = payment_entry_values("Receive", 940.0, "CHF", "CHF", "EUR",
                                      EUR_CHF)
        self.assertEqual(values["paid_amount"], 940.0)
        self.assertAlmostEqual(values["source_exchange_rate"], 1 / 0.94)
        self.assertAlmostEqual(values["target_exchange_rate"], 1 / 0.94)

    def test_both_sides_agree_in_the_company_currency(self):
        """What makes the entry balance: no gain or loss nobody had."""
        for payment_type in ("Receive", "Pay"):
            for party in ("EUR", "CHF"):
                v = payment_entry_values(payment_type, 1234.56, "CHF", party,
                                         "EUR", EUR_CHF)
                self.assertAlmostEqual(
                    v["paid_amount"] * v["source_exchange_rate"],
                    v["received_amount"] * v["target_exchange_rate"],
                    places=6, msg=(payment_type, party))

    def test_the_sign_of_the_booking_does_not_matter(self):
        self.assertEqual(
            payment_entry_values("Pay", -470.0, "CHF", "EUR", "EUR", EUR_CHF),
            payment_entry_values("Pay", 470.0, "CHF", "EUR", "EUR", EUR_CHF))

    def test_every_field_is_decided(self):
        values = payment_entry_values("Receive", 1.0, "CHF", "EUR", "EUR",
                                      EUR_CHF)
        self.assertEqual(sorted(values), sorted(FIELDS))


class TestWhereTheBanksRateDoesNotDecide(unittest.TestCase):

    def test_three_currencies_are_left_to_erpnext(self):
        """CHF bank, USD party, EUR company: the bank's EUR/CHF rate next to
        two system rates would not balance."""
        self.assertIsNone(payment_entry_values(
            "Receive", 940.0, "CHF", "USD", "EUR", EUR_CHF))

    def test_a_rate_about_other_currencies_is_not_used(self):
        self.assertIsNone(payment_entry_values(
            "Receive", 940.0, "CHF", "EUR", "EUR",
            {"from": "USD", "to": "CHF", "rate": 0.8}))

    def test_one_currency_has_nothing_to_convert(self):
        self.assertIsNone(payment_entry_values(
            "Receive", 100.0, "EUR", "EUR", "EUR", EUR_CHF))

    def test_without_a_rate_nothing_changes(self):
        self.assertIsNone(payment_entry_values(
            "Receive", 940.0, "CHF", "EUR", "EUR", None))

    def test_an_unknown_currency_or_type_changes_nothing(self):
        self.assertIsNone(payment_entry_values(
            "Receive", 940.0, "CHF", None, "EUR", EUR_CHF))
        self.assertIsNone(payment_entry_values(
            "Internal Transfer", 940.0, "CHF", "EUR", "EUR", EUR_CHF))


def _source(*parts):
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    with open(os.path.join(root, *parts), encoding="utf-8") as handle:
        return handle.read()


class TestThePaymentEntryWrapper(unittest.TestCase):
    """Read as text: the override needs ERPNext to load."""

    def setUp(self):
        text = _source("overrides", "bank_reconciliation_tool",
                       "bank_reconciliation_tool.py")
        self.body = text[text.index("def custom_create_payment_entry_bts"):]

    def test_it_is_installed_over_erpnexts_endpoint(self):
        hooks = _source("hooks.py")
        self.assertIn(
            '"erpnext.accounts.doctype.bank_reconciliation_tool.'
            'bank_reconciliation_tool.create_payment_entry_bts": '
            '"kefiya.overrides.bank_reconciliation_tool.'
            'bank_reconciliation_tool.custom_create_payment_entry_bts"',
            hooks)

    def test_erpnext_builds_the_entry_and_nothing_is_saved_first(self):
        """The permission checks stay ERPNext's; the bank's rate is set on
        the unsaved entry, before insert."""
        built = self.body.index("allow_edit=1")
        rated = self.body.index("pe.set(field, values[field])")
        saved = self.body.index("pe.insert()")
        self.assertLess(built, rated)
        self.assertLess(rated, saved)

    def test_without_a_bank_rate_it_is_erpnexts_function(self):
        early = self.body[:self.body.index("allow_edit=1")]
        self.assertIn("if not bank_fx:", early)
        self.assertIn("return original(bank_transaction_name, "
                      "allow_edit=allow_edit,", early)

    def test_no_request_argument_reaches_erpnext_unnamed(self):
        signature = self.body[:self.body.index("):")]
        self.assertNotIn("**", signature)


if __name__ == "__main__":
    unittest.main()
