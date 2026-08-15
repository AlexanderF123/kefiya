// Copyright (c) 2026, Phamos GmbH and contributors
// For license information, please see license.txt

// Entering an outgoing transfer, laid out the way a transfer form is.
//
// The dialog this replaces asked for account, recipient, IBAN, amount, purpose
// and a bare date field -- and that was all. The document has carried three
// more decisions the whole time and none of them could be made here:
//
//   execution_date    when it should happen
//   manage_due_date   who holds it until then, we or the bank
//   instant_payment   whether it goes as a SEPA instant payment
//
// A date field alone cannot say "as soon as possible" versus "on the 24th",
// and it certainly cannot say who keeps the order in the meantime. So the
// execution is asked as what it is: a choice, then its details.
//
// The recipient is a free field. It suggests known payees, but it does not
// require one -- the whole point of this document is a transfer that has no
// invoice behind it. The IBAN carries the safeguard instead: the document
// checks its checksum before anything is stored.

frappe.provide("kefiya");

//: How an order is executed. Kept as data because three places read it: the
//: form builds the choice from it, the dialog decides which fields to show,
//: and the detail view says it back in the same words.
kefiya.EXECUTION_MODES = [
	{
		value: "asap",
		label: __("As soon as possible"),
		hint: __("The order goes out with the next send."),
	},
	{
		value: "bank",
		label: __("On a date — the bank holds the order"),
		hint: __("Sent now, executed by the bank on the day. The bank must"
			+ " support dated transfers for this account."),
	},
	{
		value: "here",
		label: __("On a date — held here until then"),
		hint: __("Stays in the outbox and is offered for sending on the day."
			+ " Use this where the bank takes no dated order."),
	},
];

kefiya.execution_mode_of = function (row) {
	if (!row || !row.execution_date) return "asap";
	return row.manage_due_date ? "here" : "bank";
};

// One dialog for entering and for correcting. They ask for the same things,
// and two dialogs would have drifted apart the first time one of them changed.
kefiya.transfer_form = function (options) {
	options = options || {};
	const payers = options.payers || [];
	const existing = options.row || null;
	const isEdit = !!existing;

	if (!payers.length && !isEdit) {
		frappe.msgprint({
			title: __("No account available"),
			indicator: "orange",
			message: __("No bank access is set up that a transfer can start"
				+ " from. A loan, a guarantee or a credit card cannot send"
				+ " money."),
		});
		return;
	}

	const payerLabels = payers.map(function (p) {
		return p.bank_account + (p.company ? " — " + p.company : "");
	});
	const item = (existing && (existing.items || [])[0]) || {};

	const fields = [
		{
			fieldtype: "Select", fieldname: "payer", reqd: 1,
			label: __("Paying account"),
			options: payerLabels.join("\n"),
			default: payerLabels[0],
			read_only: isEdit ? 1 : 0,
			description: isEdit
				? __("The paying account cannot be changed on an existing"
					+ " order. Delete it and enter a new one instead.")
				: "",
		},
		{ fieldtype: "Section Break", label: __("Recipient") },
		{
			fieldtype: "Data", fieldname: "recipient_name", reqd: 1,
			label: __("Recipient"), default: item.recipient_name || "",
			description: __("Free text. Known payees are suggested while you"
				+ " type, but any name may be entered."),
		},
		{ fieldtype: "Column Break" },
		{
			fieldtype: "Data", fieldname: "recipient_iban", reqd: 1,
			label: __("IBAN"), default: item.recipient_iban || "",
			description: __("Checked against its checksum before it is stored."),
		},
		{ fieldtype: "Section Break" },
		{
			fieldtype: "Currency", fieldname: "amount", reqd: 1,
			label: __("Amount"), default: item.amount || null,
		},
		{ fieldtype: "Column Break" },
		{
			fieldtype: "Small Text", fieldname: "purpose",
			label: __("Reference"), default: item.purpose || "",
		},
		{ fieldtype: "Section Break", label: __("Execution") },
		{
			fieldtype: "Select", fieldname: "execution_mode", reqd: 1,
			label: __("When"),
			options: kefiya.EXECUTION_MODES.map(function (m) {
				return m.label;
			}).join("\n"),
			default: (kefiya.EXECUTION_MODES.find(function (m) {
				return m.value === kefiya.execution_mode_of(existing);
			}) || kefiya.EXECUTION_MODES[0]).label,
		},
		{
			fieldtype: "Date", fieldname: "execution_date",
			label: __("Execution date"),
			default: (existing && existing.execution_date) || null,
			depends_on: "eval:doc.execution_mode && doc.execution_mode.indexOf('"
				+ __("As soon as possible") + "') !== 0",
			mandatory_depends_on: "eval:doc.execution_mode && doc.execution_mode"
				+ ".indexOf('" + __("As soon as possible") + "') !== 0",
		},
		{ fieldtype: "Column Break" },
		{
			fieldtype: "Check", fieldname: "instant_payment",
			label: __("Instant payment"),
			default: existing && existing.instant_payment ? 1 : 0,
			description: __("Arrives within seconds. The bank must offer it for"
				+ " this account, and it is usually capped."),
		},
		{ fieldtype: "Section Break" },
		{ fieldtype: "HTML", fieldname: "hint" },
	];

	const dialog = new frappe.ui.Dialog({
		title: isEdit ? __("Correct transfer") : __("New transfer"),
		size: "large",
		fields: fields,
		primary_action_label: isEdit ? __("Save") : __("Enter"),
		primary_action: function (values) {
			kefiya.transfer_form_submit(dialog, values, payers, existing,
				options.onSaved);
		},
	});

	// The chosen mode explains itself, so nobody has to know what "the bank
	// holds the order" means for an account whose bank takes no dated orders.
	const showHint = function () {
		const label = dialog.get_value("execution_mode");
		const mode = kefiya.EXECUTION_MODES.find(function (m) {
			return m.label === label;
		}) || kefiya.EXECUTION_MODES[0];
		dialog.fields_dict.hint.$wrapper.html(
			"<div class='text-muted small'>"
			+ frappe.utils.escape_html(mode.hint) + "</div>");
	};
	dialog.fields_dict.execution_mode.df.onchange = showHint;

	// Suggestions without a requirement: an Autocomplete would refuse a name
	// it does not know, which is exactly the case this document exists for.
	kefiya.known_payees().then(function (names) {
		const input = dialog.fields_dict.recipient_name.$input;
		if (input && input.length && names.length) {
			input.autocomplete({ source: names, minLength: 2 });
		}
	});

	dialog.show();
	showHint();
	return dialog;
};

