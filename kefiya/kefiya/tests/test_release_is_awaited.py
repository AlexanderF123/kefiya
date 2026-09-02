# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""After a decoupled release, somebody has to ask the bank -- and write it down.

KEF-TRF-2026-00007, 02.09.2026, 16:50:47, read off the stored state:

  1. The Sparkasse accepted the order, passed the payee check, handed over
     a VoP-ID and asked for the release in the S-pushTAN app.
  2. kefiya parked the challenge -- correctly, see
     test_decoupled_release_survives -- and returned "tan_required".
  3. The box on screen said "follow the instructions in your banking app"
     and waited for kefiya_release_arrived. That event is sent by the
     statement fetch after ITS poll. The transfer path never polls, so the
     event never came, and nobody asked the bank whether the release had
     been given.
  4. Even the one way out -- the box's OK button, which resumes the parked
     dialog -- would have left the order "Due": no resume path ever marked
     a Kefiya Transfer sent. Only the original send did, and that had long
     returned.

  Result: no error, no result, an order that says "not sent" whether or
  not the money is gone. "Due" is the one state that invites a second send.

The rules asserted here:

  - The transfer path still does not poll inside the request that sent the
    order (that is what the bank refused, see the other suite). It asks in
    LATER requests, from the page: send_transfer_tan with an empty TAN.
  - The bank's answer to that is one of three, and the page acts on each:
    released, refused, or not yet.
  - A release that goes through marks the orders sent -- in the one place
    every sending path shares.
  - The box closes itself when the release lands, on the transfer path too.
"""

import os
import unittest

HIER = os.path.dirname(os.path.abspath(__file__))
WURZEL = os.path.dirname(os.path.dirname(HIER))


def _js(name):
    path = os.path.join(WURZEL, "public", "js", "controllers", name)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _py(*parts):
    with open(os.path.join(WURZEL, *parts), encoding="utf-8") as handle:
        return handle.read()


def _pyfunc(source, header):
    """One Python function, up to the next top-level def."""
    return source.split(header)[1].split("\ndef ")[0]


def _function(source, header):
    """The body of one JS function, up to the next one at the same indent."""
    tail = source.split(header)[1]
    end = tail.find("\n\tfunction ")
    if end < 0:
        end = tail.find("\n    function ")
    return tail[:end if end > 0 else len(tail)]


class TestThePageAsksTheBank(unittest.TestCase):

    def test_the_helper_exists_in_the_bundle(self):
        source = _js("tan_prompt.js")
        self.assertIn("kefiya.await_release = awaitRelease;", source)

    def test_it_asks_with_an_empty_tan_and_the_orders_it_belongs_to(self):
        body = _function(_js("tan_prompt.js"), "function awaitRelease(opts) {")
        self.assertIn('method: "kefiya.utils.client.send_transfer_tan"', body)
        self.assertIn('tan: ""', body)
        self.assertIn("transfer_names: JSON.stringify(names)", body)

    def test_it_acts_on_all_three_answers(self):
        body = _function(_js("tan_prompt.js"), "function awaitRelease(opts) {")
        self.assertIn('m.status === "submitted"', body)
        self.assertIn('m.status === "error"', body)
        # Anything else is "not yet": ask again, do not give up.
        self.assertIn("setTimeout(ask, every)", body)

    def test_it_gives_up_eventually_and_says_so(self):
        body = _function(_js("tan_prompt.js"), "function awaitRelease(opts) {")
        self.assertIn('finish("timeout")', body)

    def test_the_outbox_asks_on_a_decoupled_release(self):
        body = _function(_js("payment_outbox.js"),
                         "function reportSendResult(")
        self.assertIn('m.status === "tan_required"', body)
        self.assertIn("m.decoupled", body)
        self.assertIn("awaitRelease(login, names || [], count)", body)

    def test_the_outbox_names_the_orders_it_sent(self):
        body = _function(_js("payment_outbox.js"), "function handToBank(")
        self.assertIn("m.sent || names", body)

    def test_the_form_asks_too(self):
        source = _js("fints_transfer_flow.js")
        self.assertIn("msg.decoupled && kefiya.await_release", source)
        self.assertIn("names: [frm.doc.name]", source)

    def test_the_outbox_tells_the_user_when_it_gave_up(self):
        body = _function(_js("payment_outbox.js"), "function awaitRelease(")
        self.assertIn("online banking", body)
        self.assertIn("still marked as not sent here", body)


class TestTheServerAnswersTheQuestion(unittest.TestCase):

    def test_send_transfer_tan_knows_which_orders(self):
        source = _pyfunc(_py("utils", "client.py"), "def send_transfer_tan(")
        self.assertIn("transfer_names=None", source)
        self.assertIn("_mark_sent(docs, {}, _bank_holds_the_date(docs[0]))",
                      source)

    def test_not_yet_is_reported_not_swallowed(self):
        source = _pyfunc(_py("utils", "client.py"), "def send_transfer_tan(")
        self.assertIn('return {"status": "tan_required"', source)
        self.assertIn('return {"status": "submitted", "sent":', source)

    def test_an_empty_tan_takes_the_known_working_path(self):
        """The release box hands over None for a decoupled procedure and that
        path works. An empty string would be a new path, untested."""
        source = _pyfunc(_py("utils", "client.py"), "def send_transfer_tan(")
        self.assertIn("tan=tan or None", source)

    def test_resolve_tan_interaction_no_longer_answers_with_silence(self):
        source = _pyfunc(_py("utils", "client.py"),
                         "def resolve_tan_interaction(")
        self.assertIn('return {"status": "tan_required"', source)
        self.assertIn('return {"status": "submitted"', source)
        self.assertNotIn("        pass\n", source)


class TestOnePlaceWritesItDown(unittest.TestCase):

    def test_there_is_one_marker(self):
        self.assertIn("\ndef _mark_sent(docs, result, scheduled):",
                      _py("utils", "client.py"))

    def test_every_sending_path_uses_it(self):
        source = _py("utils", "client.py")
        self.assertEqual(source.count("_mark_sent("), 4,
                         "the definition and three callers: single send,"
                         " outbox batch, release of a parked challenge")

    def test_nobody_writes_sent_on_their_own(self):
        source = _py("utils", "client.py")
        marker = source.split("def _mark_sent(")[1].split("\ndef ")[0]
        self.assertIn('"Scheduled at Bank" if scheduled else "Sent"', marker)
        self.assertEqual(
            source.count('"Scheduled at Bank" if scheduled else "Sent"'), 1,
            "written in one place, so the release path cannot drift from"
            " the send path again")


class TestTheBoxClosesOnTheTransferPathToo(unittest.TestCase):

    def test_the_resume_tells_the_browser(self):
        source = _py("utils", "fints_tan_session.py")
        body = source.split("def _resume_and_answer_the_parked_tan(")[1]
        body = body.split("\n    def ")[0]
        self.assertIn("self._persist_fints_state()", body)
        self.assertIn("self._tell_the_browser_it_can_stop_waiting()", body)
        # After the state is cleared, not before: the box must not close on
        # a release that then failed to be written down.
        self.assertLess(body.index("self._persist_fints_state()"),
                        body.index("self._tell_the_browser_it_can_stop_waiting()"))

    def test_the_box_says_it_closes_by_itself(self):
        source = _js("tan_prompt.js")
        self.assertIn("This box closes by itself once the bank reports", source)
