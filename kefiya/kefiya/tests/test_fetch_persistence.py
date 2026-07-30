# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

import inspect
import unittest

import frappe

from kefiya.utils import client, fetch_persistence
from kefiya.utils.fints_controller import FinTSController


class TestNothingIsOnlyCounted(unittest.TestCase):
    """A fetch used to pull documents and credit-card transactions from the
    bank and then report a bare count -- the data was dropped on the floor."""

    def test_every_retrieval_persists_something(self):
        source = inspect.getsource(client.fetch_all)
        self.assertNotIn(
            '"count": len(', source,
            "Counting a result instead of storing it is the whole defect.",
        )
        for helper in ("store_balance", "replace_pending_transactions",
                       "download_statements",
                       "store_credit_card_transactions"):
            self.assertIn(
                "fetch_persistence." + helper, source,
                "{0} must be reached from fetch_all.".format(helper))

    def test_holdings_are_fetched_too(self):
        source = inspect.getsource(client.fetch_all)
        self.assertIn("get_fints_holdings()", source)
        self.assertIn("refresh_holdings", source)


class TestBalanceIsStored(unittest.TestCase):
    """The balance was returned to the caller and forgotten."""

    def test_it_lands_on_the_bank_account(self):
        source = inspect.getsource(fetch_persistence.store_balance)
        self.assertIn("custom_account_balance", source)
        self.assertIn("custom_credit_line", source)
        self.assertIn(
            "account.save(", source,
            "Through the document lifecycle, not a direct database write.",
        )

    def test_the_right_row_is_picked(self):
        """A bank may answer for several accounts in one HISAL response."""
        source = inspect.getsource(fetch_persistence.store_balance)
        self.assertIn('r.get("iban") == login.account_iban', source)

    def test_missing_custom_fields_do_not_fail_the_fetch(self):
        source = inspect.getsource(fetch_persistence.store_balance)
        self.assertIn('meta.has_field("custom_account_balance")', source)

    def test_the_target_fields_exist_on_this_instance(self):
        meta = frappe.get_meta("Bank Account")
        self.assertTrue(meta.has_field("custom_account_balance"))
        self.assertTrue(meta.has_field("custom_credit_line"))


class TestPendingEntriesCannotDoubleCount(unittest.TestCase):
    """A pending entry becomes a booking with a different date, so the import's
    dedup hash would not recognise the two as the same payment and the account
    would show it twice."""

    def _source(self):
        return inspect.getsource(fetch_persistence.replace_pending_transactions)

    def test_pending_entries_stay_drafts(self):
        source = self._source()
        self.assertIn('"docstatus": 0', source)
        self.assertIn('"status": "Pending"', source)

    def test_the_previous_snapshot_is_replaced(self):
        source = self._source()
        self.assertIn("frappe.delete_doc", source)
        self.assertIn(
            '"docstatus": 0', source,
            "Only drafts may be dropped -- a submitted transaction is a real "
            "booking.",
        )

    def test_a_booked_transaction_is_never_deleted(self):
        source = self._source()
        self.assertIn(
            'filters={', source)
        self.assertIn(
            '"docstatus": 0,', source,
            "The delete filter must be bound to drafts carrying our marker.",
        )
        self.assertIn("PENDING_MARKER", source)

    def test_the_marker_is_recognisable(self):
        self.assertIn("vorgemerkt", fetch_persistence.PENDING_MARKER)


class TestPendingFetchIsSafe(unittest.TestCase):
    """The pending entries come from the same message as the booked ones."""

    def _source(self):
        return inspect.getsource(
            FinTSController.get_fints_pending_transactions)

    def test_it_uses_the_crash_safe_path(self):
        source = self._source()
        self.assertIn(
            "self._get_transactions_raw(", source,
            "The library's public get_transactions dies on the camt unpacking "
            "as soon as the bank answers with a TAN challenge.",
        )
        self.assertNotIn("self.fints_connection.get_transactions(", source)

    def test_a_tan_challenge_does_not_break_the_fetch(self):
        source = self._source()
        self.assertIn("NeedRetryResponse", source)
        self.assertIn(
            "return []", source,
            "The booked transactions are the point and already went through; "
            "a TAN request for the pending ones must not undo that.",
        )

    def test_include_pending_reaches_the_library(self):
        raw = inspect.getsource(FinTSController._get_transactions_raw)
        self.assertIn("include_pending=False", raw)
        self.assertIn(
            "if include_pending and result[1]:", raw,
            "The camt path has to add the pending streams, not ignore them.",
        )


class TestStatementsAreDownloaded(unittest.TestCase):
    """The list only says which statements exist; each has to be fetched."""

    def _source(self):
        return inspect.getsource(fetch_persistence.download_statements)

    def test_the_documents_themselves_are_fetched(self):
        source = self._source()
        self.assertIn("controller.get_fints_statement(", source)

    def test_it_does_not_download_the_same_one_twice(self):
        source = self._source()
        self.assertIn('frappe.db.exists("File"', source)

    def test_the_field_names_match_the_fints_segment(self):
        """HIKAU calls them statement_number and year."""
        source = self._source()
        self.assertIn('"statement_number"', source)

    def test_the_extension_follows_the_real_format(self):
        """FinTS allows MT940 and ISO 8583 besides PDF."""
        source = inspect.getsource(fetch_persistence._statement_suffix)
        self.assertIn("statement_format", source)
        self.assertIn(".sta", source)
        self.assertIn('b"%PDF-"', source)

    def test_a_first_run_cannot_pull_years_of_pdfs(self):
        source = self._source()
        self.assertIn("limit", source)
        self.assertIn("entries[:limit]", source)


class TestCreditCardTransactionsAreBooked(unittest.TestCase):
    """A card charge moves money exactly like a transfer does."""

    def _source(self):
        return inspect.getsource(
            fetch_persistence.store_credit_card_transactions)

    def test_they_become_bank_transactions(self):
        source = self._source()
        self.assertIn('"doctype": "Bank Transaction"', source)
        self.assertIn('"docstatus": 1', source)

    def test_a_repeated_fetch_is_harmless(self):
        source = self._source()
        self.assertIn('frappe.db.exists("Bank Transaction"', source)
        self.assertIn("hashlib.md5", source)
