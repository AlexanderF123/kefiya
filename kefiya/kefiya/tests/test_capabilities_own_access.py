# -*- coding: utf-8 -*-
"""HIUPD lists what the READING access may do on an account (26.11.2026).

A second access, allowed only to look at an account, overwrote that
account's list -- and every send from it was refused. The list now goes
only onto the accounts of the access that read it.
"""

import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(os.path.dirname(HERE))


class TestTheListStaysWithItsAccess(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(APP, "utils", "account_capabilities.py"),
                  encoding="utf-8") as handle:
            source = handle.read()
        self.body = source.split("def refresh_account_capabilities(")[1] \
            .split("\ndef ")[0]

    def test_the_accounts_of_the_access_are_known_before_the_loop(self):
        self.assertIn("login_siblings.same_access(", self.body)
        self.assertLess(self.body.index("ours = {"),
                        self.body.index("for row in rows:"))

    def test_nothing_is_written_outside_them(self):
        loop = self.body.split("for row in rows:")[1]
        self.assertLess(loop.index("if account not in ours:"),
                        loop.index("store_for_account(account,"))
        # One query before the loop, none per account.
        self.assertNotIn('frappe.get_all("Kefiya Login"', loop)


if __name__ == "__main__":
    unittest.main()
