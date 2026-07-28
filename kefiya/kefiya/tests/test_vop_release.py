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

    def test_release_is_never_automatic(self):
        """No code path may approve a VoP response on its own."""
        import kefiya.utils.fints_controller as fc

        source = inspect.getsource(fc)
        approvals = source.count("approve_vop_response(")
        self.assertEqual(
            approvals, 1,
            "approve_vop_response must be called from exactly one place "
            "(approve_pending_vop), which is reachable only after an explicit "
            "human confirmation.",
        )
