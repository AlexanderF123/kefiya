# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

import inspect
import unittest

from kefiya.utils import client
from kefiya.utils.fints_controller import FinTSController


class TestVopRelease(unittest.TestCase):
    """Verification of Payee: the bank could not confirm that the payee name
    belongs to the IBAN. Kefiya refuses such a transfer and parks it. Releasing
    it is the one path that lets money leave against the bank's warning, so it
    is gated the same way the transfer itself is.
    """

    def test_release_requires_explicit_confirmation(self):
        """Unconfirmed calls must not reach the bank.

        A VoP mismatch is exactly the signature of a payment diversion, so it
        must never be waved through by a caller that simply omits the flag.
        """
        result = client.approve_vop_transfer(
            kefiya_login="irrelevant", user_scope="irrelevant"
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("not confirmed", result["message"].lower())

    def test_release_checks_permission_and_confirmation(self):
        source = inspect.getsource(client.approve_vop_transfer)
        self.assertIn(
            "has_permission", source,
            "Releasing a flagged payee must gate on write rights for the "
            "paying Kefiya Login.",
        )
        self.assertIn(
            "cint(confirmed)", source,
            "Releasing a flagged payee must require an explicit confirmation.",
        )

    def test_mismatch_is_parked_not_discarded(self):
        """Without persisting the challenge the transfer is a dead end."""
        source = inspect.getsource(FinTSController.submit_sepa_transfer)
        self.assertIn(
            "_persist_vop_state", source,
            "A VoP mismatch must be parked so a reviewer can release it; "
            "discarding it forces the whole transfer to be restarted.",
        )

    def test_challenge_is_consumed_on_release(self):
        """An approved challenge must not be replayable."""
        source = inspect.getsource(FinTSController.approve_pending_vop)
        self.assertIn(
            "clear_vop_state", source,
            "The parked challenge must be cleared when released, so an "
            "approval cannot be replayed from a stale dialog.",
        )

    def test_only_two_places_can_confirm_the_check(self):
        """And each of them has to have a reason.

        One is the reviewer's own act; the other is the narrow rule in
        vop_rule, which confirms only a full match or a payee somebody already
        approved. A third caller would be an approval with no reason at all,
        which is what this counts.
        """
        import kefiya.utils.fints_controller as fc

        source = inspect.getsource(fc)
        self.assertEqual(
            source.count("approve_vop_response("), 2,
            "approve_vop_response must be called from exactly two places: "
            "approve_pending_vop (a human said yes) and "
            "_release_vop_without_asking (the bank confirmed the match, or a "
            "human said yes to this payee before).",
        )

    def test_confirming_without_a_human_asks_the_rule_first(self):
        """The rule is in vop_rule and is what makes this defensible."""
        source = inspect.getsource(FinTSController._release_vop_without_asking)
        self.assertIn("vop_rule.needs_a_human(", source)
        self.assertIn("return None", source)
        self.assertIn(
            "accepted_payee.was_accepted(", source,
            "A remembered decision is what spares the reviewer the second "
            "question; without this lookup nothing is ever remembered.",
        )

    def test_a_parked_order_still_needs_the_human(self):
        """The auto-confirm must not swallow the parking branch."""
        source = inspect.getsource(FinTSController.submit_sepa_transfer)
        self.assertIn("_release_vop_without_asking(response, payee)", source)
        self.assertIn("_persist_vop_state(response, vop, payment_reference", source)

    def test_the_reviewers_decision_is_written_down(self):
        """Otherwise they are asked the same question every month, which is
        the rubber stamp this whole feature exists to remove."""
        source = inspect.getsource(FinTSController.approve_pending_vop)
        self.assertIn("accepted_payee.remember(", source)
        self.assertIn(
            "parked = self._parked_payee()",
            inspect.getsource(FinTSController.approve_pending_vop),
            "The payee has to be read before clear_vop_state drops it.",
        )
        before = source.index("parked = self._parked_payee()")
        cleared = source.index("self.kefiya_login.clear_vop_state()")
        self.assertLess(
            before, cleared,
            "Reading it afterwards would remember nothing at all -- the same "
            "reviewer would be asked the same question next month.")
