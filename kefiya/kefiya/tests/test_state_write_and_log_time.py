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
    def _body(self, name):
        source = _read("utils", "fints_controller.py")
        return source.split("def {0}(".format(name))[1].split("\n    def ")[0]

    def test_persist_writes_the_fields_not_the_document(self):
        body = self._body("_persist_fints_state")
        self.assertIn("self._write_state_fields()", body)
        self.assertNotIn("self.kefiya_login.save()", body)

    def test_discarding_a_challenge_writes_the_same_way(self):
        """The second path that wrote connection state with save(), and
        with it the timestamp check #147 removed from the first."""
        body = self._body("__discard_parked_challenge")
        self.assertIn("self._write_state_fields()", body)
        self.assertNotIn("self.kefiya_login.save()", body)

    def test_one_list_and_the_conversion_save_uses(self):
        body = self._body("_write_state_fields")
        self.assertIn("update_modified=False", body)
        self.assertIn("fints_state_fields.PERSISTED", body)
        # The same per-type conversion save() writes with: a None Check
        # becomes 0. Raw set_value does not convert -- 27.11.2026, error 1048
        # on every fetch.
        self.assertIn("self.kefiya_login.get_valid_dict()", body)
        source = _read("utils", "fints_controller.py")
        self.assertNotIn("STATE_FIELDS", source)


class TestTheListIsComplete(unittest.TestCase):
    """What the controller writes without save(), checked against the
    document it writes to."""

    def _setters(self):
        """{setter name: fields it assigns} from kefiya_login.py."""
        import ast
        tree = ast.parse(_read("kefiya", "doctype", "kefiya_login",
                               "kefiya_login.py"))
        found = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not any(isinstance(d, ast.Attribute) and d.attr == "setter"
                       for d in node.decorator_list):
                continue
            fields = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign):
                    for target in sub.targets:
                        if (isinstance(target, ast.Attribute)
                                and isinstance(target.value, ast.Name)
                                and target.value.id == "self"):
                            fields.add(target.attr)
            found[node.name] = fields
        return found

    def test_every_field_exists_on_the_login(self):
        import json
        from kefiya.utils import fints_state_fields
        meta = json.loads(_read("kefiya", "doctype", "kefiya_login",
                                "kefiya_login.json"))
        names = {f["fieldname"] for f in meta["fields"]}
        for field in fints_state_fields.PERSISTED:
            self.assertIn(field, names)

    def test_a_state_goes_with_its_timestamp(self):
        """Until 27.11.2026 client_state_updated and dialog_state_updated
        were set by the setters and never written: the choice between
        sibling logins compared stale times, and a discarded state kept its
        old one."""
        from kefiya.utils import fints_state_fields
        persisted = set(fints_state_fields.PERSISTED)
        setters = self._setters()
        self.assertIn("stored_client_blob", setters)
        for name, fields in setters.items():
            if fields & persisted:
                self.assertLessEqual(
                    fields, persisted,
                    "{0} sets {1}, but only part of it is written".format(
                        name, sorted(fields)))
        self.assertIn("client_state_updated", persisted)
        self.assertIn("dialog_state_updated", persisted)

    def test_the_payee_check_is_not_written_by_a_fetch(self):
        """The transfer writes its own; a fetch writing the state from
        before its dialog would overwrite a payee check in progress."""
        from kefiya.utils import fints_state_fields
        self.assertNotIn("stored_vop_state", fints_state_fields.PERSISTED)
        self.assertNotIn("stored_vop_dialog_state",
                         fints_state_fields.PERSISTED)

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
