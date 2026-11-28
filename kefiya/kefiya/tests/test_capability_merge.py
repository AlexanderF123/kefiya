# -*- coding: utf-8 -*-
"""An account the bank names more than once in HIUPD (26.11.2026).

Written one entry after the other, the last one won -- and when that was
the short list, every send from the account was refused."""

import os
import unittest

from kefiya.utils.capability_merge import merged

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(os.path.dirname(HERE))

FULL = {"HKCCS": {"required_signatures": 1, "limit_amount": None},
        "HKKAZ": {"required_signatures": 1},
        "HKSAL": {"required_signatures": 1}}
SHORT = {"HKSAL": {"required_signatures": 1}, "DKPSA": {}}


class TestMerged(unittest.TestCase):
    def test_the_short_entry_last_does_not_win(self):
        out = merged([FULL, SHORT])
        self.assertIn("HKCCS", out)
        self.assertIn("HKKAZ", out)

    def test_the_order_does_not_matter(self):
        self.assertEqual(sorted(merged([FULL, SHORT])),
                         sorted(merged([SHORT, FULL])))

    def test_missing_details_are_filled_not_overwritten(self):
        out = merged([{"HKCCS": {"limit_amount": None,
                                  "required_signatures": 1}},
                      {"HKCCS": {"limit_amount": 3000.0,
                                  "required_signatures": 2}}])
        self.assertEqual(out["HKCCS"]["limit_amount"], 3000.0)
        self.assertEqual(out["HKCCS"]["required_signatures"], 1)

    def test_nothing_in_nothing_out(self):
        self.assertEqual(merged([]), {})
        self.assertEqual(merged(None), {})

    def test_the_input_is_not_changed(self):
        first = {"HKCCS": {"limit_amount": None}}
        merged([first, {"HKCCS": {"limit_amount": 1.0}}])
        self.assertIsNone(first["HKCCS"]["limit_amount"])


class TestOneWritePerAccount(unittest.TestCase):
    def test_entries_are_collected_before_they_are_written(self):
        with open(os.path.join(APP, "utils", "account_capabilities.py"),
                  encoding="utf-8") as handle:
            source = handle.read()
        body = source.split("def refresh_account_capabilities(")[1].split(
            "\ndef ")[0]
        self.assertLess(body.index("entries.setdefault(account, [])"),
                        body.index("capability_merge.merged(lists)"))
        self.assertEqual(body.count("store_for_account("), 1)


if __name__ == "__main__":
    unittest.main()
