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
