# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""From which accounts a transfer may start.

The payer dropdown offered five loans and a credit card. Three filters were
meant to prevent that -- the Bank Account's account_type, a link to a Property
Loan, and the bank's own HIUPD capability list -- and all three missed: the
account_type is not maintained on those records, the loan link is not either,
and HIUPD is never fetched for an account nobody fetches.

The kind was right on every one of them the whole time. Nothing asked.
"""

import inspect
import unittest

from kefiya.utils import account_kind


class TestWhatMaySendMoney(unittest.TestCase):

    def test_a_loan_cannot_send(self):
        self.assertNotIn(account_kind.LOAN, account_kind.TRANSFER_SOURCE_KINDS)

    def test_a_guarantee_a_share_and_a_depot_cannot_send(self):
        for kind in (account_kind.GUARANTEE, account_kind.SHARES,
                     account_kind.SECURITIES):
            self.assertNotIn(kind, account_kind.TRANSFER_SOURCE_KINDS, kind)

    def test_a_credit_card_cannot_send_either(self):
        """It is paid, it does not pay. This is where the sending kinds are
        narrower than the payment kinds -- a card counts towards liquidity and
        keeps a running balance, but no SEPA transfer starts from it."""
        self.assertIn(account_kind.CREDIT_CARD, account_kind.PAYMENT_KINDS)
        self.assertNotIn(account_kind.CREDIT_CARD,
                         account_kind.TRANSFER_SOURCE_KINDS)

    def test_a_giro_and_a_savings_account_can(self):
        self.assertIn(account_kind.GIRO, account_kind.TRANSFER_SOURCE_KINDS)
        self.assertIn(account_kind.SAVINGS, account_kind.TRANSFER_SOURCE_KINDS)

    def test_every_sending_kind_is_a_real_kind(self):
        for kind in account_kind.TRANSFER_SOURCE_KINDS:
            self.assertIn(kind, account_kind.KINDS, kind)


class TestTheAnswerIsOfferedOnce(unittest.TestCase):
    """So a page does not have to reimplement the rule -- which is how the
    dropdown came to disagree with the app in the first place."""

    def test_there_is_a_helper_for_a_single_login(self):
        self.assertTrue(callable(account_kind.can_send_transfers))
        source = inspect.getsource(account_kind.can_send_transfers)
        self.assertIn("TRANSFER_SOURCE_KINDS", source)

    def test_there_is_an_endpoint_for_the_whole_list(self):
        source = inspect.getsource(account_kind.transfer_sources)
        self.assertIn("TRANSFER_SOURCE_KINDS", source)

    def test_the_list_is_read_with_permissions(self):
        """These are offered for selection; an access the caller may not see
        must not appear in a dropdown."""
        source = inspect.getsource(account_kind.transfer_sources)
        self.assertIn('frappe.get_list(\n        "Kefiya Login"', source)

    def test_a_disabled_account_is_not_offered(self):
        source = inspect.getsource(account_kind.transfer_sources)
        self.assertIn('"disabled": 1', source)

    def test_a_site_without_the_field_still_gets_a_list(self):
        """Before account_kind exists every login is a payment account, which
        is what kind_of() answers anyway. Returning nothing would empty the
        dropdown on an instance that never classified its accounts."""
        source = inspect.getsource(account_kind.transfer_sources)
        self.assertIn('has_field("account_kind")', source)