kefiya.known_payees = function () {
	return frappe.call({ method: "zk_payees" }).then(function (r) {
		const list = (r && r.message && r.message.payees) || [];
		return list.map(function (p) {
			return typeof p === "string" ? p : (p.name || p.recipient_name);
		}).filter(Boolean);
	}).catch(function () {
		return [];
	});
};

kefiya.transfer_form_submit = function (dialog, values, payers, existing, onSaved) {
	const mode = kefiya.EXECUTION_MODES.find(function (m) {
		return m.label === values.execution_mode;
	}) || kefiya.EXECUTION_MODES[0];

	if (mode.value !== "asap" && !values.execution_date) {
		frappe.msgprint({
			title: __("Date missing"),
			indicator: "orange",
			message: __("A dated transfer needs a date."),
		});
		return;
	}

	const payerIndex = payers.map(function (p) {
		return p.bank_account + (p.company ? " — " + p.company : "");
	}).indexOf(values.payer);

	const doc = {
		execution_date: mode.value === "asap" ? null : values.execution_date,
		manage_due_date: mode.value === "here" ? 1 : 0,
		instant_payment: values.instant_payment ? 1 : 0,
	};

	const item = {
		doctype: "Kefiya Transfer Item",
		recipient_name: (values.recipient_name || "").trim(),
		recipient_iban: (values.recipient_iban || "").replace(/\s+/g, "")
			.toUpperCase(),
		amount: values.amount,
		purpose: (values.purpose || "").trim(),
	};

	dialog.disable_primary_action();
	let call;
	if (existing) {
		// The paying account stays as it was: it is read-only above, and
		// changing it would make this a different order.
		call = frappe.call({
			method: "frappe.client.set_value",
			args: {
				doctype: "Kefiya Transfer", name: existing.name,
				fieldname: Object.assign({}, doc, { items: [item] }),
			},
		});
	} else {
		if (payerIndex < 0) {
			dialog.enable_primary_action();
			frappe.msgprint(__("Please choose a paying account."));
			return;
		}
		call = frappe.call({
			method: "frappe.client.insert",
			args: {
				doc: Object.assign({
					doctype: "Kefiya Transfer",
					kefiya_login: payers[payerIndex].login,
					items: [item],
				}, doc),
			},
		});
	}

	call.then(function () {
		dialog.hide();
		frappe.show_alert({
			message: existing ? __("Transfer saved.") : __("Transfer entered."),
			indicator: "green",
		}, 4);
		if (onSaved) onSaved();
	}).catch(function (r) {
		dialog.enable_primary_action();
		// The document's own validation is the safeguard here -- the IBAN
		// checksum above all -- so its message is what the user needs to see,
		// not a generic failure.
		frappe.msgprint({
			title: __("Not saved"),
			indicator: "red",
			message: kefiya.server_message(r)
				|| __("The transfer could not be saved."),
		});
	});
};

kefiya.server_message = function (r) {
	try {
		return JSON.parse((r && r._server_messages) || "[]").map(function (m) {
			try { return JSON.parse(m).message; } catch (e) { return m; }
		}).join(" ");
	} catch (e) {
		return "";
	}
};
