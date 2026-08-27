# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""The branch that turns "3945" into a challenge somebody can answer.

The rule itself takes a response and the segment it was sent with, and says
whether the bank refused to release the order without the payee check being
confirmed. No bank, no library, no site -- which is the point: this decides
what happens to a payment, and a rule that can only be exercised against a
live bank is a rule nobody exercises.

The rest of fints_vop is a copy of a library method with one branch added.
What can be asserted about a copy is that it knows which release it was taken
from and refuses to run against another one, and that is asserted here from
the source text.

WHAT THIS CANNOT CHECK, so that nobody reads it as covered: the imports in
_pieces() only resolve where python-fints is installed, which is a bench and
not this suite. A wrong module path there fails silently in exactly the worst
way -- _pieces() answers None, the guard reports "shape has moved", and the
branch is dead code that looks installed. It happened once already: PSRD1 was
imported from fints.formals, where it is not; it lives in fints.segments.auth.
It was caught by listing the pieces against the installed library before
shipping, and that check is the only thing that catches it.
"""

import os
import unittest

from kefiya.utils.fints_vop import (CONFIRMATION_DEMANDED,
                                    DEFAULT_POLL_SECONDS,
                                    demands_confirmation, poll_pause,
                                    still_checking, verdict_of)


class Line:
    def __init__(self, code):
        self.code = code


class Answer:
    """The shape python-fints hands back: responses(segment) -> lines."""

    def __init__(self, lines, explode=False):
        self._lines = lines
        self._explode = explode

    def responses(self, segment):
        if self._explode:
            raise RuntimeError("a response this cannot read")
        return self._lines


class TestTheBankAsksForTheConfirmation(unittest.TestCase):

    def test_3945_is_the_ask(self):
        self.assertTrue(demands_confirmation(
            Answer([Line("3040"), Line("3945")]), object()))

    def test_the_ordinary_answers_are_not(self):
        """0030 and 3955 are TAN requests and the library already handles
        them; 3050 is the commonest remark a German bank makes about a
        transfer. Treating any of them as a payee question would park a
        payment that was going through."""
        for code in ("0010", "0030", "3050", "3955", "9010"):
            self.assertFalse(
                demands_confirmation(Answer([Line(code)]), object()), code)

    def test_an_empty_answer_is_not_the_ask(self):
        self.assertFalse(demands_confirmation(Answer([]), object()))

    def test_a_response_it_cannot_read_answers_no(self):
        """Then the order takes exactly the path it took before this module
        existed. Guessing "yes" would park a payment on a parse error."""
        self.assertFalse(
            demands_confirmation(Answer([], explode=True), object()))

    def test_the_code_is_the_one_the_bank_sent(self):
        self.assertEqual(CONFIRMATION_DEMANDED, "3945")


class TestACopyKnowsWhatItIsACopyOf(unittest.TestCase):

    def _source(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))), "utils", "fints_vop.py")
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def test_it_names_the_release_it_was_taken_from(self):
        self.assertIn('KNOWN_GOOD = "5.0.0b1"', self._source())

    def test_another_release_gets_the_library_method(self):
        """A stale copy of a payment path is worse than a missing feature."""
        source = self._source()
        self.assertIn("if installed_version() != KNOWN_GOOD:", source)
        self.assertIn('return parts["base"]', source)

    def test_a_moved_library_shape_gets_the_library_method_too(self):
        source = self._source()
        self.assertIn("if not hasattr(FinTS3PinTanClient, name):", source)
        self.assertIn("return None", source)

    def test_building_the_client_never_raises(self):
        """A bank connection must not fail over an optional branch."""
        source = self._source()
        body = source[source.index("def client_class("):
                      source.index("def _note(")]
        self.assertIn("except Exception:", body)
        self.assertIn("frappe.log_error", body)

    def test_it_says_out_loud_why_it_cannot_send_twice(self):
        """The only question that matters about a change on the payment path.
        3945 means the bank did not release the order, so turning that into a
        parked challenge cannot send anything a second time -- and the
        approval that follows is a person's deliberate act."""
        self.assertIn("WHY THIS CANNOT SEND TWICE", self._source())


class Evpe:
    def __init__(self, result=None):
        self.result = result


class Hivpp:
    """What the bank hands back. Three shapes turn up in practice."""

    def __init__(self, polling_id=None, wait_for_seconds=None, inner=None,
                 report=None, vop_id=None):
        self.polling_id = polling_id
        self.wait_for_seconds = wait_for_seconds
        self.vop_single_result = inner
        self.payment_status_report = report
        self.vop_id = vop_id


class TestTheCheckThatIsNotFinishedYet(unittest.TestCase):
    """The Volksbank answers asynchronously, and the first live transfer is
    what found it: polling id, a wait, and no verdict. Parking that produced
    a challenge nobody could release -- HKVPA carries the VoP-ID and there
    was none."""

    def test_a_polling_id_without_a_verdict_means_ask_again(self):
        self.assertTrue(still_checking(
            Hivpp(polling_id=b"587d03b8", wait_for_seconds=2)))

    def test_a_verdict_ends_the_asking(self):
        for code in ("RCVC", "RVMC", "RVNM", "RVNA"):
            self.assertFalse(still_checking(
                Hivpp(polling_id=b"587d03b8", inner=Evpe(code))), code)

    def test_a_batch_report_ends_the_asking(self):
        """A collective order is answered as a payment status report, not as
        a single result. Asking again for it would never stop."""
        self.assertFalse(still_checking(
            Hivpp(polling_id=b"587d03b8", report=b"<xml/>")))

    def test_no_polling_id_is_not_something_to_ask_about(self):
        self.assertFalse(still_checking(Hivpp(inner=Evpe(None))))
        self.assertFalse(still_checking(None))
        self.assertFalse(still_checking(object()))

    def test_the_verdict_is_read_out_of_the_inner_group(self):
        self.assertEqual(verdict_of(Hivpp(inner=Evpe("RVMC"))), "RVMC")
        self.assertEqual(verdict_of(Hivpp()), "")
        self.assertEqual(verdict_of(None), "")
        self.assertEqual(verdict_of("kaputt"), "")

    def test_the_bank_names_the_pause(self):
        self.assertEqual(poll_pause(Hivpp(wait_for_seconds=2)), 2.0)

    def test_an_absurd_pause_is_brought_back_into_range(self):
        """Neither a busy loop nor a request nobody waits out."""
        self.assertEqual(poll_pause(Hivpp(wait_for_seconds=0)),
                         float(DEFAULT_POLL_SECONDS))
        self.assertEqual(poll_pause(Hivpp(wait_for_seconds=900)), 10.0)
        self.assertEqual(poll_pause(Hivpp(wait_for_seconds=-5)),
                         float(DEFAULT_POLL_SECONDS))
        self.assertEqual(poll_pause(Hivpp(wait_for_seconds="zwei")),
                         float(DEFAULT_POLL_SECONDS))

    def test_the_copy_waits_before_it_decides(self):
        """Asserted from the source: the decision must not be taken on the
        first answer, and an unfinished check must park nothing."""
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))), "utils", "fints_vop.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("hivpp = self._await_vop_result(", source)
        self.assertIn("if not still_checking(hivpp) and (", source)
        self.assertIn("waited < POLL_LIMIT_SECONDS", source)
