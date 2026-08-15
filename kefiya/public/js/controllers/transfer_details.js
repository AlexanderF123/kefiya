// Copyright (c) 2026, Phamos GmbH and contributors
// For license information, please see license.txt

// What one outgoing transfer actually says, laid out like a transfer form
// rather than as a list of database fields.
//
// The previous version was a two-column table of six rows. It named the order
// but not what would happen to it: whether the bank holds it until a date or
// takes it now, whether it goes as an instant payment, whether we keep the due
// date ourselves -- all of that lives on the document and none of it was
// shown. The order number was text, so getting to the document meant finding
// it by hand. And a receipt attached to the order was not visible at all.
//
// It lives here rather than in the page that opens it: the page is a stored
// script on one site, this is versioned, reviewed and shared by every caller.

frappe.provide("kefiya");

kefiya.transfer_details = function (row, options) {
	if (!row) return;
	options = options || {};

	const esc = frappe.utils.escape_html;
	const dialog = new frappe.ui.Dialog({
		title: __("Transfer"),
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "body" }],
		primary_action_label: __("Open document"),
		primary_action: function () {
			dialog.hide();
			frappe.set_route("Form", "Kefiya Transfer", row.name);
		},
	});

	// Correcting happens from here, so the row itself needs no second button.
	// Only a draft can be corrected: after approval the amounts and the
	// recipients are locked, which is the entire point of approving.
	if (row.docstatus === 0 && options.canWrite !== false) {
		dialog.set_secondary_action_label(__("Correct"));
		dialog.set_secondary_action(function () {
			dialog.hide();
			kefiya.transfer_form({
				row: row,
				payers: options.payers || [],
				onSaved: options.onChanged || function () {},
			});
		});
	}

	const field = dialog.fields_dict.body;
	field.$wrapper.html(kefiya.transfer_details_html(row, null));
	dialog.show();

	// The receipts are fetched only once the order is actually looked at.
	// Shipping them with every row of the list would fetch hundreds of file
	// records to show none of them.
	kefiya.transfer_attachments(row.name).then(function (files) {
		field.$wrapper.html(kefiya.transfer_details_html(row, files));
	});
};

kefiya.transfer_attachments = function (name) {
	return frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "File",
			filters: {
				attached_to_doctype: "Kefiya Transfer",
				attached_to_name: name,
			},
			fields: ["name", "file_name", "file_url", "is_private", "file_size"],
			limit_page_length: 0,
		},
	}).then(function (r) {
		return (r && r.message) || [];
	}).catch(function () {
		// A receipt that cannot be listed must not take the whole dialog with
		// it -- the order itself is what the reader came for.
		return null;
	});
};

kefiya.transfer_details_html = function (row, files) {
	const esc = frappe.utils.escape_html;
	const dmy = function (d) {
		return d ? frappe.datetime.str_to_user(d) : "";
	};
	const money = function (v) {
		return format_currency(v || 0);
	};

	// --- how it will be executed ------------------------------------------
	// The one thing a transfer form is really about. Written as sentences,
	// because "execution_date = null, manage_due_date = 0" is not something
	// anybody should have to translate in their head.
	let when;
	if (!row.execution_date) {
		when = __("As soon as possible");
	} else if (row.manage_due_date) {
		when = __("On {0} — held here until then", [dmy(row.execution_date)]);
	} else {
		when = __("On {0} — the bank holds the order", [dmy(row.execution_date)]);
	}

	const rows = [
		[__("Order"), "<a href='/app/kefiya-transfer/" + encodeURIComponent(row.name)
			+ "'>" + esc(row.name) + "</a>"],
		[__("State"), esc(row.status || "")
			+ (row.blocked ? " <span class='text-muted'>— " + esc(row.blocked)
				+ "</span>" : "")],
		[__("Paying account"), esc(row.bank_account || "")],
		[__("Company"), esc(row.company || "")],
	];

	const execution = [
		[__("Execution"), esc(when)],
		[__("Instant payment"), row.instant_payment
			? __("Yes — sent as a SEPA instant payment")
			: __("No — ordinary SEPA transfer")],
		[__("Due date"), row.manage_due_date
			? __("Kept here, released on the day")
			: __("Left with the bank")],
	];
	if (row.vop_pending) {
		execution.push([__("Payee verification"), __("still open")]);
	}
	if (row.bank_reference) {
		execution.push([__("Bank response"), esc(row.bank_reference)]);
	}

	const asTable = function (pairs) {
		return "<table class='kef-td'>" + pairs.map(function (p) {
			return "<tr><td class='kef-k'>" + p[0] + "</td><td>" + p[1]
				+ "</td></tr>";
		}).join("") + "</table>";
	};

	// --- the payments themselves -------------------------------------------
	const items = (row.items || []).map(function (it) {
		return "<tr><td><b>" + esc(it.recipient_name || "—") + "</b>"
			+ (it.recipient_iban
				? "<div class='kef-iban'>" + esc(it.recipient_iban) + "</div>" : "")
			+ (it.purpose
				? "<div class='text-muted small'>" + esc(it.purpose) + "</div>" : "")
			+ "</td><td class='kef-r'>" + money(it.amount) + "</td></tr>";
	}).join("");

	// --- receipts -----------------------------------------------------------
	let receipts;
	if (files === null) {
		receipts = "<div class='text-muted'>"
			+ __("The attachments could not be read.") + "</div>";
	} else if (files === undefined) {
		receipts = "<div class='text-muted'>" + __("Loading …") + "</div>";
	} else if (!files.length) {
		receipts = "<div class='text-muted'>"
			+ __("No receipt is attached to this order.") + "</div>";
	} else {
		receipts = "<table class='kef-td'>" + files.map(function (fl) {
			const size = fl.file_size
				? " <span class='text-muted small'>("
					+ Math.round(fl.file_size / 1024) + " KB)</span>" : "";
			return "<tr><td><a href='" + esc(fl.file_url) + "' target='_blank'>"
				+ esc(fl.file_name || fl.name) + "</a>" + size
				+ (fl.is_private ? "" : " <span class='text-muted small'>"
					+ __("public") + "</span>")
				+ "</td></tr>";
		}).join("") + "</table>";
	}

	return "<div class='kef-detail'>"
		+ "<div class='kef-h'>" + __("Order") + "</div>" + asTable(rows)
		+ "<div class='kef-h'>" + __("Execution") + "</div>" + asTable(execution)
		+ "<div class='kef-h'>" + __("Payments") + "</div>"
		+ "<table class='kef-td'>" + items + "</table>"
		+ "<div class='kef-total'>" + __("Total") + ": <b>"
		+ money(row.total_amount) + "</b></div>"
		+ "<div class='kef-h'>" + __("Receipts") + "</div>" + receipts
		+ "</div>"
		+ "<style>"
		+ ".kef-detail .kef-h{margin:14px 0 4px;font-weight:600;"
		+ "border-bottom:1px solid var(--border-color);padding-bottom:3px}"
		+ ".kef-detail .kef-h:first-child{margin-top:0}"
		+ ".kef-td{width:100%;border-collapse:collapse}"
		+ ".kef-td td{padding:4px 6px;border-bottom:1px solid var(--border-color);"
		+ "vertical-align:top}"
		+ ".kef-td .kef-k{width:38%;color:var(--text-muted)}"
		+ ".kef-td .kef-r{text-align:right;white-space:nowrap}"
		+ ".kef-iban{font-family:monospace;font-size:11px;color:var(--text-muted)}"
		+ ".kef-total{text-align:right;padding:6px}"
		+ "</style>";
};
