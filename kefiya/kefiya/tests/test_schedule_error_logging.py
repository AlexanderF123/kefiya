# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

import inspect
import unittest
from pathlib import Path

import frappe

from kefiya.kefiya.doctype.kefiya_schedule import kefiya_schedule
from kefiya.utils.fints_controller import _mask_iban


class TestScheduleErrorLogging(unittest.TestCase):
    """Regression tests for the scheduler outage of 2026-07.

    ``frappe.log_error(text)`` passes its single positional argument as the
    *title*, which is the Error Log ``method`` field -- a Data column capped at
    140 characters. Logging a full traceback that way raised
    ``CharacterLengthExceededError`` from inside the per-login except block, so
    one broken login aborted the whole scheduler tick instead of just its own
    iteration.
    """

    def test_log_import_failure_never_raises(self):
        """The error path must survive its own logger blowing up.

        This is the actual defect: the except block could not tolerate a
        failing ``log_error``, so the batch died instead of continuing.
        """
        original = frappe.log_error

        def exploding_log_error(*args, **kwargs):
            raise frappe.CharacterLengthExceededError("boom")

        frappe.log_error = exploding_log_error
        try:
            # Must return normally rather than propagate.
            kefiya_schedule._log_import_failure("Some Login")
        finally:
            frappe.log_error = original

    def test_log_import_failure_title_fits_error_log_field(self):
        """A very long login name must not overflow the title field."""
        captured = {}
        original = frappe.log_error

        def capturing_log_error(*args, **kwargs):
            captured.update(kwargs)
            captured["positional"] = args

        frappe.log_error = capturing_log_error
        try:
            kefiya_schedule._log_import_failure("L" * 500)
        finally:
            frappe.log_error = original

        self.assertLessEqual(
            len(captured["title"]), 140,
            "Error Log title (fieldname 'method') is a Data column capped at "
            "140 characters; a longer value raises inside the except block.",
        )
        self.assertEqual(
            captured["positional"], (),
            "log_error must be called with keyword arguments only -- a lone "
            "positional argument is taken as the title, not the message.",
        )
        self.assertIn(
            "Traceback", captured["message"],
            "The traceback belongs in `message`, never in `title`.",
        )

    def test_no_positional_log_error_in_app(self):
        """Guard the whole bug class, not just the site that caused the outage.

        ``frappe.log_error(frappe.get_traceback())`` is always wrong: it files
        the traceback as the title. Fail if the pattern reappears anywhere.
        """
        app_root = Path(inspect.getfile(kefiya_schedule)).parents[3]
        offenders = []
        for path in app_root.rglob("*.py"):
            if path.name == Path(__file__).name:
                continue
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if "log_error(frappe.get_traceback())" in line:
                    offenders.append("{0}:{1}".format(path, number))
        self.assertEqual(
            offenders, [],
            "Use frappe.log_error(title=..., message=frappe.get_traceback()); "
            "found positional calls at: {0}".format(", ".join(offenders)),
        )


class TestMaskIban(unittest.TestCase):
    def test_mask_iban_edge_cases(self):
        """Diagnostic output must never raise, whatever the field holds."""
        self.assertEqual(_mask_iban("DE89370400440532013000"), "DE***3000")
        self.assertEqual(_mask_iban(None), "<no IBAN>")
        self.assertEqual(_mask_iban(""), "<no IBAN>")
        # Too short to mask meaningfully -- returned as-is, still no crash.
        self.assertEqual(_mask_iban("ABCDEF"), "ABCDEF")
        self.assertEqual(_mask_iban("ABCDEFG"), "AB***DEFG")
        # Non-string input must be coerced rather than blow up.
        self.assertEqual(_mask_iban(12345678), "12***5678")

    def test_mask_iban_hides_the_account_number(self):
        """The point of masking: the full number must not reach the log."""
        iban = "DE89370400440532013000"
        self.assertNotIn(iban, _mask_iban(iban))
        self.assertNotIn("37040044", _mask_iban(iban))
