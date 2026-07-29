# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

import inspect
import unittest

from kefiya.utils import client
from kefiya.utils.fints_controller import FinTSController


class TestUnsupportedSegmentsAreNotErrors(unittest.TestCase):
    """A bank that does not offer a segment is not a malfunction.

    fetch_all tries every retrieval type per login. Where the bank answers
    "No supported HIKAUS version found ... bank supports ()", that used to be
    logged like a real failure -- one collective run produced 32 Error Log
    entries, 24 of them for credit cards alone, burying the failures that do
    need attention.
    """

    def _helper(self):
        return inspect.getsource(client._optional_fetch)

    def test_unsupported_operation_is_not_logged(self):
        source = self._helper()
        self.assertIn("FinTSUnsupportedOperation", source)
        self.assertIn(
            'summary.setdefault("unsupported", [])', source,
            "An unsupported segment must be recorded on the summary, not "
            "written to the Error Log.",
        )

    def test_real_failures_are_still_logged(self):
        source = self._helper()
        self.assertIn("frappe.log_error", source)
        self.assertIn(
            'summary["errors"].append(label)', source,
            "Anything that is not an unsupported segment must still surface.",
        )

    def test_every_optional_fetch_uses_the_helper(self):
        """No retrieval may keep its own except/log_error block."""
        source = inspect.getsource(client.fetch_all)
        self.assertNotIn(
            "Kefiya fetch_all:", source,
            "Direct log_error titles in fetch_all mean a retrieval bypasses "
            "_optional_fetch and will keep spamming the Error Log.",
        )
        self.assertEqual(
            source.count("_optional_fetch("), 4,
            "All four optional retrievals (balance, scheduled debits, "
            "statements, credit card) must route through the helper.",
        )


class TestMidFetchTanRequest(unittest.TestCase):
    """An expired SCA turns a statement fetch into a TAN challenge.

    python-fints expects a (booked, pending) tuple at that point and fails
    unpacking, which surfaced as "cannot unpack non-iterable NeedTANResponse
    object" -- naming neither the login nor the cause.
    """

    def _source(self):
        return inspect.getsource(FinTSController._get_transactions_checked)

    def test_tan_response_becomes_a_tan_interaction(self):
        source = self._source()
        self.assertIn("NeedTANResponse", source)
        self.assertIn(
            "TanInteractionRequired", source,
            "A mid-fetch TAN request must raise the exception the rest of the "
            "app already handles, not a bare TypeError.",
        )

    def test_unrelated_type_errors_are_not_swallowed(self):
        source = self._source()
        self.assertIn(
            'if "NeedTANResponse" not in str(exc):', source,
            "Only the TAN unpacking failure may be reinterpreted; every other "
            "TypeError has to propagate unchanged.",
        )
        self.assertIn("raise", source)

    def test_prompt_failure_cannot_mask_the_tan_error(self):
        """The scheduler has no UI; publishing the prompt may fail there."""
        source = self._source()
        self.assertIn(
            "except Exception:", source,
            "The interactive prompt must be guarded -- this is an error path "
            "and must not raise on its own.",
        )


class TestSkipFetch(unittest.TestCase):
    """Loan and clearing accounts are never offered for statement retrieval,
    so fetching them fails on every single run."""

    def test_scheduler_skips_marked_logins(self):
        from kefiya.kefiya.doctype.kefiya_schedule import kefiya_schedule

        source = inspect.getsource(
            kefiya_schedule.scheduled_import_fints_payments)
        self.assertIn("skip_fetch", source)
        self.assertIn(
            "if skip_fetch:", source,
            "A login marked as excluded must be skipped before a Kefiya "
            "Import is created for it.",
        )

    def test_fetch_all_refuses_marked_logins(self):
        source = inspect.getsource(client.fetch_all)
        self.assertIn("skip_fetch", source)
        self.assertIn(
            '"skipped"', source,
            "The collective fetch must report a skip rather than failing.",
        )

    def test_skip_is_checked_before_any_bank_contact(self):
        """Skipping after contacting the bank would defeat the purpose."""
        source = inspect.getsource(client.fetch_all)
        skip_at = source.index("skip_fetch")
        import_at = source.index("import_fints_transactions")
        self.assertLess(
            skip_at, import_at,
            "The skip check must come before the transaction import.",
        )
