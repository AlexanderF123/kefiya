# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Whose money leaves the account is not a choice on a form.

A colleague preparing a transfer saw "Brilu KG Mietkonto Sparkasse" as the
paying account and "axessio Hausverwaltung GmbH" as the company, and asked
whether that could be right. It could not: that account belongs to the
Brilu-Stiftung.

The field was filled only when it was still empty -- and a Company link picks
up the user's session default, so it almost never is. The wrong company then
simply stayed.

That is not a label. build_pain001_for() takes the ordering party's NAME from
the company and the ordering party's IBAN from the account, so a mismatch
sends an order that names one company and debits another.
"""

import os
import re
import unittest


def _app_path(*parts):
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), *parts)


def _read(*parts):
    with open(_app_path(*parts), encoding="utf-8") as handle:
        return handle.read()


DOCTYPE = ("kefiya", "doctype", "kefiya_transfer")


class TestTheCompanyFollowsTheAccount(unittest.TestCase):

    def _controller(self):
        return _read(*(DOCTYPE + ("kefiya_transfer.py",)))

    def test_it_is_no_longer_only_filled_when_empty(self):
        """The whole defect in one line."""
        source = self._controller()
        self.assertNotIn("if not self.company and self.kefiya_login:", source)
        self.assertIn("self.company = self.company_of_the_paying_account()",
                      source)

    def test_the_bank_account_is_the_authority(self):
        """It is the thing that holds the money; the login's own company is
        the fallback for a record that names none."""
        body = self._controller().split(
            "def company_of_the_paying_account(")[1].split("\n    def ")[0]
        self.assertIn('"Bank Account", login["bank_account"], "company"', body)
        self.assertIn('company or login.get("company")', body)

    def test_an_account_without_a_company_is_refused(self):
        """Rather than sending an order with no ordering party on it."""
        body = self._controller().split(
            "def company_of_the_paying_account(")[1].split("\n    def ")[0]
        self.assertIn("frappe.throw(", body)

    def test_the_form_cannot_diverge_either(self):
        """Policing a field the user can still set is second best; the field
        is fetched from the account and read-only."""
        import json
        meta = json.loads(_read(*(DOCTYPE + ("kefiya_transfer.json",))))
        company = [f for f in meta["fields"] if f["fieldname"] == "company"][0]
        self.assertEqual(company.get("fetch_from"), "kefiya_login.company")
        self.assertEqual(company.get("read_only"), 1)


class TestAnIbanIsShownInFours(unittest.TestCase):
    """DE27672500200009355367 is twenty-two characters with no landmarks --
    nobody checks that against a letter from the bank. In fours they do."""

    def test_the_display_rule_lives_in_one_place(self):
        source = _read("public", "js", "controllers", "iban_display.js")
        self.assertIn("kefiya.iban_pretty", source)
        self.assertIn('replace(/(.{4})/g, "$1 ")', source)

    def test_it_is_loaded_for_every_page_that_shows_one(self):
        bundle = _read("public", "js", "kefiya.bundle.js")
        self.assertIn('import "./controllers/iban_display";', bundle)

    def test_every_place_that_shows_an_iban_uses_it(self):
        for parts in (("public", "js", "controllers", "transfer_details.js"),
                      ("public", "js", "controllers", "payment_outbox.js"),
                      DOCTYPE + ("kefiya_transfer.js",)):
            self.assertIn("kefiya.iban_pretty", _read(*parts), parts[-1])

    def test_no_second_copy_of_the_rule_survives(self):
        """The outbox had its own; two copies drift."""
        outbox = _read("public", "js", "controllers", "payment_outbox.js")
        self.assertNotIn("function ibanPretty", outbox)

    def test_what_is_stored_stays_unbroken(self):
        """A space inside an IBAN is a rejected order, so the grouping is a
        display rule only -- the field handler still strips on entry."""
        form = _read(*(DOCTYPE + ("kefiya_transfer.js",)))
        self.assertIn('row.recipient_iban.replace(/[\\s-]/g, "").toUpperCase()',
                      form)
        self.assertIn("iban_column.formatter = function (value)", form,
                      "Grouping belongs in the column formatter, not in the "
                      "stored value.")


class TestTheFormSaysWhichAccountItIs(unittest.TestCase):
    """The name of an access does not tell two accounts of one bank apart, and
    says nothing about whose money it is."""

    def test_the_paying_account_is_described_in_full(self):
        form = _read(*(DOCTYPE + ("kefiya_transfer.js",)))
        self.assertIn("function kefiya_describe_paying_account(frm)", form)
        self.assertIn("account_iban", form)
        self.assertTrue(re.search(r"kefiya_describe_paying_account\(frm\);",
                                  form))

    def test_it_is_refreshed_when_the_account_changes(self):
        form = _read(*(DOCTYPE + ("kefiya_transfer.js",)))
        block = form.split("kefiya_login: function (frm) {")[1][:200]
        self.assertIn("kefiya_describe_paying_account(frm)", block)
