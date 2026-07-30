# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

import importlib
import os
import re
import unittest

import frappe


APP_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: `kefiya.utils.client.foo` and friends, as written in frappe.call({method: ...})
CALL_PATTERN = re.compile(
    r"[\"']((?:kefiya)(?:\.[A-Za-z_][A-Za-z0-9_]*)+)[\"']")


def _js_files():
    for base, dirs, files in os.walk(APP_ROOT):
        dirs[:] = [d for d in dirs if d not in ("node_modules", "dist", ".git")]
        for name in files:
            if name.endswith(".js"):
                yield os.path.join(base, name)


class TestEveryCalledEndpointExists(unittest.TestCase):
    """Every kefiya method a script calls must exist and be whitelisted.

    `kefiya.utils.client.add_sales_invoice_payment` was called by the payment
    assignment wizard and had never been written. Frappe answers a missing
    method with HTTP 404, which the user sees as the "Nicht gefunden" dialog --
    the button simply did nothing, with no error anywhere in the log.
    """

    def _dotted_calls(self):
        found = {}
        for path in _js_files():
            with open(path, encoding="utf-8") as handle:
                for match in CALL_PATTERN.finditer(handle.read()):
                    found.setdefault(match.group(1), set()).add(
                        os.path.relpath(path, APP_ROOT))
        return found

    def test_no_call_points_at_a_missing_method(self):
        missing = []
        not_whitelisted = []

        for dotted, sources in self._dotted_calls().items():
            module_path, _sep, method_name = dotted.rpartition(".")
            if "." not in module_path:
                # A JavaScript namespace such as `kefiya.tools`, not a server
                # method: `kefiya` itself imports fine, so this has to be
                # filtered out here or every one of them reads as missing.
                continue
            try:
                module = importlib.import_module(module_path)
            except ImportError:
                continue
            method = getattr(module, method_name, None)
            if method is None:
                missing.append((dotted, sorted(sources)))
                continue
            # Frappe registers whitelisted functions in a set and also marks
            # them on the function; either is proof enough.
            registered = method in getattr(frappe, "whitelisted", ())
            if not (registered or getattr(method, "whitelisted", False)):
                not_whitelisted.append((dotted, sorted(sources)))

        self.assertEqual(
            missing, [],
            "These methods are called from JavaScript but do not exist; every "
            "click answers with a 404.",
        )
        self.assertEqual(
            not_whitelisted, [],
            "These methods exist but are not whitelisted, so frappe.call "
            "refuses them.",
        )


class TestReconcileAmount(unittest.TestCase):
    """The reconcile button must allocate a number, and never more than either
    side has open."""

    def test_allocation_is_capped_on_both_sides(self):
        import inspect

        from kefiya.utils import client

        source = inspect.getsource(client.add_sales_invoice_payment)
        self.assertIn("min(unallocated, outstanding)", source)
        self.assertIn(
            'frappe.has_permission("Bank Transaction", ptype="write"', source,
            "Reconciliation writes the allocation onto the Bank Transaction.",
        )

    def test_the_wizard_sends_a_raw_amount(self):
        path = os.path.join(
            APP_ROOT, "kefiya", "page", "assign_payment_entries",
            "assign_payment_entries.js")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn(
            "amount: format_currency(", source,
            "reconcile_vouchers runs flt() over this value; a localised "
            "string reduces to a nonsense allocation.",
        )


class TestFetchGroups(unittest.TestCase):
    """Parallel fetching is only safe across bank accesses, never within one."""

    def test_grouping_key_hides_the_credential(self):
        import inspect

        from kefiya.utils import client

        source = inspect.getsource(client.get_fetch_groups)
        self.assertIn("hashlib.sha256", source)
        self.assertIn(
            '"key": key', source,
            "The browser gets a hash, never the FinTS login itself.",
        )
        self.assertNotIn(
            '"fints_login": row', source,
            "The FinTS login is a credential and must not leave the server.",
        )

    def test_excluded_and_unconfigured_logins_are_left_out(self):
        import inspect

        from kefiya.utils import client

        source = inspect.getsource(client.get_fetch_groups)
        self.assertIn('row.get("skip_fetch")', source)
        self.assertIn('not row.get("account_iban")', source)

    def test_groups_are_ordered_longest_first(self):
        import inspect

        from kefiya.utils import client

        source = inspect.getsource(client.get_fetch_groups)
        self.assertIn(
            "-len(item[1])", source,
            "The longest chain has to start first, otherwise the whole run "
            "waits for it at the end.",
        )

    def test_grouping_is_by_access_not_by_bank(self):
        """Two different accesses at the same bank must not share a dialog."""
        import inspect

        from kefiya.utils import client

        source = inspect.getsource(client.get_fetch_groups)
        self.assertIn(
            '"{0}|{1}".format(row.get("blz")', source,
            "BLZ alone would merge two separate accesses at the same bank.",
        )
        self.assertIn('row.get("fints_login")', source)


class TestSchedulerFrequencyGate(unittest.TestCase):
    """A login that can never succeed used to be retried on every tick.

    The gate read the last SUBMITTED Kefiya Import, and a failed run leaves
    none -- the recovery rolls back even the draft. Six loan accounts and a
    dozen misconfigured IBANs therefore contacted their banks three times an
    hour, every hour, and wrote an Error Log entry each time.
    """

    def _source(self):
        import inspect

        from kefiya.kefiya.doctype.kefiya_schedule import kefiya_schedule

        return inspect.getsource(
            kefiya_schedule.scheduled_import_fints_payments)

    def test_a_failed_attempt_also_closes_the_gate(self):
        source = self._source()
        self.assertIn("last_fetch_attempt", source)
        self.assertIn(
            "max(seen)", source,
            "The newer of last success and last attempt decides.",
        )

    def test_the_attempt_is_recorded_on_both_paths(self):
        import inspect

        from kefiya.kefiya.doctype.kefiya_schedule import kefiya_schedule

        self.assertIn(
            "_record_fetch_attempt", inspect.getsource(
                kefiya_schedule._recover_from_failed_login),
            "Without this the failure path leaves no trace and the gate stays "
            "open.",
        )
        self.assertIn("_record_fetch_attempt", self._source())

    def test_recording_uses_the_document_lifecycle(self):
        import inspect

        from kefiya.kefiya.doctype.kefiya_schedule import kefiya_schedule

        source = inspect.getsource(kefiya_schedule._record_fetch_attempt)
        self.assertIn("login.save(", source)
        self.assertNotIn(
            "db_set", source,
            "Direct database writes are not allowed; go through the document.",
        )
        self.assertIn(
            "except Exception:", source,
            "Recording the attempt must never end the batch.",
        )

    def test_the_field_exists_on_the_doctype(self):
        self.assertTrue(
            frappe.get_meta("Kefiya Login").has_field("last_fetch_attempt"))
