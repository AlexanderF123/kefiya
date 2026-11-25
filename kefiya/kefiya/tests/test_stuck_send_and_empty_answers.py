# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Three things found on 18.11.2026.

* Pressing Send again while the bank waited for a release in its app gave
  "Transfer failed: A transfer for this document is already in progress."
* Every fetch of one bank came back empty from 16.11. on, and nothing said why.
* A booking whose counter account the bank names by number, not IBAN, was
  rejected by ERPNext and lost on every fetch.
"""

import os
import unittest


def _read(*parts):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), *parts)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _body(source, name):
    return source.split("def " + name + "(")[1].split("\ndef ")[0]


class TestASendStillUnderWay(unittest.TestCase):

    def setUp(self):
        self.client = _read("utils", "client.py")

    def test_both_send_paths_explain_instead_of_failing(self):
        single = _body(self.client, "submit_kefiya_transfer")
        self.assertIn("return _already_on_its_way(doc.kefiya_login,"
                      " transfer_name)", single)
        batch = _body(self.client, "send_transfer_outbox")
        self.assertIn("_already_on_its_way(kefiya_login,", batch)
        # The old refusal as code -- the docstring may still quote it.
        self.assertNotIn('_(\n            "A transfer for this document is'
                         ' already in progress."', self.client)

    def test_an_open_release_is_waited_for_again(self):
        body = _body(self.client, "_already_on_its_way")
        self.assertIn('"status": "tan_required", "decoupled": True', body)
        self.assertIn('"still_waiting": True', body)
        self.assertIn("stored_tan_state_decoupled", body)

    def test_the_pages_say_it(self):
        for path in (("public", "js", "controllers", "fints_transfer_flow.js"),
                     ("public", "js", "controllers", "payment_outbox.js")):
            self.assertIn("still_waiting", _read(*path))


class TestTheReleaseNoteIsNotRepeatedWhileWaiting(unittest.TestCase):

    def test_once_per_quarter_hour(self):
        body = _read("utils", "fints_tan_session.py").split(
            "def _note_release_request(")[1].split("\n    def ")[0]
        self.assertIn("ex=900, nx=True", body)
        self.assertIn("if attended and fresh:", body)


class TestAnEmptyAnswerIsWrittenDown(unittest.TestCase):

    def test_what_the_bank_said_goes_to_the_timeline(self):
        controller = _read("utils", "fints_controller.py")
        body = controller.split("def _note_empty_answer(")[1].split(
            "\n    def ")[0]
        self.assertIn("last_said", body)
        self.assertIn("note_on_login(", body)
        self.assertIn("ex=86400", body)
        self.assertIn("self._note_empty_answer(curr_doc.from_date,"
                      " curr_doc.to_date)", controller)


class TestANumberInTheIbanField(unittest.TestCase):

    def setUp(self):
        source = _read("utils", "import_bank_transaction.py")
        start = source.index("def iban_or_number(")
        end = source.index("\nclass ", start)
        namespace = {}
        exec("import re\n" + source[start:end], namespace)
        self.split = namespace["iban_or_number"]

    def test_a_valid_iban_stays_an_iban(self):
        self.assertEqual(self.split("DE89 9999 9999 0001 1111 11"),
                         ("DE89999999990001111111", None))

    def test_an_account_number_becomes_a_number(self):
        self.assertEqual(self.split("1234567890"), (None, "1234567890"))

    def test_a_wrong_checksum_is_not_an_iban(self):
        self.assertEqual(self.split("DE98370400440532013000"),
                         (None, "DE98370400440532013000"))

    def test_nothing_is_nothing(self):
        self.assertEqual(self.split(None), (None, None))

    def test_both_import_paths_use_it(self):
        source = _read("utils", "import_bank_transaction.py")
        self.assertEqual(source.count(
            "applicant_iban, kontonummer = iban_or_number(applicant_iban)"), 2)


class TestTheWaitIsVisible(unittest.TestCase):
    """18.11.2026: the bank's app asked for the release while the page
    showed nothing -- an eight-second alert, gone, and on a phone not even
    that."""

    def setUp(self):
        self.js = _read("public", "js", "controllers", "tan_prompt.js")
        self.body = self.js.split("function awaitRelease(opts) {")[1].split(
            "kefiya.await_release = awaitRelease;")[0]

    def test_a_box_stays_while_the_page_waits(self):
        self.assertIn("waitingBox(login, names, ceiling,", self.body)
        self.assertIn("waitBox.close()", self.body)

    def test_not_a_second_box_where_one_is_open(self):
        self.assertIn("(openBoxes[scope] || openBoxes[login]) ? null",
                      self.body)

    def test_the_box_says_what_and_how_long(self):
        box = self.js.split("function waitingBox(")[1]
        self.assertIn("The bank is waiting for your release in its app.",
                      box)
        self.assertIn("This page keeps asking for {0} more seconds.", box)


class TestARefusalIsNoError(unittest.TestCase):
    """19.11.2026: 13 Error Log entries a night for accounts that simply do
    not offer standing orders or dated transfers (9380)."""

    def test_the_bestand_refusal_counts_as_refused(self):
        body = _body(_read("utils", "client.py"), "_is_refused_by_the_bank")
        self.assertIn("isinstance(exc, BankRefusedQuery)", body)
        self.assertLess(body.index("BankRefusedQuery"),
                        body.index("from fints.exceptions import"))

    def test_the_refusal_keeps_the_banks_words(self):
        body = _body(_read("utils", "client.py"), "_optional_fetch")
        self.assertIn('getattr(exc, "said", None)', body)
        self.assertLess(body.index("_is_refused_by_the_bank(exc)"),
                        body.index("frappe.log_error("))


class TestTheEmptyAnswerIsReadWhereItArrives(unittest.TestCase):
    """20.11.2026: four empty answers, each noted as "(nothing recorded)"."""

    def test_the_statement_dialog_is_listened_to(self):
        controller = _read("utils", "fints_controller.py")
        raw = controller.split("def _get_transactions_raw(")[1].split(
            "\n    def ")[0]
        self.assertLess(raw.index("self._record_statement_answers(dialog)"),
                        # The MT940 fetch, now through the helper that
                        # keeps the pending block (25.11.2026).
                        raw.index("self._fetch_mt940_keeping_pending("))
        note = controller.split("def _note_empty_answer(")[1].split(
            "\n    def ")[0]
        self.assertLess(note.index('"_statement_lines"'),
                        note.index('"last_said"'))


class TestNotDueYetOffersToPayNow(unittest.TestCase):
    """23.11.2026: "is due on ... and is managed here" named a field to change
    by hand, in English, under "Transfer failed"."""

    def setUp(self):
        self.client = _read("utils", "client.py")

    def test_both_refusals_carry_the_way_out(self):
        for path in ("submit_kefiya_transfer", "send_transfer_outbox"):
            body = _body(self.client, path)
            self.assertIn('"not_due_yet": True', body)

    def test_pay_now_only_moves_the_date(self):
        body = _body(self.client, "pay_now")
        self.assertIn("doc.execution_date = nowdate()", body)
        self.assertIn("if not _not_due_yet(doc):", body)
        self.assertNotIn("submit_sepa_transfer", body)
        self.assertIn('ptype="submit" if doc.docstatus == 1', body)

    def test_the_pages_ask_first(self):
        form = _read("public", "js", "controllers", "fints_transfer_flow.js")
        offer = form.split("function kefiya_offer_pay_now(")[1]
        self.assertLess(offer.index("frappe.confirm("),
                        offer.index("kefiya.utils.client.pay_now"))
        page = _read("public", "js", "controllers", "payment_outbox.js")
        self.assertIn("m.not_due_yet", page)


class TestSendAlsoTakesOrdersDueLater(unittest.TestCase):
    """23.11.2026: approved orders kept here for a later day could not be
    sent today at all. Not a second button for it -- Send asks."""

    def setUp(self):
        self.page = _read("public", "js", "controllers", "payment_outbox.js")

    def test_no_second_button(self):
        self.assertNotIn('button("send_now"', self.page)
        self.assertIn('applicable("send").length + applicable("send_now").length',
                      self.page)

    def test_send_asks_first_then_the_ordinary_send(self):
        send = self.page.split("function send() {")[1].split("\n\tfunction ")[0]
        self.assertIn("bringLaterForward(later)", send)
        body = self.page.split("function bringLaterForward(later) {")[1].split(
            "\n\tfunction ")[0]
        self.assertLess(body.index("frappe.confirm("),
                        body.index("kefiya.utils.client.pay_now"))
        self.assertIn("load().then(function () { send(); })", body)

    def test_same_conditions_as_the_server(self):
        rule = self.page.split("kefiya.outbox_not_due_yet = function")[1][:500]
        for part in ("r.docstatus !== 1", "r.on_hold", "r.vop_pending",
                     '"Scheduled at Bank"', "!r.manage_due_date"):
            self.assertIn(part, rule)


class TestABankRefusalReadAsMissingBpdIsShown(unittest.TestCase):
    """23.11.2026: "could not be rebuilt" under an instant payment, with no
    word of what the bank had said."""

    def test_the_banks_lines_go_into_message_and_log(self):
        controller = _read("utils", "fints_controller.py")
        part = controller.split('title=_("Connection could not be rebuilt"))')[0]
        part = part[part.rindex("if not _is_missing_bank_parameters(exc):"):]
        self.assertIn('"last_said"', part)
        self.assertIn("frappe.log_error(", part)
        self.assertIn('_("What the bank said:")', part)
