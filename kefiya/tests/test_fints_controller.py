# -*- coding: utf-8 -*-
# Copyright (c) 2026, phamos GmbH and contributors
# For license information, please see license.txt

from unittest.mock import MagicMock, patch

import frappe
from fints.client import NeedTANResponse
from fints.exceptions import FinTSConnectionError, FinTSSCARequiredError
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate

from kefiya.utils import fints_controller, fints_controller_legacy
from kefiya.utils.fints_controller import FetchTanRequired
from kefiya.utils.fints_controller_legacy import TanAuthenticationRequired

CONTROLLERS = (fints_controller.FinTSController, fints_controller_legacy.FinTSController)


def make_controller(cls):
    """Build a controller without its __init__, which logs in to the bank."""
    controller = cls.__new__(cls)
    controller.kefiya_login = frappe._dict(account_iban="DE02120300000000202051")
    controller.fints_connection = MagicMock()
    controller.get_fints_account_by_iban = MagicMock()
    controller.interactive = MagicMock()
    return controller


class TestFetchTanRequired(FrappeTestCase):
    def test_tan_on_fetch_raises_clear_error(self):
        start = add_days(getdate(), -120)
        for cls in CONTROLLERS:
            with self.subTest(controller=cls.__module__):
                controller = make_controller(cls)
                controller.fints_connection.get_transactions.return_value = MagicMock(
                    spec=NeedTANResponse
                )
                with self.assertRaises(FetchTanRequired):
                    controller.get_fints_transactions(start, add_days(getdate(), -1))

    def test_sca_required_error_on_fetch_raises_clear_error(self):
        start = add_days(getdate(), -120)
        for cls in CONTROLLERS:
            with self.subTest(controller=cls.__module__):
                controller = make_controller(cls)
                controller.fints_connection.get_transactions.side_effect = (
                    FinTSSCARequiredError("SCA required")
                )
                with self.assertRaises(FetchTanRequired):
                    controller.get_fints_transactions(start, add_days(getdate(), -1))

    def test_import_passes_tan_error_through_unwrapped(self):
        for cls in CONTROLLERS:
            with self.subTest(controller=cls.__module__):
                controller = make_controller(cls)
                controller.get_fints_transactions = MagicMock(
                    side_effect=FetchTanRequired("TAN needed")
                )
                with patch("frappe.get_doc"), self.assertRaises(FetchTanRequired):
                    controller.import_fints_transactions("KEFIYA-IMPORT-TEST")


# What fints raises when DKB rejects HKSPA, shortened
DKB_REJECTION = (
    "Error response: fints.message.FinTSInstituteMessage([...responses=["
    "fints.formals.Response(code='9800', reference_element=None, text='Dialog abgebrochen.'), "
    "fints.formals.Response(code='9210', reference_element=None, text='Auftrag abgelehnt')]"
)


class TestLegacyTanAuthenticationRequired(FrappeTestCase):
    def get_accounts(self, side_effect):
        controller = make_controller(fints_controller_legacy.FinTSController)
        controller.fints_connection.get_sepa_accounts.side_effect = side_effect
        controller._FinTSController__get_fints_accounts()

    def test_rejected_account_list_points_to_settings(self):
        with self.assertRaises(TanAuthenticationRequired):
            self.get_accounts(Exception(DKB_REJECTION))
        primary_action = frappe.message_log[-1]["primary_action"]
        self.assertEqual(primary_action["args"], ["Form", "Kefiya Settings"])

    def test_http_400_on_account_list_points_to_settings(self):
        with self.assertRaises(TanAuthenticationRequired):
            self.get_accounts(FinTSConnectionError("Bad status code 400"))

    def test_failed_account_list_skips_the_dialog_end(self):
        # fints would send HKEND on exit; it fails too and hides the message
        for error in (FinTSConnectionError("Bad status code 400"), Exception("code='9942'")):
            with self.subTest(error=str(error)):
                controller = make_controller(fints_controller_legacy.FinTSController)
                controller.fints_connection.get_sepa_accounts.side_effect = error
                with self.assertRaises(frappe.ValidationError):
                    controller._FinTSController__get_fints_accounts()
                self.assertFalse(controller.fints_connection._standing_dialog.open)

    def test_sca_required_error_points_to_settings(self):
        with self.assertRaises(TanAuthenticationRequired):
            self.get_accounts(FinTSSCARequiredError("SCA required"))

    def test_tan_at_dialog_start_points_to_settings(self):
        controller = make_controller(fints_controller_legacy.FinTSController)
        controller.fints_connection.init_tan_response = MagicMock(spec=NeedTANResponse)
        with self.assertRaises(TanAuthenticationRequired):
            controller._FinTSController__init_tan_processing()

    def test_other_errors_keep_the_bank_message(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.get_accounts(Exception("code='9942' PIN falsch"))
        self.assertNotIsInstance(ctx.exception, TanAuthenticationRequired)
