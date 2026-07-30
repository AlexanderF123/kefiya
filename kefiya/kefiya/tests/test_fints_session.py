# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

import inspect
import unittest

import frappe

from kefiya.utils import client, fints_controller
from kefiya.utils.fints_controller import FinTSController, fints_session


class TestSessionScope(unittest.TestCase):
    """A shared dialog must never outlive the work it belongs to.

    It lives on frappe.local, which is rebuilt for every request and every
    background job, so a leaked session cannot reach the next one. Inside a
    request it still has to clean up after itself.
    """

    def test_session_is_cleared_afterwards(self):
        self.assertIsNone(fints_controller._active_session())
        with fints_session():
            self.assertIsNotNone(fints_controller._active_session())
        self.assertIsNone(fints_controller._active_session())

    def test_session_is_cleared_after_an_error(self):
        try:
            with fints_session():
                raise ValueError("fetch blew up")
        except ValueError:
            pass
        self.assertIsNone(fints_controller._active_session())

    def test_nesting_joins_instead_of_replacing(self):
        with fints_session():
            outer = fints_controller._active_session()
            with fints_session():
                self.assertIs(fints_controller._active_session(), outer)
            # The inner block must not have torn the session down.
            self.assertIs(fints_controller._active_session(), outer)

    def test_the_session_lives_on_frappe_local(self):
        source = inspect.getsource(fints_controller.fints_session)
        self.assertIn("frappe.local", source)


class TestAccessKey(unittest.TestCase):
    """One dialog may serve one bank access -- never two."""

    def _login(self, blz, fints_login):
        return frappe._dict({"blz": blz, "fints_login": fints_login})

    def test_same_access_shares_a_key(self):
        self.assertEqual(
            fints_controller._access_key(self._login("67092300", "u1")),
            fints_controller._access_key(self._login("67092300", "u1")),
        )

    def test_two_contracts_at_one_bank_do_not(self):
        """The BLZ alone would merge them and send one contract's requests
        over the other's credentials."""
        self.assertNotEqual(
            fints_controller._access_key(self._login("67092300", "u1")),
            fints_controller._access_key(self._login("67092300", "u2")),
        )

    def test_incomplete_credentials_are_never_grouped(self):
        self.assertIsNone(fints_controller._access_key(
            self._login(None, "u1")))
        self.assertIsNone(fints_controller._access_key(
            self._login("67092300", None)))


class TestDialogReuse(unittest.TestCase):
    """Every command used to open its own dialog: handshake, authentication,
    one command, HKEND. The handshake costs several round trips, the data
    costs one -- which is why a fetch of 48 accounts took twelve minutes."""

    def test_reads_go_through_the_shared_session(self):
        source = inspect.getsource(fints_controller)
        body = source[source.index("class FinTSController"):]
        # The money paths deliberately keep their own dialog.
        self.assertEqual(
            body.count("with self.fints_connection:"), 2,
            "Only submit_sepa_transfer and submit_sepa_debit may open their "
            "own dialog; every read must use client_session().",
        )
        self.assertGreaterEqual(body.count("with self.client_session():"), 10)

    def test_money_paths_are_excluded(self):
        for method in (FinTSController.submit_sepa_transfer,
                       FinTSController.submit_sepa_debit):
            self.assertIn(
                "with self.fints_connection:", inspect.getsource(method),
                "A transfer parks the dialog on a TAN request; freezing a "
                "dialog a surrounding fetch is still using would break it.",
            )

    def test_an_open_dialog_is_joined_not_reopened(self):
        source = inspect.getsource(FinTSController.client_session)
        self.assertIn("if conn._standing_dialog:", source)
        self.assertLess(
            source.index("if conn._standing_dialog:"),
            source.index("conn.__enter__()"),
            "Entering a client that already has a standing dialog raises "
            "'Cannot double __enter__'.",
        )

    def test_the_session_closes_what_it_opened(self):
        source = inspect.getsource(fints_controller.fints_session)
        self.assertIn("conn.__exit__(None, None, None)", source)
        self.assertIn(
            "finally:", source,
            "The dialog has to be closed on the error path as well.",
        )
        self.assertIn(
            "except Exception:", source,
            "A bank that dropped the connection must not turn into a second "
            "exception on the way out.",
        )


class TestConnectionSharing(unittest.TestCase):
    """Inside a session the logins of one access share a client, so a second
    account of the same bank costs one command instead of a handshake."""

    def _source(self):
        return inspect.getsource(
            FinTSController._FinTSController__init_fints_connection)

    def test_sharing_only_happens_inside_a_session(self):
        source = self._source()
        self.assertIn("_active_session()", source)
        self.assertIn(
            "if access and access in session", source,
            "Outside a session nothing may be shared -- behaviour has to stay "
            "exactly as it was.",
        )

    def test_a_shared_client_is_registered_for_the_access(self):
        source = self._source()
        self.assertIn('session["connections"][access] = self.fints_connection',
                      source)

    def test_a_pending_tan_is_not_resumed_inside_an_open_dialog(self):
        """resume_dialog() refuses to run inside a standing dialog."""
        source = inspect.getsource(FinTSController.__init__)
        self.assertIn("not self.fints_connection._standing_dialog", source)


class TestRetireOnFailure(unittest.TestCase):
    """With one dialog per command, a broken dialog died with the command.
    Shared, every later command in the session would inherit it -- one failure
    would take down the rest of the bank access."""

    def test_a_failed_command_retires_the_connection(self):
        source = inspect.getsource(FinTSController.client_session)
        self.assertIn("_retire_connection(session, conn)", source)
        self.assertIn(
            "raise", source,
            "Retiring must not swallow the failure.",
        )

    def test_an_unsupported_segment_keeps_the_dialog(self):
        """Decided from the stored BPD without touching the dialog -- and it
        is the common case: twelve of them in one collective run."""
        source = inspect.getsource(FinTSController.client_session)
        self.assertIn("FinTSUnsupportedOperation", source)
        self.assertIn("if not (FinTSUnsupportedOperation", source)

    def test_a_parked_dialog_is_removed_but_not_ended(self):
        source = inspect.getsource(fints_controller._retire_connection)
        self.assertIn('getattr(dialog, "paused", False)', source)
        self.assertIn(
            "return", source,
            "A TAN request parks the dialog for the user to release later; "
            "ending it would throw that away.",
        )

    def test_a_retired_connection_leaves_the_pool(self):
        source = inspect.getsource(fints_controller._retire_connection)
        self.assertIn('session["connections"].pop(access, None)', source)
        self.assertIn('session["open"].remove(conn)', source)


class TestFetchGroup(unittest.TestCase):
    """One access, one dialog, every account of it."""

    def _source(self):
        return inspect.getsource(client.fetch_group)

    def test_the_group_runs_inside_one_session(self):
        self.assertIn("with fints_session():", self._source())

    def test_one_failure_does_not_abandon_the_rest(self):
        source = self._source()
        self.assertIn("except Exception as exc:", source)
        self.assertIn(
            "failed[name]", source,
            "Giving up on the group would abandon thirty accounts over one.",
        )

    def test_duplicates_cannot_import_twice(self):
        source = self._source()
        self.assertIn(
            "dict.fromkeys", source,
            "The same login twice would fetch and import it twice.",
        )

    def test_a_single_fetch_also_shares_its_dialog(self):
        """Five retrievals per login used to mean five dialogs."""
        self.assertIn("with fints_session():",
                      inspect.getsource(client.fetch_all))
