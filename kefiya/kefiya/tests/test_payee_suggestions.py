# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""The recipient field suggests known payees -- which it never did.

The form has advertised it the whole time: "Known payees are suggested while
you type". The field called

    input.autocomplete({ source: names, minLength: 2 })

which is the jQuery UI widget. Frappe does not ship jQuery UI, so the call
landed on undefined, threw nothing, and did nothing. A comment beside it even
recorded the reason it had to be that way -- that a Frappe Autocomplete would
refuse an unknown name -- which is a reason for not using a control, not a
reason for calling one that is not there.

Two things had to be true for the fix, and both are checked here: the
suggestions must come from the app rather than from a Server Script stored on
one site, and a name that is not in the list must stay typeable, because a
transfer with no invoice behind it is what this document exists for.
"""

import inspect
import os
import unittest

from kefiya.utils import payee_check


def _controller(name):
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    with open(os.path.join(root, "public", "js", "controllers", name),
              encoding="utf-8") as handle:
        return handle.read()


class TestTheSuggestionsComeFromTheApp(unittest.TestCase):

    def test_there_is_an_endpoint(self):
        self.assertTrue(callable(payee_check.known_payees))

    def test_it_is_callable_from_the_desk(self):
        self.assertTrue(getattr(payee_check.known_payees,
                                "whitelisted", False))

    def test_it_is_gated_on_the_right_to_enter_a_transfer(self):
        """The answer enumerates payees and IBANs this company has paid.
        That is not something a reader without that right should be able to
        collect one guess at a time."""
        source = inspect.getsource(payee_check.known_payees)
        self.assertIn("has_permission", source)
        self.assertIn("throw=True", source)

    def test_it_reads_the_same_two_sources_as_the_check(self):
        """What is suggested and what is later judged must not disagree."""
        source = inspect.getsource(payee_check.known_payees)
        self.assertIn("Kefiya Transfer Item", source)
        self.assertIn("Bank Transaction", source)

    def test_it_answers_with_the_ibans_as_well(self):
        source = inspect.getsource(payee_check.known_payees)
        self.assertIn('"ibans"', source)

    def test_the_page_no_longer_asks_a_stored_script(self):
        body = _controller("transfer_form.js") + _controller("payee_check.js")
        self.assertNotIn("zk_payees", body)
        self.assertIn("kefiya.utils.payee_check.known_payees", body)


class TestAnUnknownNameStaysTypeable(unittest.TestCase):
    """The document exists for the transfer that has no invoice behind it. A
    control that refuses an unknown payee would refuse exactly that."""

    def test_the_recipient_is_still_a_free_field(self):
        body = _controller("transfer_form.js")
        recipient = body.split('fieldname: "recipient_name"')[0]
        self.assertTrue(recipient.rstrip().endswith('fieldtype: "Data",'),
                        "The recipient must stay a Data field.")

    def test_the_widget_that_does_not_exist_is_gone(self):
        body = _controller("transfer_form.js")
        self.assertNotIn(".autocomplete({", body)

    def test_the_suggestions_use_what_frappe_itself_uses(self):
        body = _controller("payee_check.js")
        self.assertIn("Awesomplete", body)

    def test_a_missing_widget_leaves_a_working_form(self):
        """No suggestions is a worse form, not a broken one."""
        body = _controller("payee_check.js")
        rule = body.split("kefiya.suggest = function")[1].split("\n};")[0]
        self.assertIn('typeof window.Awesomplete !== "function"', rule)


class TestPickingAPayeeOffersTheirIban(unittest.TestCase):
    """The half that saves the typing -- and the half that catches the swap,
    because an IBAN offered out of our own history is one we have paid."""

    def test_the_ibans_of_the_picked_payee_are_offered(self):
        body = _controller("transfer_form.js")
        self.assertIn("offerTheirIbans", body)

    def test_a_typed_iban_is_never_overwritten(self):
        """It is the one taken off the invoice in front of the person."""
        body = _controller("transfer_form.js")
        rule = body.split("const offerTheirIbans = function")[1] \
            .split("\n\t\t};")[0]
        self.assertIn(
            'if (kefiya.iban_plain(dialog.get_value("recipient_iban"))) return;',
            rule)

    def test_one_iban_is_filled_in_and_several_are_offered(self):
        body = _controller("transfer_form.js")
        rule = body.split("const offerTheirIbans = function")[1] \
            .split("\n\t\t};")[0]
        self.assertIn("ibans.length === 1", rule)
        self.assertIn("list.open()", rule)

    def test_the_check_is_run_again_on_what_was_picked(self):
        """Otherwise the verdict on screen would still judge what was typed
        before the pick."""
        body = _controller("transfer_form.js")
        rule = body.split("const offerTheirIbans = function")[1] \
            .split("\n\t\t};")[0]
        self.assertIn("checkPayee", rule)
