// Copyright (c) 2026, Phamos GmbH and contributors
// For license information, please see license.txt
//
// Pay an executed transfer once more.
//
//   kefiya.transfer_again(bank_transaction_name)
//
// The booking already holds recipient, IBAN, amount and purpose. The server
// hands them over (transaction_actions.transfer_again), and a NEW, unsaved
// Kefiya Transfer opens with them -- every field can still be changed, and
// it is approved and sent like any other order, with its own TAN.
//
// Offered in three places: the Bank Transaction form, and -- where the
// desk's shared context menu (window.axActions) is present -- on every row
// that names a Bank Transaction, which is how the finance overview and the
// account statement view show their bookings.

frappe.provide("kefiya");

kefiya.transfer_again = function (name) {
	if (!name) return;
	frappe.call({
		method: "kefiya.utils.transaction_actions.transfer_again",
		args: { name: name },
		freeze: true,
	}).then(function (r) {
		const m = (r && r.message) || {};
		if (m.status !== "ok") {
			frappe.msgprint({ title: __("Cannot transfer again"),
				indicator: "orange",
				message: frappe.utils.escape_html(m.message || "") });
			return;
		}
		frappe.model.with_doctype("Kefiya Transfer", function () {
			const doc = frappe.model.get_new_doc("Kefiya Transfer");
			if (m.kefiya_login) doc.kefiya_login = m.kefiya_login;
			if (m.company) doc.company = m.company;
			const row = frappe.model.add_child(doc, "items");
			const it = m.item || {};
			row.recipient_name = it.recipient_name || "";
			row.recipient_iban = it.recipient_iban || "";
			row.amount = it.amount || m.amount || 0;
			row.purpose = it.purpose || "";
			frappe.set_route("Form", "Kefiya Transfer", doc.name);
			frappe.show_alert({
				message: m.warning || __("New transfer filled in from booking {0}."
					+ " Check it, then approve and send.", [name]),
				indicator: m.warning ? "orange" : "green",
			}, 10);
		});
	});
};

// The shared context menu loads on its own schedule; register as soon as
// it is there, and only once.
(function () {
	let tries = 0;
	function register() {
		if (kefiya._transfer_again_registered) return true;
		if (!window.axActions || !window.axActions.register) return false;
		window.axActions.register("Bank Transaction", function (dt, name) {
			return [{
				label: __("Transfer again"),
				action: function () { kefiya.transfer_again(name); },
				when: function () {
					return frappe.model.can_create
						? frappe.model.can_create("Kefiya Transfer") : true;
				},
			}];
		});
		kefiya._transfer_again_registered = true;
		return true;
	}
	function wait() {
		if (register() || tries++ > 60) return;
		setTimeout(wait, 2000);
	}
	wait();
})();
