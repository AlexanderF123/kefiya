# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""What the bank executed on its own, read from the statement.

The matching runs here without frappe, on statement lines shaped like the
ones measured in 11/2026 at a Sparkasse and a Volksbank account: purpose glued
to bank additions, no End-To-End ID on the debit side. All names, IBANs and
amounts are invented. The frappe side is read as text.
"""

import datetime
import os
import unittest

from kefiya.utils import bank_execution_match as m

D = datetime.date
HIER = os.path.dirname(os.path.abspath(__file__))
WURZEL = os.path.dirname(os.path.dirname(HIER))

PAYEE = "DE89999999990001111111"
OTHER = "DE19888888880004444444"


def _read(*parts):
    with open(os.path.join(WURZEL, *parts), encoding="utf-8") as handle:
        return handle.read()


def txn(name, day, amount, iban=PAYEE, text="", ref=""):
    return {"name": name, "date": day, "withdrawal": amount,
            "bank_party_iban": iban, "description": text,
            "reference_number": ref}


def pay(key, due, amount, iban=PAYEE, purpose="", e2e=None):
    return {"key": key, "due": due, "amount": amount, "iban": iban,
            "purpose": purpose, "end_to_end_id": e2e}


class TestMatching(unittest.TestCase):

    def test_a_dated_transfer_is_found_by_its_purpose(self):
        """Sparkasse: purpose glued to "DATUM ..", a hash as reference."""
        debit = txn("BT-1", D(2026, 11, 2), 1500.0,
                    text="Rent Example Street 10/2026DATUM 01.11.2026,"
                         " 14.28 UHR", ref="abaa96a8ee")
        found = m.assign([pay("T", D(2026, 11, 2), 1500.0,
                              purpose="Rent Example Street 10/2026",
                              e2e="KEF-TRF-2026-00001-1")], [debit])
        self.assertEqual(found["T"]["name"], "BT-1")

    def test_two_orders_of_the_same_size_to_the_same_payee(self):
        """Two monthly fees, same IBAN, same amount: the purpose decides."""
        a = txn("BT-A", D(2026, 11, 2), 208.25,
                text="102 Management fee Example Road 5 x 35 / DA-3")
        b = txn("BT-B", D(2026, 11, 2), 208.25,
                text="206 Management fee Sample Lane 5 x 35 / DA-4")
        found = m.assign(
            [pay("S1", D(2026, 11, 1), 208.25,
                 purpose="206 Management fee Sample Lane 5 x 35"),
             pay("S2", D(2026, 11, 1), 208.25,
                 purpose="102 Management fee Example Road 5 x 35")],
            [a, b])
        self.assertEqual(found["S1"]["name"], "BT-B")
        self.assertEqual(found["S2"]["name"], "BT-A")

    def test_without_a_telling_purpose_a_tie_stays_open(self):
        a = txn("BT-A", D(2026, 11, 2), 100.0, text="unreadable")
        b = txn("BT-B", D(2026, 11, 2), 100.0, text="unreadable")
        found = m.assign([pay("S1", D(2026, 11, 1), 100.0, purpose="x1"),
                          pay("S2", D(2026, 11, 1), 100.0, purpose="x2")],
                         [a, b])
        self.assertEqual(found, {})

    def test_one_debit_is_never_given_to_two_orders(self):
        only = txn("BT-A", D(2026, 11, 2), 100.0, text="unreadable")
        found = m.assign([pay("S1", D(2026, 11, 1), 100.0),
                          pay("S2", D(2026, 11, 1), 100.0)], [only])
        self.assertEqual(found, {})

    def test_amount_iban_and_date_suffice_when_nothing_competes(self):
        only = txn("BT-A", D(2026, 11, 3), 1300.0, text="shortened by bank")
        found = m.assign([pay("S", D(2026, 11, 3), 1300.0,
                              purpose="Share of rents, love from home")],
                         [only])
        self.assertEqual(found["S"]["name"], "BT-A")

    def test_wrong_amount_wrong_payee_or_far_away_is_no_match(self):
        due = D(2026, 11, 1)
        for debit in (txn("BT-1", D(2026, 11, 2), 100.01, text="Rent"),
                      txn("BT-2", D(2026, 11, 2), 100.0, iban=OTHER,
                          text="Rent"),
                      txn("BT-3", D(2026, 10, 1), 100.0, text="Rent"),
                      txn("BT-4", D(2026, 11, 20), 100.0, text="Rent")):
            self.assertEqual(
                m.assign([pay("S", due, 100.0, purpose="Rent")], [debit]),
                {}, debit["name"])

    def test_a_debit_already_recorded_is_not_handed_out_again(self):
        debit = txn("BT-1", D(2026, 11, 2), 100.0, text="Rent")
        self.assertEqual(m.assign([pay("S", D(2026, 11, 1), 100.0,
                                       purpose="Rent")],
                                  [debit], taken={"BT-1"}), {})

    def test_an_end_to_end_id_settles_it_without_an_iban(self):
        debit = txn("BT-1", D(2026, 11, 2), 50.0, iban="",
                    text="EREF: KEF-TRF-2026-00009-1 something")
        found = m.assign([pay("T", D(2026, 11, 2), 50.0,
                              e2e="KEF-TRF-2026-00009-1")], [debit])
        self.assertEqual(found["T"]["name"], "BT-1")

    def test_a_named_debit_beats_an_anonymous_one(self):
        """The weak match must not take the debit that names someone else."""
        named = txn("BT-N", D(2026, 11, 2), 80.0, text="Invoice 4711")
        anon = txn("BT-X", D(2026, 11, 2), 80.0, text="")
        found = m.assign([pay("A", D(2026, 11, 2), 80.0, purpose="Other"),
                          pay("B", D(2026, 11, 2), 80.0,
                              purpose="Invoice 4711")], [named, anon])
        self.assertEqual(found["B"]["name"], "BT-N")
        self.assertEqual(found["A"]["name"], "BT-X")

    def test_a_collective_order_booked_as_one_sum_must_name_itself(self):
        total = txn("BT-S", D(2026, 11, 2), 300.0, iban="",
                    text="SAMMLER KEF-TRF-2026-00005")
        self.assertEqual(m.batch_booking("KEF-TRF-2026-00005", 300.0,
                                         D(2026, 11, 2), [total])["name"],
                         "BT-S")
        self.assertIsNone(m.batch_booking("KEF-TRF-2026-00006", 300.0,
                                          D(2026, 11, 2), [total]))

    def test_umlauts_and_spacing_do_not_matter(self):
        self.assertEqual(m.purpose_key("Nutzungsüberlassung  HD"),
                         m.purpose_key("NUTZUNGSÜBERLASSUNG HD"))


class TestFrappeSide(unittest.TestCase):

    def test_settled_after_every_import_and_daily(self):
        self.assertIn("_settle_executed_orders(kefiya_login)",
                      _read("utils", "auto_reconcile.py"))
        self.assertIn('"kefiya.utils.bank_execution.settle_executed"',
                      _read("hooks.py"))

    def test_settling_runs_before_the_reconciliation_switch(self):
        """Bookkeeping about our own orders must not wait for a setting
        about bookings."""
        body = _read("utils", "auto_reconcile.py").split(
            "def run_after_import(")[1]
        self.assertLess(body.index("_settle_executed_orders(kefiya_login)"),
                        body.index("auto_reconcile_after_import"))

    def test_only_bank_kept_standing_orders_are_moved_on(self):
        """Orders kept here move on when their transfer is placed."""
        source = _read("utils", "bank_execution.py")
        self.assertIn('"execution_mode": "Bank", "status": "Active"', source)

    def test_a_held_transfer_is_marked_sent_and_nothing_else(self):
        source = _read("utils", "bank_execution.py")
        body = source.split("def _mark_transfer_executed(")[1].split(
            "\ndef ")[0]
        self.assertIn("if doc.status != SCHEDULED:", body)
        self.assertIn('doc.db_set("status", SENT)', body)

    def test_the_date_lock_no_longer_blocks_a_status_change(self):
        body = _read("kefiya", "doctype", "kefiya_transfer",
                     "kefiya_transfer.py").split(
            "def on_update_after_submit(self):")[1].split(
            "\n    @frappe.whitelist()")[0]
        guarded = body.split(
            'if self.status in ("Sent", "Scheduled at Bank"):')[1][:300]
        self.assertIn('self.has_value_changed("execution_date")', guarded)


if __name__ == "__main__":
    unittest.main()
