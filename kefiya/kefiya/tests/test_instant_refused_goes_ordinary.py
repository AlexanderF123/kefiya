# -*- coding: utf-8 -*-
"""An instant order on an account that refuses instant payments goes as an
ordinary transfer instead of being stopped (rule of 23.11.2026)."""

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))


def _client():
    with open(os.path.join(ROOT, "kefiya", "utils", "client.py"),
              encoding="utf-8") as handle:
        return handle.read()


def _func(source, name):
    match = re.search(r"\ndef {0}\(.*?(?=\n(?:def |@frappe)|\Z)".format(name),
                      source, re.S)
    assert match, name
    return match.group(0)


class TestInstantRefusedGoesOrdinary(unittest.TestCase):
    def test_runs_before_the_refusal_on_both_send_paths(self):
        source = _client()
        calls = [m.start() for m in re.finditer(
            r"(?<!def )_instant_refused_goes_ordinary\((?:\[doc\]|docs), scheduled\)",
            source)]
        refusals = [m.start() for m in re.finditer(
            r"unsupported = _refuse_unsupported\(", source)]
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(refusals), 2)
        for call, refusal in zip(calls, refusals):
            self.assertLess(call, refusal)
            self.assertLess(refusal - call, 200)

    def test_only_where_ordinary_is_allowed(self):
        body = _func(_client(), "_instant_refused_goes_ordinary")
        self.assertIn("caps.refuses(bank_account, wanted)", body)
        self.assertIn("caps.refuses(bank_account, ordinary)", body)
        self.assertIn("instant=False", body)

    def test_written_onto_the_order_and_said(self):
        body = _func(_client(), "_instant_refused_goes_ordinary")
        self.assertIn('doc.db_set("instant_payment", 0)', body)
        self.assertIn("doc.add_comment(", body)
        self.assertIn("frappe.msgprint(", body)


if __name__ == "__main__":
    unittest.main()
