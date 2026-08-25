// Copyright (c) 2026, Phamos GmbH and contributors
// For license information, please see license.txt

// What our own payment history says about a recipient, shown where it helps.
//
// The bank's Verification of Payee happens at the bank, on submission -- in
// FinTS the check is part of the transfer message, so asking it means sending
// the order. That is too late where one person enters an order and another
// sends it. This is the question that CAN be asked at entry: have we paid
// this IBAN before, and did it belong to this name?
//
// It is shown three times on purpose, because three different people look:
// while entering, on the order itself, and in the box the managing director
// confirms before the money leaves.

frappe.provide("kefiya");

kefiya.PAYEE_VERDICTS = {
	known: {
		colour: "green",
		short: __("Payee known"),
		long: __("This IBAN was paid before under this name."),
	},
	// The loudest of the four. Right letterhead, right name, swapped IBAN --
	// and the bank's own check would not flag it, because the swapped IBAN
	// really does belong to somebody with a plausible name.
	other_iban: {
		colour: "red",
		short: __("Known payee, new IBAN"),
		long: __("We have paid this payee before, always to a different IBAN."
			+ " Check the invoice against an earlier one before releasing"
			+ " this."),
	},
	name_differs: {
		colour: "red",
		short: __("IBAN known under another name"),
		long: __("This IBAN was paid before, but to somebody else."),
	},
	// Not an alarm. Every payee is new once.
	new: {
		colour: "orange",
		short: __("New payee"),
		long: __("First payment to this IBAN. Worth a second pair of eyes."),
	},
};

kefiya.payee_verdict = function (verdict) {
	return kefiya.PAYEE_VERDICTS[verdict] || null;
};

//: Does this verdict need a human to look before the money leaves?
kefiya.payee_needs_a_look = function (verdict) {
	return verdict === "other_iban" || verdict === "name_differs";
};

kefiya.payee_check = function (name, iban) {
	if (!iban) return Promise.resolve(null);
	return frappe.call({
		method: "kefiya.utils.payee_check.check_payee",
		args: { name: name || "", iban: iban },
		silent: true,
	}).then(function (r) {
		return (r && r.message) || null;
	}).catch(function () {
		// Not knowing is not the same as being fine, and the caller renders
		// nothing rather than a reassuring tick.
		return null;
	});
};

//: One line about a recipient, for a dialog. Detail included, because "known
//: payee, new IBAN" without the old IBAN is an alarm nobody can act on.
kefiya.payee_check_html = function (answer) {
	if (!answer) return "";
	const info = kefiya.payee_verdict(answer.verdict);
	if (!info) return "";
	const esc = frappe.utils.escape_html;
	const tone = { green: "var(--green-600,#1a7f37)",
		orange: "var(--orange-600,#b26a00)",
		red: "var(--red-600,#c0392b)" }[info.colour];

	let detail = info.long;
	if (answer.verdict === "other_iban" && (answer.other_ibans || []).length) {
		detail += " " + __("So far: {0}",
			[answer.other_ibans.map(kefiya.iban_pretty).join(", ")]);
	}
	if (answer.verdict === "name_differs" && (answer.known_as || []).length) {
		detail += " " + __("So far: {0}", [answer.known_as.join(", ")]);
	}
	return "<div style='color:" + tone + ";font-size:12px'><b>"
		+ esc(info.short) + "</b> — " + esc(detail) + "</div>";
};
