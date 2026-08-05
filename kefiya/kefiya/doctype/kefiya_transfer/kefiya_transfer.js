// Copyright (c) 2026, Phamos GmbH and contributors
// For license information, please see license.txt

{% include "kefiya/public/js/controllers/fints_progress_log.js" %}
{% include "kefiya/public/js/controllers/fints_interactive.js" %}
{% include "kefiya/public/js/controllers/fints_transfer_flow.js" %}
{% include "kefiya/public/js/controllers/account_capabilities.js" %}

frappe.ui.form.on("Kefiya Transfer", {
	onload: function (frm) {
		kefiya.interactive.progressbar(frm);
		// Only the company's own accounts are offered, and never the one the
		// money is drawn from: a transfer from an account to itself is not a
		// transfer, and the bank only says so after a TAN was spent on it.
		frm.set_query("own_account", "items", function () {
			return {
				query: "kefiya.utils.own_transfer.own_account_query",
				filters: {
					kefiya_login: frm.doc.kefiya_login,
					company: frm.doc.company,
				},
			};
		});
	},

	kefiya_login: function (frm) {
		kefiya_apply_capabilities(frm);
	},

	instant_payment: function (frm) {
		kefiya_apply_capabilities(frm);
	},

	manage_due_date: function (frm) {
		kefiya_apply_capabilities(frm);
	},

	refresh: function (frm) {
		// What the bank allows on this account decides which of the options
		// below are offered at all. Applied asynchronously: the answer comes
		// from the server, and the form must not wait for it to render.
		kefiya_apply_capabilities(frm);

		// Sending is deliberately separate from submitting: approving a
		// transfer must never move money as a side effect.
		if (frm.doc.docstatus === 1 && frm.doc.status !== "Sent") {
			if (!frm.doc.on_hold) {
				frm.add_custom_button(__("Send to bank"), function () {
					kefiya_confirm_and_send(frm);
				}).addClass("btn-primary");
			}

			// Holding back is allowed after approval because it changes only
			// when the order goes out, not what it says.
			frm.add_custom_button(
				frm.doc.on_hold ? __("Release") : __("Hold back"),
				function () {
					frm.call("set_hold", { on_hold: frm.doc.on_hold ? 0 : 1 })
						.then(() => frm.reload_doc());
				}
			);
		}

		if (frm.doc.on_hold && frm.doc.status !== "Sent") {
			frm.dashboard.set_headline_alert(
				__("Held back — this order stays in the outbox and is skipped by a collective send."),
				"orange"
			);
		}

		if (frm.doc.status === "Sent") {
			frm.dashboard.set_headline_alert(
				__("Sent to the bank. Recall it with your bank if needed — it cannot be withdrawn here."),
				"green"
			);
		} else if (frm.doc.vop_pending) {
			frm.dashboard.set_headline_alert(
				__("The bank flagged a payee mismatch. Use 'Send to bank' to review and release it."),
				"orange"
			);
		}

		kefiya_render_summary(frm);
	},

	items_on_form_rendered: function (frm) {
		kefiya_render_summary(frm);
	},
});

frappe.ui.form.on("Kefiya Transfer Item", {
	amount: function (frm) {
		kefiya_recalculate(frm);
	},
	own_account: function (frm, cdt, cdn) {
		// A Kontouebertrag: the recipient is one of our own accounts. Name and
		// IBAN come from there so nobody types an IBAN they already own --
		// that is where transposed digits come from, and a transposed digit
		// pays a stranger just as reliably here as anywhere else.
		const row = locals[cdt][cdn];
		if (!row.own_account) {
			return;
		}
		frappe.db.get_value("Bank Account", row.own_account,
			["account_name", "iban"]).then(function (r) {
			const a = (r && r.message) || {};
			if (a.iban) {
				frappe.model.set_value(cdt, cdn, "recipient_iban",
					a.iban.replace(/[\s-]/g, "").toUpperCase());
			}
			if (a.account_name && !row.recipient_name) {
				frappe.model.set_value(cdt, cdn, "recipient_name",
					a.account_name);
			}
		});
	},
	items_remove: function (frm) {
		kefiya_recalculate(frm);
	},
	recipient_iban: function (frm, cdt, cdn) {
		// Immediate feedback on a mistyped IBAN. With free recipient entry
		// there is no invoice to check against, so the checksum is the only
		// automatic defence -- and catching it here beats a server error.
		const row = locals[cdt][cdn];
		if (!row.recipient_iban) {
			return;
		}
		const iban = row.recipient_iban.replace(/[\s-]/g, "").toUpperCase();
		frappe.model.set_value(cdt, cdn, "recipient_iban", iban);
		if (!kefiya_iban_is_valid(iban)) {
			frappe.msgprint({
				title: __("Invalid IBAN"),
				indicator: "red",
				message: __("{0} is not a valid IBAN — the checksum does not match. Please re-check the recipient's account.", [frappe.utils.escape_html(iban)]),
			});
		}
	},
});

/** ISO 7064 mod-97 check, mirroring the server-side validation. */
function kefiya_iban_is_valid(iban) {
	if (!iban || iban.length < 15 || iban.length > 34) {
		return false;
	}
	if (!/^[A-Z]{2}[0-9]{2}[A-Z0-9]+$/.test(iban)) {
		return false;
	}
	const rearranged = iban.slice(4) + iban.slice(0, 4);
	let digits = "";
	for (const ch of rearranged) {
		digits += /[0-9]/.test(ch) ? ch : (ch.charCodeAt(0) - 55).toString();
	}
	// The number exceeds Number.MAX_SAFE_INTEGER, so reduce piecewise.
	let remainder = 0;
	for (const ch of digits) {
		remainder = (remainder * 10 + parseInt(ch, 10)) % 97;
	}
	return remainder === 1;
}

