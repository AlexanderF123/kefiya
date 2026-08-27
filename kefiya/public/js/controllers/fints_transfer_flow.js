// Copyright (c) 2026, Phamos GmbH and contributors
// For license information, please see license.txt

/**
 * Shared outgoing-transfer flow: bank response handling, Verification-of-Payee
 * release and the TAN prompt.
 *
 * Used by both entry points -- a transfer raised from a Payment Request and a
 * free-entry Kefiya Transfer -- so the money-moving dialogs stay identical
 * rather than drifting apart in two copies.
 */
function kefiya_handle_transfer_response(frm, msg) {
    if (!msg) {
        frappe.msgprint(__("No response from server."));
        return;
    }
    if (msg.status === "submitted") {
        frappe.show_alert({ message: __("Transfer submitted."), indicator: "green" });
        frm.reload_doc();
    } else if (msg.status === "tan_required") {
        kefiya_prompt_transfer_tan(frm, msg.docname);
    } else if (msg.status === "vop_mismatch") {
        kefiya_prompt_vop_release(frm, msg.docname, msg.vop_result, msg.payee);
    } else {
        frappe.msgprint({
            title: __("Transfer failed"),
            indicator: "red",
            message: msg.message || __("Unknown error")
        });
    }
}

/**
 * Verification of Payee mismatch: the bank could not confirm that the payee
 * name belongs to the IBAN. No money has moved. The order is parked
 * server-side and can only continue through this box, after a human compared
 * the payee against the underlying document -- a VoP mismatch is exactly what
 * a payment diversion (redirected invoice) looks like, so it is never waved
 * through.
 *
 * The box itself is kefiya.vop_prompt, in the bundle. It used to live here,
 * and this file is included into doctype JS rather than bundled -- so the
 * outgoing-payments page could not reach it and reported a parked order as
 * sent. One box, both callers.
 */
function kefiya_prompt_vop_release(frm, kefiya_login, vop_result, payee) {
    kefiya.vop_prompt({
        login: kefiya_login,
        scope: frm.docname,
        vop_result: vop_result,
        payee: payee,
        onResult: function (msg) {
            kefiya_handle_transfer_response(frm, msg);
        }
    });
}

function kefiya_prompt_transfer_tan(frm, kefiya_login) {
    const d = new frappe.ui.Dialog({
        title: __("Enter TAN to authorise the transfer"),
        fields: [
            {
                fieldname: "tan",
                fieldtype: "Data",
                label: __("TAN"),
                reqd: 1,
                description: __("Enter the TAN from your bank's app/device. For push-TAN, confirm in the app, then submit.")
            }
        ],
        primary_action_label: __("Confirm transfer"),
        primary_action: function (values) {
            d.hide();
            frappe.call({
                method: "kefiya.utils.client.send_transfer_tan",
                args: {
                    kefiya_login: kefiya_login,
                    tan: values.tan,
                    user_scope: frm.docname
                },
                freeze: true,
                freeze_message: __("Sending TAN..."),
                callback: function (r) {
                    if (r.message && r.message.status === "submitted") {
                        frappe.show_alert({
                            message: __("Transfer authorised and submitted."),
                            indicator: "green"
                        });
                        frm.reload_doc();
                    } else {
                        frappe.msgprint({
                            title: __("TAN failed"),
                            indicator: "red",
                            message: (r.message && r.message.message) || __("Unknown error")
                        });
                    }
                }
            });
        }
    });
    d.show();
}
