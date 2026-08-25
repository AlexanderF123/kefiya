# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""A parked TAN challenge must not outlive its usefulness.

The challenge is kept so a release given in the banking app still finds
something to unlock after the request that asked for it has ended. Nothing
expired it, though -- and an unreleased challenge is not inert: every later
connection replays it, the bank answers without a TAN status, and fints raises.
The raise ends the connection attempt, so one challenge nobody released in July
left an account unable to send anything in August.

These tests pin the shelf life down. The replay itself needs a bank and is
covered by hand; what is testable is when we stop trying.
"""

import unittest
from unittest.mock import patch

from frappe.utils import add_to_date, now_datetime

from kefiya.utils.fints_controller import (
    PARKED_CHALLENGE_MAX_AGE_HOURS,
    FinTSController,
)


class Login:
    """Just enough Kefiya Login for the age check."""

    def __init__(self, tan_state_updated):
        self.tan_state_updated = tan_state_updated
        self.stored_tan_blob = b"challenge"
        self.stored_dialog_blob = b"dialog"
        self.stored_tan_state_decoupled = 1
        self.saved = False

    def save(self):
        self.saved = True


def controller(login):
    """A controller without __init__ -- constructing one talks to a bank."""
    instance = FinTSController.__new__(FinTSController)
    instance.kefiya_login = login
    return instance


class TestParkedChallengeExpiry(unittest.TestCase):
    def test_a_fresh_challenge_is_still_worth_replaying(self):
        login = Login(add_to_date(now_datetime(), hours=-1))
        self.assertFalse(
            controller(login)._FinTSController__parked_challenge_is_stale()
        )

    def test_a_challenge_from_last_month_is_not(self):
        login = Login(add_to_date(now_datetime(), days=-15))
        self.assertTrue(controller(login)._FinTSController__parked_challenge_is_stale())

    def test_the_boundary_belongs_to_the_challenge(self):
        """Exactly at the limit it still gets its chance."""
        login = Login(
            add_to_date(now_datetime(), hours=-PARKED_CHALLENGE_MAX_AGE_HOURS)
        )
        self.assertFalse(
            controller(login)._FinTSController__parked_challenge_is_stale()
        )

    def test_without_a_timestamp_it_counts_as_old(self):
        """State from before the field existed. Nothing says it is fresh."""
        self.assertTrue(
            controller(Login(None))._FinTSController__parked_challenge_is_stale()
        )

    def test_discarding_clears_all_three_fields_and_saves(self):
        login = Login(add_to_date(now_datetime(), days=-15))
        controller(login)._FinTSController__discard_parked_challenge()

        self.assertIsNone(login.stored_tan_blob)
        self.assertIsNone(login.stored_dialog_blob)
        self.assertIsNone(login.stored_tan_state_decoupled)
        self.assertTrue(
            login.saved, "a discarded challenge that is not written stays parked"
        )

    def test_the_client_state_is_left_alone(self):
        """Discarding must not push a broken session onto the sibling logins."""
        login = Login(add_to_date(now_datetime(), days=-15))
        instance = controller(login)

        with patch.object(
            FinTSController, "_FinTSController__persist_fints_state"
        ) as persist:
            instance._FinTSController__discard_parked_challenge()

        persist.assert_not_called()
