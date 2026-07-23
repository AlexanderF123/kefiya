# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Tests for the automatic incoming-mail acknowledgment (FEAT-11901).

The pure helpers are tested without a site; the handler flow is tested with
mocked frappe accessors so the decision logic (shadow mode, duplicate guard,
kill switch, daily limit) is covered even in environments without a bench
site."""

import unittest
from unittest import mock

from kefiya.utils import autoreply


class TestAutoReplyHelpers(unittest.TestCase):
    def test_normalize_sender_extracts_bare_address(self):
        self.assertEqual(
            autoreply.normalize_sender('"Max Mieter" <Max.Mieter@Example.COM>'),
            "max.mieter@example.com",
        )
        self.assertEqual(
            autoreply.normalize_sender("  mieter@example.com "),
            "mieter@example.com",
        )
        self.assertEqual(autoreply.normalize_sender(None), "")

    def test_unsafe_senders_are_rejected(self):
        for sender in (
            "no-reply@portal.de",
            "noreply@bank.de",
            "MAILER-DAEMON@mx.example.com",
            "postmaster@example.com",
            "bounce-1234@lists.example.com",
            "notifications@github.com",
            "",
            "not-an-address",
        ):
            self.assertTrue(autoreply.is_unsafe_sender(sender), sender)
        self.assertFalse(autoreply.is_unsafe_sender("max.mieter@example.com"))

    def test_case_key_per_sender_and_case(self):
        with_ref = autoreply.case_key("a@b.de", "Issue", "ISS-0001")
        self.assertIn("Issue", with_ref)
        self.assertIn("ISS-0001", with_ref)
        # a different case for the same sender must yield a different key
        self.assertNotEqual(
            with_ref, autoreply.case_key("a@b.de", "Issue", "ISS-0002")
        )
        # without a reference the key collapses onto the sender
        self.assertEqual(
            autoreply.case_key("a@b.de", None, None),
            autoreply.case_key("a@b.de", "Issue", None),
        )

    def test_pick_rule_prefers_specific_vorgangstyp(self):
        generic = {"name": "R1", "reference_doctype": ""}
        specific = {"name": "R2", "reference_doctype": "Issue"}
        self.assertEqual(
            autoreply.pick_rule([generic, specific], "Issue"), specific
        )
        self.assertEqual(
            autoreply.pick_rule([generic, specific], "Task"), generic
        )
        self.assertEqual(
            autoreply.pick_rule([specific], "Task"), None
        )

    def test_render_default_contains_vorgang_and_frist(self):
        subject, message = autoreply.render_default(
            {
                "vorgangsnummer": "ISS-0001",
                "frist": "25.07.2026",
                "sender_name": "Max Mieter",
            }
        )
        self.assertIn("ISS-0001", subject)
        self.assertIn("ISS-0001", message)
        self.assertIn("25.07.2026", message)
        self.assertIn("Max Mieter", message)
        # the promise wording of FEAT-11901
        self.assertIn("erhalten", message)


class _Comm:
    """Minimal stand-in for a Communication document."""

    def __init__(self, **kwargs):
        defaults = dict(
            name="COMM-0001",
            communication_type="Communication",
            communication_medium="Email",
            sent_or_received="Received",
            email_account="Support Postfach",
            sender='"Max Mieter" <max@example.com>',
            sender_full_name="Max Mieter",
            subject="Heizung defekt",
            reference_doctype="Issue",
            reference_name="ISS-0001",
            message_id="<abc@example.com>",
        )
        defaults.update(kwargs)
        self.__dict__.update(defaults)

    def get(self, key, default=None):
        return self.__dict__.get(key, default)


RULE = {
    "name": "KAR-0001",
    "email_account": "Support Postfach",
    "reference_doctype": "",
    "autonomy_level": "0 - Shadow Mode",
    "email_template": None,
    "response_time_days": 2,
    "daily_limit": 200,
    "cooldown_days": 7,
    "kill_switch": 0,
}


def _patch_site(**overrides):
    """Patch every site-touching helper of the autoreply module."""
    reply = mock.Mock()
    reply.name = "COMM-0002"
    patches = {
        "get_rules": mock.Mock(return_value=[dict(RULE)]),
        "central_gate": mock.Mock(return_value=(False, None, None)),
        "is_duplicate": mock.Mock(return_value=False),
        "daily_count": mock.Mock(return_value=0),
        "write_log": mock.Mock(),
        "create_reply_communication": mock.Mock(return_value=reply),
        "queue_email": mock.Mock(),
        "build_context": mock.Mock(
            return_value={
                "vorgangsnummer": "ISS-0001",
                "frist": "25.07.2026",
                "sender_name": "Max Mieter",
            }
        ),
    }
    patches.update(overrides)
    return [
        mock.patch.object(autoreply, attr, value)
        for attr, value in patches.items()
    ], patches


class TestAutoReplyFlow(unittest.TestCase):
    def _run(self, comm, **overrides):
        patchers, patches = _patch_site(**overrides)
        own_address = mock.patch(
            "kefiya.utils.autoreply.frappe.db.get_value",
            return_value="support@axessio.de",
        )
        with own_address:
            for p in patchers:
                p.start()
            try:
                autoreply.process_incoming(comm)
            finally:
                for p in patchers:
                    p.stop()
        return patches

    def test_shadow_mode_logs_would_send_and_sends_nothing(self):
        patches = self._run(_Comm())
        action = patches["write_log"].call_args[0][4]
        self.assertEqual(action, "Would Send")
        patches["queue_email"].assert_not_called()
        patches["create_reply_communication"].assert_not_called()

    def test_level_2_queues_email(self):
        rule = dict(RULE, autonomy_level="2 - Versand mit Leitplanken")
        patches = self._run(
            _Comm(), get_rules=mock.Mock(return_value=[rule])
        )
        patches["queue_email"].assert_called_once()
        action = patches["write_log"].call_args[0][4]
        self.assertEqual(action, "Sent")

    def test_level_1_creates_draft_without_sending(self):
        rule = dict(RULE, autonomy_level="1 - Vorschlagen (Entwurf)")
        patches = self._run(
            _Comm(), get_rules=mock.Mock(return_value=[rule])
        )
        patches["create_reply_communication"].assert_called_once()
        patches["queue_email"].assert_not_called()
        action = patches["write_log"].call_args[0][4]
        self.assertEqual(action, "Draft Created")

    def test_duplicate_is_skipped(self):
        patches = self._run(
            _Comm(), is_duplicate=mock.Mock(return_value=True)
        )
        action = patches["write_log"].call_args[0][4]
        self.assertEqual(action, "Skipped Duplicate")
        patches["queue_email"].assert_not_called()

    def test_kill_switch_stops_everything_silently(self):
        rule = dict(RULE, kill_switch=1, autonomy_level="3 - Autonom mit Leitplanken")
        patches = self._run(
            _Comm(), get_rules=mock.Mock(return_value=[rule])
        )
        patches["write_log"].assert_not_called()
        patches["queue_email"].assert_not_called()

    def test_central_gate_block_wins_over_local_level(self):
        rule = dict(RULE, autonomy_level="3 - Autonom mit Leitplanken")
        patches = self._run(
            _Comm(),
            get_rules=mock.Mock(return_value=[rule]),
            central_gate=mock.Mock(return_value=(True, None, "kill_switch")),
        )
        action = patches["write_log"].call_args[0][4]
        self.assertEqual(action, "Blocked")
        patches["queue_email"].assert_not_called()

    def test_central_level_override_downgrades_to_shadow(self):
        rule = dict(RULE, autonomy_level="3 - Autonom mit Leitplanken")
        patches = self._run(
            _Comm(),
            get_rules=mock.Mock(return_value=[rule]),
            central_gate=mock.Mock(return_value=(False, 0, None)),
        )
        action = patches["write_log"].call_args[0][4]
        self.assertEqual(action, "Would Send")
        patches["queue_email"].assert_not_called()

    def test_daily_limit_blocks(self):
        rule = dict(RULE, autonomy_level="2 - Versand mit Leitplanken", daily_limit=5)
        patches = self._run(
            _Comm(),
            get_rules=mock.Mock(return_value=[rule]),
            daily_count=mock.Mock(return_value=5),
        )
        action = patches["write_log"].call_args[0][4]
        self.assertEqual(action, "Blocked")
        patches["queue_email"].assert_not_called()

    def test_outgoing_and_non_email_communications_are_ignored(self):
        for comm in (
            _Comm(sent_or_received="Sent"),
            _Comm(communication_type="Comment"),
            _Comm(email_account=None),
            _Comm(sender=None),
        ):
            patches = self._run(comm)
            patches["write_log"].assert_not_called()

    def test_noreply_sender_is_ignored(self):
        patches = self._run(_Comm(sender="no-reply@portal.de"))
        patches["write_log"].assert_not_called()
        patches["queue_email"].assert_not_called()

    def test_handler_swallows_exceptions(self):
        # a crash inside processing must never propagate into email pulling
        with mock.patch.object(
            autoreply, "process_incoming", side_effect=RuntimeError("boom")
        ), mock.patch(
            "kefiya.utils.autoreply.frappe.log_error"
        ) as log_error:
            autoreply.on_communication_after_insert(_Comm())
            log_error.assert_called_once()
