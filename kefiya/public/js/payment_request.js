{% include "kefiya/public/js/controllers/fints_transfer_flow.js" %}

frappe.ui.form.on('Payment Request', {
    refresh: function(frm) {
        frm.set_df_property('transaction_date', 'reqd', 1);
        frm.set_df_property('company', 'reqd', 1);
        frm.set_df_property('bank_account', 'reqd', 1);
        frm.set_df_property('company_bank_account', 'reqd', 1);

        // FinTS direct transfer (no manual upload) -- only for a submitted
        // Outward request, and always behind an explicit confirmation + TAN.
        if (frm.doc.docstatus === 1 && frm.doc.payment_request_type === "Outward") {
            frm.add_custom_button(__("Send via FinTS"), function() {
                kefiya_submit_transfer_via_fints(frm);
            });
        }
    },

    setup: function(frm) {
        frm.set_query("company_bank_account", function() {
            return {
                filters: {
                    is_company_account: 1,
                    company: frm.doc.company
                }
            }
        });

        frm.set_query("bank_account", function() {
            return {
                filters: {
                    is_company_account: 0,
                    party_type: frm.doc.party_type,
                    party: frm.doc.party
                }
            }
        });
    },

    before_submit: function(frm) {

        frappe.call({
            method: "kefiya.events.hammer_script.payment_request_on_submit.export_request",
            args: {
                payment_request_name: frm.doc.name
            },
            callback: function(r) {
                if (r.message.status == "success") {
                    var export_action = r.message.export_action;
                    var is_download = export_action == "Download SEPA XML";
                    var is_email = export_action == "Send SEPA XML via Email";

                    if (is_download) {
                        var content = r.message.data;
                        var blob = new Blob([content], { type: "application/xml;charset=utf-8;" });

                        var link = document.createElement("a");
                        if (link.download !== undefined) {
                            var url = URL.createObjectURL(blob);
                            link.setAttribute("href", url);
                            link.setAttribute("download", "moneyplex_" + frm.doc.name + ".xml");
                            link.style.visibility = 'hidden';
                            document.body.appendChild(link);
                            link.click();
                            document.body.removeChild(link);
                        }
                    }
                    else if (is_email) {

                        var recipient_email = r.message.recipient_email;
                        var file_content = r.message.data;

                        frappe.msgprint({
                            title: __('Sending Email'),
                            indicator: 'blue',
                            message: __('Email is being sent to {0}. Please wait...', [recipient_email])
                        });

                        frappe.call({
                            method: "kefiya.events.hammer_script.payment_request_on_submit.send_sepa_xml_via_email",
                            args: {
                                recipient_email: recipient_email,
                                xml_content: file_content
                            },
                            callback: function (r) {

                                if (r.message) {
                                    if (r.message.status === "success") {
                                        frappe.show_alert({
                                            message: __('Email sent successfully to {0}', [recipient_email]),
                                            indicator: 'green'
                                        });
                                    } else {
                                        frappe.msgprint({
                                            title: __('Error'),
                                            indicator: 'red',
                                            message: r.message.message
                                        });
                                        frappe.validated = false;
                                    }
                                }
                            }
                        });
                    }
                } else {
                    frappe.msgprint(__('Error during export: {0}', [r.message.message]));
                    frappe.validated = false;
                }
            }
        });
    }
});


// --- FinTS outgoing transfer (human-in-the-loop: confirm + TAN) ---------------

function kefiya_submit_transfer_via_fints(frm) {
    const d = new frappe.ui.Dialog({
        title: __("SEPA transfer via FinTS"),
        fields: [
            {
                fieldtype: "HTML",
                options: __("Send a SEPA transfer of {0} to {1} ({2}) via FinTS? The amount is capped at the outstanding amount and you will be asked for a TAN.", [
                    frappe.utils.escape_html(format_currency(frm.doc.grand_total, frm.doc.currency)),
                    frappe.utils.escape_html(frm.doc.party || ""),
                    frappe.utils.escape_html(frm.doc.bank_account || "")
                ])
            },
            {
                fieldtype: "Check",
                fieldname: "instant_payment",
                label: __("Echtzeitüberweisung (SEPA Instant)"),
                default: 1,
                description: __("Real-time credit transfer (HKIPZ). The debtor bank and account must support instant payments, otherwise the bank rejects the order.")
            }
        ],
        primary_action_label: __("Send"),
        primary_action(values) {
            d.hide();
            frappe.call({
                method: "kefiya.utils.client.submit_payment_request_via_fints",
                args: {
                    payment_request_name: frm.doc.name,
                    user_scope: frm.docname,
                    confirmed: 1,
                    instant_payment: values.instant_payment ? 1 : 0
                },
                freeze: true,
                freeze_message: __("Submitting transfer via FinTS..."),
                callback: function (r) {
                    kefiya_handle_transfer_response(frm, r.message);
                }
            });
        }
    });
    d.show();
}