function kefiya_recalculate(frm) {
	let total = 0;
	(frm.doc.items || []).forEach((row) => {
		total += flt(row.amount);
	});
	frm.set_value("total_amount", total);
	frm.set_value("payment_count", (frm.doc.items || []).length);
	kefiya_render_summary(frm);
	// One payment goes out as HKCCS, several as the collective HKCCM -- a
	// different business transaction, which a bank may allow on this account
	// or not. So the answer changes with the number of rows.
	kefiya_apply_capabilities(frm);
}

/**
 * Offer only what the bank allows on this account.
 *
 * Hides what was REFUSED and leaves everything else alone. An account that has
 * never been fetched says "unknown" to every question, and unknown is not a
 * reason to take a button away -- see account_capabilities.js.
 */
function kefiya_apply_capabilities(frm) {
	if (!frm.doc.kefiya_login) {
		return;
	}
	kefiya.capabilities.load(frm.doc.kefiya_login).then(function (info) {
		if (!info || !info.capabilities) {
			return;
		}

		const count = (frm.doc.items || []).length || 1;

		// An instant payment is its own transaction (HKIPZ/HKIPM). Where the
		// bank does not offer it here, the tick box is not just useless, it
		// is a trap: it changes what is sent and the order fails at the bank.
		const instant = kefiya.capabilities.required(count, false, true);
		const instant_ok = kefiya.capabilities.allows(info, instant);
		frm.toggle_display("instant_payment", instant_ok);
		if (!instant_ok && frm.doc.instant_payment && frm.doc.docstatus === 0) {
			frm.set_value("instant_payment", 0);
		}

		// Letting the bank hold the date is HKCSE/HKCME. Where it is refused,
		// the date can still be managed here -- that is our own doing and
		// needs nothing from the bank -- so the field stays and only the
		// choice to hand the date over goes.
		const dated = kefiya.capabilities.required(count, true, false);
		const dated_ok = kefiya.capabilities.allows(info, dated);
		if (!dated_ok && frm.doc.docstatus === 0) {
			frm.set_df_property(
				"manage_due_date", "description",
				__("The bank does not accept dated orders on this account, so the date is managed here.")
			);
			if (!frm.doc.manage_due_date) {
				frm.set_value("manage_due_date", 1);
			}
		}

		// And the order itself. Saying so here rather than at the bank is the
		// difference between a sentence and a spent TAN.
		const needed = kefiya.capabilities.required(
			count,
			!frm.doc.manage_due_date && !!frm.doc.execution_date,
			!!frm.doc.instant_payment
		);
		if (kefiya.capabilities.refuses(info, needed)) {
			frm.remove_custom_button(__("Send to bank"));
			frm.dashboard.set_headline_alert(
				__("The bank does not allow \"{0}\" on this account. Sending would be refused after the TAN, so it is not offered here.", [
					kefiya.capabilities.label(needed),
				]),
				"red"
			);
		}
	});
}

function kefiya_render_summary(frm) {
	const count = (frm.doc.items || []).length;
	if (!count) {
		return;
	}
	const mode = count > 1
		? __("Collective order ({0} payments) — a single TAN authorises all of them.", [count])
		: __("Single transfer.");
	frm.dashboard.clear_comment();
	frm.dashboard.add_comment(mode, "blue", true);
}

function kefiya_confirm_and_send(frm) {
	const count = (frm.doc.items || []).length;
	const rows = (frm.doc.items || []).map((row) =>
		"<tr><td>" + frappe.utils.escape_html(row.recipient_name || "")
		+ "</td><td style='font-family:monospace'>"
		+ frappe.utils.escape_html(row.recipient_iban || "")
		+ "</td><td style='text-align:right'>"
		+ format_currency(row.amount) + "</td></tr>"
	).join("");

	const d = new frappe.ui.Dialog({
		title: count > 1 ? __("Send collective order") : __("Send transfer"),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				options:
					"<div class='alert alert-warning'>"
					+ __("You are about to move {0} from {1}. Check every recipient — a transfer cannot be undone here.", [
						"<b>" + format_currency(frm.doc.total_amount) + "</b>",
						frappe.utils.escape_html(frm.doc.kefiya_login || ""),
					])
					+ "</div>"
					+ "<table class='table table-bordered'><thead><tr><th>"
					+ __("Recipient") + "</th><th>" + __("IBAN") + "</th><th style='text-align:right'>"
					+ __("Amount") + "</th></tr></thead><tbody>"
					+ rows + "</tbody></table>"
					+ (frm.doc.instant_payment
						? "<p>" + __("Sent as an instant payment (SEPA Instant).") + "</p>"
						: ""),
			},
			{
				fieldtype: "Check",
				fieldname: "confirmed",
				label: __("I checked every recipient and amount"),
				reqd: 1,
			},
		],
		primary_action_label: __("Send now"),
		primary_action: function (values) {
			if (!values.confirmed) {
				frappe.msgprint(__("Please confirm you checked the recipients."));
				return;
			}
			d.hide();
			frappe.call({
				method: "kefiya.utils.client.submit_kefiya_transfer",
				args: {
					transfer_name: frm.doc.name,
					user_scope: frm.docname,
					confirmed: 1,
				},
				freeze: true,
				freeze_message: __("Sending to bank..."),
				callback: function (r) {
					kefiya_handle_transfer_response(frm, r.message);
				},
			});
		},
	});
	d.show();
}
