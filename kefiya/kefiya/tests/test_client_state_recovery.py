# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""A stored connection state that cannot build a dialog must not be kept.

The trap it made is a closed loop. A send whose dialog initialisation fails
persists the state it ended up with; that state has no bank parameters; the
next attempt restores it, python-fints answers "could not fetch BPD", and the
same empty state is written again. The access is then unusable for good and
the only way out is emptying the field by hand.

Both ends are closed here: an empty BPD is never persisted over a good state,
and a state that already went bad is discarded when it surfaces -- for the
sibling logins too, because they share it.

Read as source text: fints_controller imports frappe at the top and never
loads outside a bench, and a test that cannot run is worse than none.
"""

import os
import re
import unittest


def _read(*parts):
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), *parts)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _block(source, header):
    """One def, by indentation."""
    # [ \t]* and not \s*: \s matches newlines, so the search happily started
    # on a blank line above and measured the indent of nothing.
    hit = re.search(r"^([ \t]*)def %s\(" % re.escape(header), source, re.M)
    assert hit, header
    indent = len(hit.group(1))
    lines = source[hit.start():].split("\n")
    out = [lines[0]]
    for line in lines[1:]:
        if line.strip() and (len(line) - len(line.lstrip())) <= indent:
            break
        out.append(line)
    return "\n".join(out)


class TestAnEmptyBpdIsNeverPersisted(unittest.TestCase):

    def setUp(self):
        self.py = _read("utils", "fints_controller.py")

    def test_the_guard_stands_before_the_write(self):
        body = _block(self.py, "_persist_fints_state")
        self.assertIn("_has_bank_parameters(self.fints_connection)", body)
        self.assertLess(
            body.index("_has_bank_parameters"),
            body.index("deconstruct"),
            "Asking after writing would defeat the purpose.")

    def test_an_unreadable_library_shape_behaves_as_before(self):
        """A version this cannot inspect must persist, as it always did.
        Guessing "empty" there would stop storing state at all."""
        body = _block(self.py, "_has_bank_parameters")
        self.assertEqual(body.count("return True"), 3, body)
        self.assertIn("except Exception:", body)


class TestAPoisonedStateDiscardsItself(unittest.TestCase):

    def setUp(self):
        self.py = _read("utils", "fints_controller.py")

    def test_only_this_one_failure_is_caught(self):
        """FinTSClientError covers a dozen unrelated things; everything else
        has to keep propagating."""
        body = _block(self.py, "_is_missing_bank_parameters")
        self.assertIn("could not fetch BPD", body)
        send = _block(self.py, "submit_sepa_transfer")
        self.assertIn("if not _is_missing_bank_parameters(exc):", send)
        self.assertIn("raise", send)

    def test_it_is_discarded_and_not_retried(self):
        """The segments were already on the wire. A second send is the one
        mistake that costs real money."""
        send = _block(self.py, "submit_sepa_transfer")
        self.assertIn("self._forget_client_state()", send)
        self.assertIn("Before sending again, look in your online banking",
                      send)

    def test_the_siblings_lose_it_too(self):
        """They share the state, so clearing one hands it straight back."""
        body = _block(self.py, "_forget_client_state")
        self.assertIn("_sibling_login_filters()", body)
        self.assertIn("stored_client_state", body)

    def test_both_ends_write_the_same_fields(self):
        """They had drifted apart, and the raw one wrote None into a Check
        column -- MariaDB refuses that, and the discard broke off with
        error 1048 while an order was already on the wire. One list now, in
        fints_state_fields, checked against the doctype without a bench."""
        body = _block(self.py, "_forget_client_state")
        self.assertIn("fints_state_fields.CLEARED", body)
        self.assertIn("fints_state_fields.cleared()", body)
        self.assertNotIn('"stored_tan_state_decoupled": None', body)

    def test_the_discard_is_committed(self):
        """The throw that follows rolls the transaction back; without its own
        commit the discarded state comes back with it."""
        body = _block(self.py, "_forget_client_state")
        self.assertIn("frappe.db.commit()", body)


class TestTheMessageSaysWhatReallyHappened(unittest.TestCase):
    """The discard can fail -- it did, on 05.10.2026. Saying it succeeded
    anyway sends the user straight back into the same wall, and the wall is
    a bank access that can no longer send."""

    def setUp(self):
        self.py = _read("utils", "fints_controller.py")

    def test_the_discard_reports_whether_it_worked(self):
        body = _block(self.py, "_forget_client_state")
        self.assertIn("return True", body)
        self.assertIn("return False", body)
        # The False belongs to the except branch, not to some early exit.
        self.assertGreater(body.index("return False"),
                           body.index("except Exception:"))

    def test_the_send_asks_before_it_promises(self):
        send = _block(self.py, "submit_sepa_transfer")
        self.assertIn("if self._forget_client_state():", send)

    def test_and_names_the_way_out_when_it_failed(self):
        send = _block(self.py, "submit_sepa_transfer")
        self.assertIn("could NOT be discarded", send)
        self.assertIn("Reset Connection", send)

    def test_the_warning_stands_in_both_cases(self):
        """Whatever became of the stored state, the segments were on the
        wire. Looking before sending again is the part that must not depend
        on it."""
        send = _block(self.py, "submit_sepa_transfer")
        self.assertEqual(
            send.count("Before sending again, look in your online banking"), 1)
        hint = send.index("Before sending again, look in your online banking")
        self.assertLess(send.index("could NOT be discarded"), hint)
        self.assertLess(send.index("has been discarded"), hint)
