# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Pay an executed transfer once more, from the booking it left.

Asked for on 23.11.2026: from the finance overview or the account
statement, put the data of a booking that went out into a new transfer.
"""

import os
import unittest


def _read(*parts):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), *parts)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class TestTheServerSide(unittest.TestCase):

    def setUp(self):
        source = _read("utils", "transaction_actions.py")
        self.body = source.split("def transfer_again(")[1].split("\ndef ")[0]

    def test_only_an_outgoing_booking(self):
        self.assertIn('amount = flt(txn.get("withdrawal"))', self.body)
        self.assertIn("if amount <= 0:", self.body)

    def test_nothing_is_created_or_sent(self):
        self.assertNotIn(".insert(", self.body)
        self.assertNotIn("submit", self.body.replace('"submit"', ""))

    def test_it_needs_both_rights(self):
        self.assertIn('"Bank Transaction", ptype="read"', self.body)
        self.assertIn('"Kefiya Transfer", ptype="create"', self.body)

    def test_a_fingerprint_stays_out_of_the_purpose(self):
        self.assertIn("_FINGERPRINT.match(reference)", self.body)


class TestWhereItIsOffered(unittest.TestCase):

    def test_the_form_of_a_booking(self):
        js = _read("public", "js", "bank_transaction.js")
        self.assertIn('frm.add_custom_button(__("Transfer again")', js)
        self.assertIn("frm.doc.withdrawal > 0", js)

    def test_every_row_the_shared_menu_knows(self):
        js = _read("public", "js", "controllers", "transfer_again.js")
        self.assertIn('window.axActions.register("Bank Transaction"', js)
        self.assertIn('frappe.model.get_new_doc("Kefiya Transfer")', js)
        self.assertNotIn("submit_kefiya_transfer", js)
        bundle = _read("public", "js", "kefiya.bundle.js")
        self.assertIn('import "./controllers/transfer_again";', bundle)
