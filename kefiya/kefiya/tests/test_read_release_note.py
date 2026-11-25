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
            if method == "get_fints_pending_transactions":
                # Through _pending_read, which notes before anything else.
                body = _body(source, "_pending_read")
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


class TestPendingReadWaitsByHand(unittest.TestCase):
    """23.11.2026: the pending read asks every Volksbank account for a
    decoupled release. By hand it is waited for; at night it is not."""

    def test_both_pending_answers_go_through_the_release(self):
        body = _body(_read("utils", "fints_controller.py"),
                     "get_fints_pending_transactions")
        self.assertEqual(body.count("self._pending_read("), 2)

    def test_waits_only_attended_and_decoupled(self):
        body = _body(_read("utils", "fints_controller.py"), "_pending_read")
        self.assertIn("self.interactive.enabled", body)
        self.assertIn('getattr(answer, "decoupled", False)', body)
        self.assertLess(body.index("self._note_read_release"),
                        body.index("self._await_release"))
        self.assertLess(body.index("self._publish_tan_prompt"),
                        body.index("self._await_release"))
        self.assertIn("_as_transactions(released, include_pending)", body)
        # Nothing parked: the next account must not be held up.
        self.assertNotIn("_park_tan_challenge", body)

    def test_only_the_fetch_by_hand_is_attended(self):
        source = _read("utils", "client.py")
        self.assertIn("user_scope=scope)", source)
        self.assertIn('{"docname": user_scope, "enabled": True}', source)


class TestPendingLeftOutAtNight(unittest.TestCase):
    """24.11.2026: "nachts weglassen" -- the pending read where the bank asks
    for a release; and the nightly run in the site's language."""

    def test_night_skips_where_the_bank_asked(self):
        source = _read("utils", "client.py")
        body = source.split("def fetch_extras(")[1].split("\ndef ")[0]
        guard = body.index(
            "if not user_scope and _pending_wants_release(kefiya_login)")
        self.assertLess(guard, body.index(
            'summary, "pending", "pending_transactions", _fetch_pending)'))

    def test_memory_is_the_timeline_note(self):
        source = _read("utils", "client.py")
        body = source.split("def _pending_wants_release(")[1].split(
            "\ndef ")[0]
        self.assertIn("read=pending_transactions", body)
        self.assertIn("PENDING_RELEASE_MEMORY_DAYS", body)
        self.assertIn("return False", body)

    def test_schedule_speaks_the_sites_language(self):
        with open(os.path.join(APP, "doctype", "kefiya_schedule",
                               "kefiya_schedule.py"),
                  encoding="utf-8") as handle:
            source = handle.read()
        body = source.split("def scheduled_import_fints_payments(")[1]
        self.assertLess(body.index("_speak_the_sites_language()"),
                        body.index("frappe.get_single('Kefiya Schedule')"))
