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
        kefiya_prompt_vop_release(frm, msg.docname, msg.vop_result);
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
 * name belongs to the IBAN. No money has moved. The order is parked server-side
 * and can only continue through this dialog, after a human compared the payee
 * against the underlying document -- a VoP mismatch is exactly what a payment
 * diversion (redirected invoice) looks like, so it is never waved through.
 */
function kefiya_prompt_vop_release(frm, kefiya_login, vop_result) {
    let details = "";
    if (vop_result && typeof vop_result === "object") {
        const rows = Object.keys(vop_result).map((key) =>
            "<tr><td style='padding:2px 10px 2px 0'><b>"
            + frappe.utils.escape_html(key)
            + "</b></td><td>"
            + frappe.utils.escape_html(String(vop_result[key]))
            + "</td></tr>"
        );
        details = "<table style='margin-top:8px'>" + rows.join("") + "</table>";
    } else if (vop_result) {
        details = "<pre style='white-space:pre-wrap'>"
            + frappe.utils.escape_html(String(vop_result)) + "</pre>";
    }

    const d = new frappe.ui.Dialog({
        title: __("Verification of Payee — mismatch"),
        fields: [
            {
                fieldtype: "HTML",
                options:
                    "<div class='alert alert-warning' style='margin-bottom:10px'>"
                    + __("The bank could not confirm that the payee name matches the IBAN. <b>No money has been sent.</b>")
                    + "</div>"
                    + __("Compare the recipient against the invoice before releasing. If the account details were changed recently or came in by email, treat this as a possible fraud attempt and clarify by phone using a known number.")
                    + details
            },
            {
                fieldtype: "Check",
                fieldname: "reviewed",
                label: __("I verified the recipient against the original document"),
                default: 0,
                reqd: 1
            }
        ],
        primary_action_label: __("Release transfer"),
        primary_action: function (values) {
            if (!values.reviewed) {
                frappe.msgprint(__("Please confirm you verified the recipient."));
                return;
            }
            d.hide();
            frappe.call({
                method: "kefiya.utils.client.approve_vop_transfer",
                args: {
                    kefiya_login: kefiya_login,
                    user_scope: frm.docname,
                    confirmed: 1
                },
                freeze: true,
                freeze_message: __("Releasing transfer..."),
                callback: function (r) {
                    kefiya_handle_transfer_response(frm, r.message);
                }
            });
        },
        secondary_action_label: __("Cancel transfer"),
        secondary_action: function () {
            d.hide();
            frappe.show_alert({
                message: __("Transfer not released. No money was sent."),
                indicator: "orange"
            });
        }
    });
    d.show();
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
