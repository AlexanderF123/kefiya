# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""An account without an IBAN is not a duplicate of every other one.

The uniqueness check filtered on `{"iban": doc.iban}` with no guard. An
empty IBAN turns that into `iban IS NULL`, which matches every other
account that has none -- and on a book with many such accounts (supplier
accounts, tenant accounts, records kept by hand for a loan rather than for
a bank connection) none of them could be saved any more. The message named
an unrelated account as the supposed duplicate, which sent the search in
the wrong direction as well.
"""

import inspect
import unittest

from kefiya.utils import bank_account_controller


class TestAnEmptyIbanIsNotADuplicate(unittest.TestCase):

    def test_an_empty_iban_ends_the_check(self):
        source = inspect.getsource(
            bank_account_controller.validate_unique_iban)
        self.assertIn("if not iban:\n        return", source)

    def test_the_unguarded_filter_is_gone(self):
        """`{"iban": doc.iban, ...}` is the shape that caused it."""
        source = inspect.getsource(
            bank_account_controller.validate_unique_iban)
        self.assertNotIn('"iban": doc.iban', source)

    def test_only_accounts_that_have_one_are_compared(self):
        source = inspect.getsource(
            bank_account_controller.validate_unique_iban)
        self.assertIn('"iban": ["is", "set"]', source)


class TestOneIbanIsOneIbanHoweverItIsWritten(unittest.TestCase):

    def test_spaces_and_case_do_not_make_a_second_iban(self):
        source = inspect.getsource(
            bank_account_controller.validate_unique_iban)
        self.assertIn('.replace(" ", "").upper()', source)
        # Both sides of the comparison, not just the one being saved.
        self.assertEqual(source.count('.replace(" ", "").upper()'), 2)

    def test_a_real_duplicate_is_still_refused(self):
        source = inspect.getsource(
            bank_account_controller.validate_unique_iban)
        self.assertIn("frappe.throw", source)
        self.assertIn("IBAN already exists in bank account", source)


class TestTheHookStillPoints(unittest.TestCase):

    def test_it_runs_on_validate(self):
        from kefiya import hooks

        self.assertEqual(
            hooks.doc_events["Bank Account"]["validate"],
            "kefiya.utils.bank_account_controller.validate_unique_iban")
