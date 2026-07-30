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
    object" -- naming neither the login nor the cause, and destroying the
    challenge object on the way, so the authentication could never be
    completed.
    """

    def _source(self):
        return inspect.getsource(FinTSController._get_transactions_checked)

    def test_the_challenge_survives_the_fetch(self):
        raw = inspect.getsource(FinTSController._get_transactions_raw)
        self.assertIn(
            "NeedRetryResponse", raw,
            "The camt path must return the challenge instead of unpacking it "
            "-- that unpacking is the bug being fixed.",
        )
        self.assertIn(
            "booked_streams = result[0]", raw,
            "Only a real result may be unpacked, and only after the challenge "
            "has been ruled out.",
        )

    def test_library_drift_falls_back_to_the_public_call(self):
        raw = inspect.getsource(FinTSController._get_transactions_raw)
        self.assertIn("except (AttributeError, ImportError):", raw)
        self.assertIn(
            "conn.get_transactions(", raw,
            "If python-fints renames its internals we must degrade to the "
            "public method, not crash.",
        )

    def test_tan_response_becomes_a_tan_interaction(self):
        source = self._source()
        self.assertIn("NeedTANResponse", source)
        self.assertIn(
            "TanInteractionRequired", source,
            "A mid-fetch TAN request must raise the exception the rest of the "
            "app already handles.",
        )

    def test_decoupled_logins_are_not_asked_for_a_code(self):
        """pushTAN 2.0 (Volksbank) is released in the app and yields no TAN.

        Telling those users to "enter the TAN" sends them looking for
        something their bank never issues.
        """
        source = self._source()
        self.assertIn("decoupled", source)
        self.assertIn(
            "banking app", source,
            "The decoupled branch must ask for the release in the app.",
        )
        self.assertIn(
            "Enter the TAN", source,
            "The non-decoupled branch must still ask for the TAN itself.",
        )
        self.assertLess(
            source.index("if decoupled:"), source.index("Enter the TAN"),
            "The decoupled case has to be decided before the TAN wording.",
        )

    def test_prompt_failure_cannot_mask_the_tan_error(self):
        """The scheduler has no UI; publishing the prompt may fail there."""
        source = self._source()
        self.assertIn(
            "except Exception:", source,
            "Parking the challenge must be guarded -- this is an error path "
            "and must not raise on its own.",
        )


class TestTanRequestReachesTheCaller(unittest.TestCase):
    """import_fints_transactions used to rewrite every exception into
    "Error parsing transactions". A TAN request is not a parsing error: the
    rewrite hid it from fetch_all's tan_required branch, so the request failed
    and Frappe rolled back the challenge that had just been parked -- the user
    confirmed a release in the banking app that no longer existed."""

    def test_tan_interaction_is_re_raised_unchanged(self):
        source = inspect.getsource(FinTSController.import_fints_transactions)
        self.assertIn("except TanInteractionRequired:", source)
        self.assertLess(
            source.index("except TanInteractionRequired:"),
            source.index("Error parsing transactions"),
            "The TAN handler must come before the catch-all, otherwise it "
            "never runs.",
        )

    def test_fetch_all_returns_instead_of_failing(self):
        source = inspect.getsource(client.fetch_all)
        self.assertIn('summary["tan_required"] = True', source)
        self.assertIn(
            "return summary", source,
            "Returning normally is what commits the parked challenge; a "
            "re-raise would roll it back.",
        )

    def test_the_empty_import_is_cleaned_up(self):
        source = inspect.getsource(client.fetch_all)
        self.assertIn(
            "frappe.delete_doc", source,
            "Nothing was fetched into that draft, and the rollback that used "
            "to remove it is gone.",
        )


class TestOfferedIbanListIsBounded(unittest.TestCase):
    """A collective bank access offers dozens of accounts; listing all of them
    turned one misconfigured login into an unreadable Error Log entry."""

    def test_preview_is_capped(self):
        from kefiya.utils import fints_controller

        self.assertLessEqual(fints_controller.OFFERED_IBAN_PREVIEW, 15)
        source = inspect.getsource(FinTSController._require_fints_account)
        self.assertIn("OFFERED_IBAN_PREVIEW", source)
        self.assertIn(
            "and {0} more", source,
            "A truncated list must say how much it left out.",
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
