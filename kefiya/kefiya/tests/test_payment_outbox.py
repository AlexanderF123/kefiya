# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""The outgoing-payments list, and the promises it makes about money.

The list used to be a stored script inside a Custom HTML Block on one site:
19 KB of JavaScript in a database row, with no review, no history and no test
around it -- on the page that sends money. It lives in this app now, and the
properties that matter are asserted rather than hoped for.

Four of them, and each has a way it goes wrong:

  * a batch button offers more than it will do -- somebody selects thirty
    orders, presses Approve, and only nine were drafts, so twenty-one silently
    did nothing;
  * a batch reports only its successes, and half a selection goes missing;
  * a send picks one paying account out of several, debiting the wrong one;
  * approving is presented as sending, so a click that was meant to lock an
    order in fact moves money.
"""

import os
import re
import unittest


def _source(name="payment_outbox.js"):
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))),
        "public", "js", "controllers", name)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _function(source, header):
    """The body of one function, up to the next one at the same indent."""
    tail = source.split(header)[1]
    end = tail.find("\n\tfunction ")
    if end < 0:
        end = tail.find("\n    function ")
    return tail[:end if end > 0 else len(tail)]


class TestABatchOffersOnlyWhatItWillDo(unittest.TestCase):

    def test_every_batch_action_has_a_rule_for_what_it_may_touch(self):
        body = _function(_source(), "function applicable(what) {")
        for action in ("approve", "delete", "hold", "release", "send"):
            self.assertIn('=== "{0}"'.format(action), body,
                          "{0} would fall through and touch nothing, or "
                          "everything.".format(action))

    def test_approving_and_deleting_are_limited_to_drafts(self):
        body = _function(_source(), "function applicable(what) {")
        for action in ("approve", "delete"):
            line = [ln for ln in body.splitlines()
                    if '=== "{0}"'.format(action) in ln][0]
            self.assertIn("docstatus === 0", line,
                          "An approved order must not be re-approved or "
                          "deleted from a list.")

    def test_sending_follows_the_flag_the_server_sets(self):
        """`sendable` is the server's answer, which knows about hold, due date
        and payee verification. Re-deriving it here would drift from it."""
        body = _function(_source(), "function applicable(what) {")
        line = [ln for ln in body.splitlines() if '=== "send"' in ln][0]
        self.assertIn("r.sendable", line)

    def test_the_buttons_count_what_is_applicable_and_not_the_selection(self):
        source = _source()
        for action in ("delete", "release", "hold", "approve", "send"):
            self.assertIn('applicable("{0}").length'.format(action), source,
                          "The button label must count what the action will "
                          "actually touch.")
        self.assertNotIn("selection().length)", source.split(
            "function footer()")[1].split("function render()")[0],
            "Labelling a button with the whole selection promises more than "
            "the action does.")


class TestNoBatchReportsOnlyItsSuccesses(unittest.TestCase):

    def test_the_batch_report_names_the_documents_that_refused(self):
        body = _function(_source(),
                         "function reportBatch(done, failed, okText, "
                         "failTitle) {")
        self.assertIn("if (!failed.length)", body)
        self.assertIn("f.reason", body,
                      "A refusal without its reason is not a report.")

    def test_approving_and_deleting_both_report_through_it(self):
        source = _source()
        self.assertIn('reportBatch(m.approved || [], m.refused || [],', source)
        self.assertIn("reportBatch(gone, failed,", source)

    def test_deleting_collects_failures_instead_of_stopping(self):
        """One draft that cannot be deleted must not abandon the rest."""
        body = _function(_source(), "function remove() {")
        self.assertIn("failed.push({ name: r.name, reason: errText(e) });",
                      body)
        self.assertIn("chain = chain.then(", body,
                      "Deleting runs in sequence so a refusal names its "
                      "order.")


class TestSendingRefusesRatherThanGuesses(unittest.TestCase):

    def test_several_paying_accounts_abort_the_send(self):
        body = _function(_source(), "function send() {")
        self.assertIn("Object.keys(accounts).length > 1", body)
        self.assertIn("One account at a time", body)
        self.assertIn("return;", body.split(
            "Object.keys(accounts).length > 1")[1][:400],
            "Warning and then sending anyway would debit the wrong account.")

    def test_the_send_says_what_it_is_leaving_out(self):
        body = _function(_source(), "function send() {")
        self.assertIn("const skipped = selection().length - rows.length;",
                      body)
        self.assertIn("if (skipped > 0)", body)

    def test_the_send_is_confirmed_and_says_nothing_is_debited_yet(self):
        body = _function(_source(), "function send() {")
        self.assertIn("frappe.confirm(message, function () {", body)
        self.assertIn("confirmed: 1", body)
        self.assertIn("Nothing is debited until then.", body)


class TestApprovingIsNotSending(unittest.TestCase):

    def test_the_confirmation_says_what_approving_does_and_does_not_do(self):
        body = _function(_source(), "function approve() {")
        self.assertIn("No money", body)
        self.assertIn("separate step", body,
                      "The whole question this page raised was what "
                      "\"Freigeben\" means. It has to answer it where it is "
                      "asked.")

    def test_approving_goes_through_the_apps_own_endpoint(self):
        self.assertIn("kefiya.utils.client.approve_transfers", _source())


class TestApprovingABatchIsNotAllOrNothing(unittest.TestCase):
    """The endpoint behind the Approve button, read from its source.

    Two ways a batch approval goes wrong, and both are quiet: a document that
    refuses rolls back the ones approved before it, or it is skipped without
    anybody being told.
    """

    @staticmethod
    def _endpoint():
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))), "utils", "client.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        return source.split("def approve_transfers(")[1].split(
            "\n@frappe.whitelist()")[0]

    def test_each_document_is_checked_for_permission_on_its_own(self):
        self.assertIn('frappe.has_permission(\n            "Kefiya Transfer",'
                      ' ptype="submit", doc=name, throw=True)',
                      self._endpoint())

    def test_a_refusal_rolls_back_only_its_own_document(self):
        body = self._endpoint()
        self.assertIn("frappe.db.savepoint(point)", body)
        self.assertIn("frappe.db.rollback(save_point=point)", body,
                      "A bare rollback would discard the approvals that "
                      "already succeeded in this batch.")
        self.assertNotIn("frappe.db.rollback()", body)

    def test_every_refusal_comes_back_with_a_reason(self):
        body = self._endpoint()
        self.assertIn('refused.append({"name": name, "reason":', body)
        self.assertIn('"refused": refused', body)

    def test_an_already_approved_order_is_named_rather_than_resubmitted(self):
        body = self._endpoint()
        self.assertIn("if doc.docstatus != 0:", body)


class TestTheRowIsTheButton(unittest.TestCase):

    def test_a_row_opens_its_order(self):
        source = _source()
        self.assertIn("tr.onclick = open;", source)
        self.assertIn("kefiya.transfer_details(r, {", source)

    def test_no_per_row_action_buttons_are_rendered(self):
        """They were the reason the row could not be clicked: six small
        buttons per line, repeated on every one of them."""
        table = _source().split("function table()")[1].split(
            "function footer()")[0]
        for gone in ("zk-det", "zk-edit", "zk-free", "zk-hold", "zk-del",
                     "zk-mini"):
            self.assertNotIn(gone, table)

    def test_the_checkbox_still_only_selects(self):
        source = _source()
        self.assertIn('e.target.closest(".zk-cx")', source,
                      "A click on the checkbox must not also open the order.")

    def test_a_row_can_be_reached_without_a_mouse(self):
        source = _source()
        self.assertIn("tabindex='0'", source)
        self.assertIn('e.key === "Enter" || e.key === " "', source)


class TestTheChoicesAreRemembered(unittest.TestCase):

    def test_sorting_and_the_sent_filter_are_written_back(self):
        body = _function(_source(), "function remember() {")
        for key in ("sort_by", "sort_dir", "show_sent"):
            self.assertIn(key, body)

    def test_both_things_that_can_be_chosen_are_remembered(self):
        """Two places change a setting, and both have to store it: the sort
        headers and the "show sent" box."""
        source = _source()
        self.assertIn("remember();",
                      _function(source, "function sortBy(key) {"))
        sent = source.split('if (act === "sent") {')[1][:400]
        self.assertIn("remember();", sent)

    def test_a_third_click_restores_the_servers_order(self):
        """The server orders drafts first and then by due date. Once a column
        had been clicked that order would otherwise be unreachable."""
        body = _function(_source(), "function sortBy(key) {")
        self.assertIn("view.sortBy = null;", body)

    def test_reading_prefers_the_framework_over_the_browser(self):
        body = _source().split("kefiya.outbox_settings = {")[1].split(
            "kefiya.payment_outbox")[0]
        framework = body.find("frappe.model.user_settings")
        local = body.find("window.localStorage.getItem")
        self.assertTrue(0 < framework < local,
                        "Settings that follow the user to another browser win "
                        "over the ones that do not.")


class TestEverySortableColumnSortsByWhatItShows(unittest.TestCase):

    def test_each_column_carries_its_own_sort_key(self):
        block = _source().split("kefiya.OUTBOX_COLUMNS = [")[1].split("\n];")[0]
        keys = re.findall(r'key: "(\w+)"', block)
        self.assertEqual(len(keys), len(re.findall(r"sort: function", block)),
                         "A column without a sort key would render a header "
                         "that does nothing when clicked.")
        self.assertEqual(keys, ["state", "account", "recipient", "due",
                                "amount", "note"])

    def test_an_undated_order_sorts_before_every_dated_one(self):
        """No date means "as soon as possible", which is sooner than any
        date -- sorting it to the end would bury what leaves first."""
        block = _source().split("kefiya.OUTBOX_COLUMNS = [")[1].split("\n];")[0]
        self.assertIn('r.execution_date || "0000-00-00"', block)


class TestTheSelectionCannotOutliveItsRows(unittest.TestCase):

    def test_a_vanished_order_is_dropped_from_the_selection(self):
        body = _function(_source(), "function load() {")
        self.assertIn("if (!alive[name]) delete view.selected[name];", body)


class TestTheStylesheetReachesThePage(unittest.TestCase):
    """A Custom HTML Block renders inside a shadow root.

    That is why the block is handed a `root_element` instead of reaching for
    document, and why it has a style field of its own. A stylesheet appended
    to document.head does not cross that boundary -- the page came up with
    every rule silently matching nothing, which is exactly what happened the
    first time this moved out of the block.
    """

    def test_the_stylesheet_goes_where_the_list_lives(self):
        body = _source().split("kefiya.outbox_style = function (root) {")[1]
        body = body.split("\nkefiya.payment_outbox")[0]
        self.assertIn("root.getRootNode()", body,
                      "getRootNode answers the shadow root inside a block and "
                      "the document outside one.")
        self.assertIn("holder.appendChild(el)", body)
        self.assertNotIn("document.head.appendChild", body)

    def test_it_is_given_the_element_it_has_to_reach(self):
        self.assertIn("kefiya.outbox_style(root);", _source(),
                      "Called without the element it cannot find the shadow "
                      "root, and it is back to document.head.")

    def test_it_is_not_put_inside_the_element_that_gets_rewritten(self):
        """render() replaces #zk's innerHTML on every draw."""
        body = _source().split("kefiya.outbox_style = function (root) {")[1]
        body = body.split("\nkefiya.payment_outbox")[0]
        self.assertNotIn("root.appendChild(el)", body)

    def test_the_block_keeps_no_second_copy_of_it(self):
        """Two stylesheets for one list is the split this move undid."""
        block = _source("../blocks/payment_outbox_block.js")
        self.assertNotIn("#zk .zk-", block)


class TestTheTanPromptIsTheSharedOne(unittest.TestCase):

    def test_the_outbox_does_not_build_its_own_prompt(self):
        source = _source()
        self.assertIn("kefiya.tan_prompt(data, live.load)", source)
        self.assertNotIn("frappe.prompt(", source,
                         "A second TAN box drifted from the first once "
                         "already: it named neither bank nor account.")

    def test_the_shared_prompt_is_actually_exported(self):
        self.assertIn("kefiya.tan_prompt = tanPrompt;",
                      _source("bank_refresh.js"))

    def test_a_stale_view_cannot_answer_for_the_live_one(self):
        """The handler is bound once per page load; the list is rebuilt on
        every visit."""
        body = _function(_source(), "function bindTan() {")
        self.assertIn("const live = kefiya._outbox;", body)
