# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

import inspect
import unittest

from kefiya.kefiya.doctype.kefiya_transfer.kefiya_transfer import (
    is_valid_iban,
    normalize_iban,
)
from kefiya.utils import client
from kefiya.utils.fints_controller import FinTSController


class TestIbanValidation(unittest.TestCase):
    """With free recipient entry there is no invoice to check the account
    against, so the mod-97 checksum is the only automatic defence between a
    typo and a stranger's account."""

    def test_accepts_valid_ibans(self):
        for iban in [
            "DE89370400440532013000",   # documentation example
            "GB82WEST12345698765432",
            "FR1420041010050500013M02606",
        ]:
            self.assertTrue(is_valid_iban(iban), iban)

    def test_rejects_single_digit_typo(self):
        """One wrong digit must not pass -- this is the case that matters."""
        self.assertTrue(is_valid_iban("DE89370400440532013000"))
        self.assertFalse(is_valid_iban("DE89370400440532013001"))

    def test_rejects_transposed_characters(self):
        self.assertFalse(is_valid_iban("DE98370400440532013000"))

    def test_rejects_malformed_input(self):
        for bad in [None, "", "   ", "DE89", "XX00", "DE89-INVALID-!",
                    "1234567890123456", "D" * 40]:
            self.assertFalse(is_valid_iban(bad), repr(bad))

    def test_normalisation_is_tolerant_of_formatting(self):
        spaced = "DE89 3704 0044 0532 0130 00"
        self.assertEqual(normalize_iban(spaced), "DE89370400440532013000")
        self.assertTrue(is_valid_iban(spaced))
        self.assertTrue(is_valid_iban("de89 3704-0044 0532 0130 00"))


class TestCollectiveTransfer(unittest.TestCase):
    """Several payments must go out as one collective order (HKCCM), which the
    bank authorises with a single TAN, instead of one order -- and one TAN --
    per payment."""

    def test_control_sum_required_for_collective_order(self):
        source = inspect.getsource(FinTSController.submit_sepa_transfer)
        self.assertIn(
            "control_sum", source,
            "A collective order must carry a control sum; the bank checks the "
            "batch against it.",
        )
        self.assertIn(
            "multiple", source,
            "The collective-order flag must be forwarded to the library.",
        )

    def test_single_transfer_sends_no_batch_arguments(self):
        """Banks reject a control sum on an individual transfer, so the batch
        arguments may only be present for a genuine collective order."""
        source = inspect.getsource(FinTSController.submit_sepa_transfer)
        self.assertIn(
            'kwargs["multiple"] = True', source,
            "Batch arguments must be added conditionally, not passed always.",
        )

    def test_send_endpoint_gates_on_confirmation_and_permission(self):
        source = inspect.getsource(client.submit_kefiya_transfer)
        self.assertIn("cint(confirmed)", source)
        self.assertIn("has_permission", source)
        self.assertIn(
            'ptype="submit"', source,
            "Sending money is a submit-level action, not a write-level one.",
        )

    def test_send_requires_submitted_document(self):
        source = inspect.getsource(client.submit_kefiya_transfer)
        self.assertIn(
            "docstatus != 1", source,
            "A draft transfer must never reach the bank -- submit is what "
            "separates the person entering a transfer from the one releasing "
            "it.",
        )

    def test_send_is_not_repeatable(self):
        source = inspect.getsource(client.submit_kefiya_transfer)
        self.assertIn('doc.status == "Sent"', source)
        self.assertIn(
            "cache()", source,
            "A double click must not send real money twice.",
        )

    def test_unconfirmed_send_is_refused(self):
        result = client.submit_kefiya_transfer(
            transfer_name="irrelevant", user_scope="irrelevant"
        )
        self.assertEqual(result["status"], "error")


class TestTransferApprovalSeparation(unittest.TestCase):
    def test_submitting_does_not_send(self):
        """Approving a transfer must never move money as a side effect."""
        from kefiya.kefiya.doctype.kefiya_transfer import kefiya_transfer

        source = inspect.getsource(kefiya_transfer.KefiyaTransfer)
        self.assertNotIn(
            "submit_sepa_transfer", source,
            "The controller must not contact the bank; sending is a separate, "
            "explicitly confirmed action.",
        )
        self.assertIn(
            "def before_submit", source,
            "Submit should mark the transfer approved, nothing more.",
        )


class TestOutbox(unittest.TestCase):
    """The outbox collects orders and sends them together on one TAN.

    Its refusals matter more than its conveniences: a wrong batch debits the
    wrong account or pays twice, so each precondition aborts the whole send
    rather than quietly dropping or including a document.
    """

    def test_send_requires_confirmation(self):
        result = client.send_transfer_outbox(
            transfer_names=["KEF-TRF-0001"], user_scope="x"
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("not confirmed", result["message"].lower())

    def test_empty_selection_is_refused(self):
        result = client.send_transfer_outbox(
            transfer_names=[], user_scope="x", confirmed=1
        )
        self.assertEqual(result["status"], "error")

    def test_batch_refuses_mixed_accounts_already_at_build_time(self):
        """One pain.001 carries exactly one debtor; mixing would debit the
        wrong account."""
        from kefiya.kefiya.doctype.kefiya_transfer import kefiya_transfer

        source = inspect.getsource(kefiya_transfer.build_pain001_for)
        self.assertIn("same account", source)

        endpoint = inspect.getsource(client.send_transfer_outbox)
        self.assertIn("same account", endpoint)

    def test_batch_refuses_held_back_and_already_sent(self):
        source = inspect.getsource(client.send_transfer_outbox)
        self.assertIn(
            "doc.on_hold", source,
            "A held-back order must never ride along in a collective send.",
        )
        self.assertIn(
            'doc.status == "Sent"', source,
            "An already-sent order must not be paid a second time.",
        )
        self.assertIn(
            "docstatus != 1", source,
            "Unapproved orders must not reach the bank.",
        )

    def test_batch_marks_all_or_none_as_sent(self):
        """Leaving part of an accepted batch unsent invites paying it twice."""
        source = inspect.getsource(client.send_transfer_outbox)
        self.assertIn("for doc in docs:", source)
        self.assertIn('db_set("status", "Sent")', source)

    def test_hold_is_permitted_after_approval(self):
        """Holding changes when an order is sent, not what it says."""
        from kefiya.kefiya.doctype.kefiya_transfer import kefiya_transfer

        source = inspect.getsource(kefiya_transfer.KefiyaTransfer.set_hold)
        self.assertIn("docstatus != 1", source)
        self.assertIn('self.status == "Sent"', source)

    def test_hold_endpoint_checks_permission(self):
        source = inspect.getsource(client.set_transfer_hold)
        self.assertIn("has_permission", source)
        self.assertIn('ptype="submit"', source)
