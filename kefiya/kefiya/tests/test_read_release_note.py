# -*- coding: utf-8 -*-
"""Every read beside the bookings writes down a release the bank asks for.

23.11.2026: Volksbank accounts asked for a release in the app on every fetch
by hand, while the bookings themselves went through without one, and nothing
recorded which read had asked. Agreed: first write it down, then decide.
"""

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
ROOT = os.path.dirname(APP)


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


def _body(source, name):
    match = re.search(r"\n    def {0}\(.*?(?=\n    def |\nclass |\Z)".format(
        name), source, re.S)
    assert match, name
    return match.group(0)


class TestEveryReadNotesItsRelease(unittest.TestCase):
    READS = {
        "get_fints_balance": "balance",
        "get_fints_pending_transactions": "pending_transactions",
        "get_fints_holdings": "holdings",
        "get_fints_depot_holdings": "securities_accounts",
        "get_fints_scheduled_debits": "scheduled_debits",
        "get_fints_scheduled_transfers": "scheduled_transfers",
        "get_fints_standing_orders": "standing_orders",
        "get_fints_statements": "statements",
        "get_fints_credit_card_transactions": "credit_card",
    }

    def test_each_read_notes(self):
        source = _read("utils", "fints_controller.py")
        for method, label in self.READS.items():
            body = _body(source, method)
            self.assertIn('self._note_read_release(', body, method)
            self.assertIn('"{0}"'.format(label), body, method)

    def test_holdings_still_refuse_after_noting(self):
        body = _body(_read("utils", "fints_controller.py"),
                      "get_fints_holdings")
        self.assertLess(body.index("_note_read_release"),
                        body.index("frappe.throw"))

    def test_bestand_refusal_carries_the_challenge(self):
        source = _read("utils", "standing_orders.py")
        self.assertIn("refused.release_response = result", source)

    def test_the_note_is_written_attended_or_not_and_never_raises(self):
        body = _body(_read("utils", "fints_tan_session.py"),
                     "_note_read_release")
        self.assertIn("note_on_login(", body)
        self.assertNotIn("if attended", body)
        self.assertIn("except Exception:\n            pass", body)
        # Deduplicated like the other release note, by read.
        self.assertIn("ex=900, nx=True", body)


if __name__ == "__main__":
    unittest.main()
