# -*- coding: utf-8 -*-
"""25.11.2026: a fetch and a transfer on the same access at once, and a log
that does not say when.

* The transfer's save() of the login refused because the fetch had written
  it first ("has been modified after you have opened it"). The connection
  state is now written to the row without the timestamp check.
* The fetch log shows date and time per account.
"""

import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(os.path.dirname(HERE))


def _read(*parts):
    with open(os.path.join(APP, *parts), encoding="utf-8") as handle:
        return handle.read()


class TestTheStateIsWrittenWithoutTheTimestampCheck(unittest.TestCase):
    def test_persist_writes_the_fields_not_the_document(self):
        source = _read("utils", "fints_controller.py")
        body = source.split("def _persist_fints_state(")[1].split(
            "\n    def ")[0]
        self.assertIn("self._write_state_fields()", body)
        self.assertNotIn("self.kefiya_login.save()", body)

    def test_only_state_fields_and_modified_untouched(self):
        source = _read("utils", "fints_controller.py")
        body = source.split("def _write_state_fields(")[1].split(
            "\n    def ")[0]
        self.assertIn("update_modified=False", body)
        self.assertIn("self.STATE_FIELDS", body)
        fields = source.split("STATE_FIELDS = (")[1].split(")")[0]
        for name in ("stored_client_state", "stored_tan_state",
                     "stored_dialog_state", "stored_gateway_state"):
            self.assertIn(name, fields)


class TestTheRawWriteKeepsNotNullColumnsFilled(unittest.TestCase):
    """27.11.2026: every account fetch ended on (1048, "Column
    'stored_tan_state_decoupled' cannot be null"). save() used to turn the
    None into 0; the direct write since #147 does not."""

    def _state_fields(self):
        source = _read("utils", "fints_controller.py")
        block = source.split("STATE_FIELDS = (")[1].split(")")[0]
        return [part.strip().strip('"') for part in block.split(",")
                if part.strip().startswith('"')]

    def test_a_none_check_becomes_zero_and_text_stays_none(self):
        from kefiya.utils import fints_state_fields
        self.assertEqual(fints_state_fields.for_raw_write("Check", None), 0)
        self.assertEqual(fints_state_fields.for_raw_write("Check", 1), 1)
        self.assertIsNone(
            fints_state_fields.for_raw_write("Long Text", None))
        self.assertIsNone(fints_state_fields.for_raw_write("Datetime", None))

    def test_every_not_null_state_field_is_covered(self):
        import json
        from kefiya.utils import fints_state_fields
        meta = json.loads(_read("kefiya", "doctype", "kefiya_login",
                                "kefiya_login.json"))
        types = {f["fieldname"]: f["fieldtype"] for f in meta["fields"]}
        checked = 0
        for field in self._state_fields():
            fieldtype = types.get(field)
            if fieldtype in ("Check", "Int", "Float", "Currency", "Percent"):
                checked += 1
                self.assertEqual(
                    fints_state_fields.for_raw_write(fieldtype, None), 0,
                    field)
        self.assertGreaterEqual(checked, 1,
                                "stored_tan_state_decoupled is a Check")

    def test_the_direct_write_goes_through_it(self):
        source = _read("utils", "fints_controller.py")
        body = source.split("def _write_state_fields(")[1].split(
            "\n    def ")[0]
        self.assertIn("fints_state_fields.for_raw_write(", body)

    def test_the_controller_never_sets_the_check_to_none(self):
        source = _read("utils", "fints_controller.py")
        self.assertNotIn("stored_tan_state_decoupled = None", source)


class TestTheLogSaysWhen(unittest.TestCase):
    def test_the_server_sends_the_time(self):
        source = _read("utils", "client.py")
        body = source.split("def _say(")[1].split("\ndef ")[0]
        self.assertIn('"at": str(frappe.utils.now_datetime())[:19]', body)

    def test_every_entry_carries_and_shows_it(self):
        source = _read("public", "js", "controllers", "bank_refresh.js")
        self.assertIn("noteResult(d.login, d.summary, d.error, d.at)", source)
        self.assertIn("at: at || frappe.datetime.now_datetime()", source)
        self.assertIn("esc(whenOf(e.at))", source)


if __name__ == "__main__":
    unittest.main()
