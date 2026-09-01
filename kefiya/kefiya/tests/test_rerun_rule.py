# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Which of two identical rows a second pass wrote.

statement_repair declined this case in writing -- "nothing distinguishes the
two rows ... no field here tells them apart" -- and that was true of the
fields it read. It never read ``creation``, and on the 21.05.2026 run that is
what separates the two populations:

    2,508 pairs   6 to 93 seconds apart, eight over an hour  -> a second pass
      501 pairs   0 to 4 seconds apart                       -> one pass

Rows written in one pass are consecutive. A minute of daylight between two
copies, across thousands of rows, means the file was read again.

The 501 are not decided here and must not be: the source listed the booking
twice, and that may be a duplicated export line or a tenant who really paid
the same amount twice on one day. Deleting one of those loses a real payment,
which is the one thing this family of modules promises not to do.
"""

import os
import unittest
from datetime import datetime, timedelta

from kefiya.utils.rerun_rule import (FROM_A_RERUN, SAME_PASS, SECONDS_APART,
                                     UNDECIDED, identity, seconds_between,
                                     surplus_of)


BASE = datetime(2026, 5, 21, 13, 20, 39)


def row(name, offset_seconds, **overrides):
    data = {
        "name": name,
        "creation": BASE + timedelta(seconds=offset_seconds),
        "bank_account": "SKL Sparkasse - Sparkasse Heidelberg",
        "date": "2025-06-30",
        "deposit": 780.0,
        "withdrawal": 0.0,
        "description": "GUTSCHR. UEBERW. DAUERAUFTR | Miete Wohnung Nr. 007",
        "bank_party_name": "Chiara Dangelo",
        "bank_party_iban": "DE02120300000000202051",
    }
    data.update(overrides)
    return data


class TestWhatMakesTwoRowsTheSameBooking(unittest.TestCase):

    def test_the_account_is_part_of_it(self):
        """Unlike duplicate_rule, which compares ACROSS accounts."""
        self.assertNotEqual(identity(row("a", 0)),
                            identity(row("b", 0, bank_account="Anderes")))

    def test_the_whole_purpose_line_counts(self):
        """These rows sit side by side; two neighbours differing in their
        eighty-first character are two bookings."""
        long_one = "x" * 80 + "A"
        long_two = "x" * 80 + "B"
        self.assertNotEqual(identity(row("a", 0, description=long_one)),
                            identity(row("b", 0, description=long_two)))

    def test_identical_rows_are_one_booking(self):
        self.assertEqual(identity(row("a", 0)), identity(row("b", 40)))


class TestTheGap(unittest.TestCase):

    def test_a_second_pass_is_recognised(self):
        """The measured shape: 41 seconds apart, second pass."""
        copies = [row("erste", 0), row("zweite", 41)]
        surplus, why = surplus_of(copies)
        self.assertEqual(why, FROM_A_RERUN)
        self.assertEqual([r["name"] for r in surplus], ["zweite"])

    def test_the_earliest_always_stays(self):
        """Never the last copy -- the first pass's row is the keeper."""
        copies = [row("spaet", 90), row("frueh", 0), row("mittel", 45)]
        surplus, why = surplus_of(copies)
        self.assertEqual(why, FROM_A_RERUN)
        self.assertNotIn("frueh", [r["name"] for r in surplus])
        self.assertEqual(len(surplus), 2)

    def test_one_pass_decides_nothing(self):
        """The source listed it twice. This does not argue with the source."""
        surplus, why = surplus_of([row("a", 0), row("b", 1)])
        self.assertEqual(why, SAME_PASS)
        self.assertEqual(surplus, [])

    def test_the_boundary_belongs_to_the_cautious_side(self):
        self.assertEqual(surplus_of([row("a", 0),
                                     row("b", SECONDS_APART - 1)])[1],
                         SAME_PASS)
        self.assertEqual(surplus_of([row("a", 0),
                                     row("b", SECONDS_APART)])[1],
                         FROM_A_RERUN)

    def test_a_mixed_group_is_left_whole(self):
        """A same-pass twin AND a later copy. Picking one out would leave a
        pair behind and would rest on an ordering this cannot see."""
        surplus, why = surplus_of([row("a", 0), row("b", 1), row("c", 60)])
        self.assertEqual(why, UNDECIDED)
        self.assertEqual(surplus, [])

    def test_a_single_row_is_not_a_duplicate(self):
        self.assertEqual(surplus_of([row("a", 0)]), ([], UNDECIDED))

    def test_it_never_raises_on_unreadable_stamps(self):
        broken = [row("a", 0), dict(row("b", 0), creation="nicht lesbar")]
        self.assertEqual(surplus_of(broken)[0], [])

    def test_seconds_between_survives_nonsense(self):
        self.assertIsNone(seconds_between("a", "b"))


def _source(*parts):
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    with open(os.path.join(root, *parts), encoding="utf-8") as handle:
        return handle.read()


class TestTheToolKeepsEveryPromise(unittest.TestCase):
    """The same four the cross-account deletion makes, plus confirm-by-count.

    Asserted as code with its arguments, not as the sentences that describe
    it -- the docstrings here list the promises verbatim, so a search for the
    words finds the prose and proves nothing.
    """

    def _delete_body(self):
        source = _source("utils", "statement_repair.py")
        method = source.split("def delete_rerun_duplicates(")[1]
        return method.split('"""', 2)[2].split("\ndef ")[0]

    def test_it_only_reads_drafts_and_untouched_rows(self):
        source = _source("utils", "statement_repair.py")
        plan = source.split("def plan_reruns(")[1].split("\ndef ")[0]
        self.assertIn('"docstatus": 0', plan)
        self.assertIn("if not _untouched(row):", plan)

    def test_it_confirms_by_count(self):
        """A count that no longer matches means the data moved."""
        body = self._delete_body()
        self.assertIn("if cint(confirm) != len(doomed):", body)
        self.assertIn("frappe.throw", body)

    def test_it_deletes_softly(self):
        """Not delete_permanently: a wrong rule has to be undoable."""
        body = self._delete_body()
        self.assertIn("frappe.delete_doc(\"Bank Transaction\", name,", body)
        self.assertNotIn("delete_permanently", body)

    def test_it_asks_permission(self):
        body = self._delete_body()
        self.assertIn("_may_repair()", body)

    def test_it_commits_in_batches(self):
        """An interruption leaves a finished prefix, not a rolled-back hour."""
        body = self._delete_body()
        self.assertIn("if index % BATCH == 0:", body)

    def test_the_undecided_pairs_are_named_not_swallowed(self):
        source = _source("utils", "statement_repair.py")
        plan = source.split("def plan_reruns(")[1].split("\ndef ")[0]
        self.assertIn("review.append({", plan)
        self.assertIn('"zeilen": [row["name"] for row in copies]', plan)


if __name__ == "__main__":
    unittest.main()
