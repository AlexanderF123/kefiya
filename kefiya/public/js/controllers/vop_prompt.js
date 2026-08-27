// Copyright (c) 2026, Phamos GmbH and contributors
// For license information, please see license.txt
//
// The box that shows what the bank said about a payee, and releases the order.
//
//   kefiya.vop_prompt(opts)   opts: {login, scope, vop_result, payee, onResult}
//
// Its own file for the same reason the TAN box has one: two callers -- the
// transfer form and the outgoing-payments page -- and no share in what either
// of them does otherwise.
//
// It moved here after a real transfer went missing. The outgoing-payments page
// had no branch for a parked payee check at all: the send returned
// "vop_mismatch", the page fell into its else and reported "handed to the bank
// -- 1 order" in green. Nothing had been handed to anyone. The order sat
// parked, and the only way to release it was a dialog that lived in a file
// that page could not reach.

frappe.provide("kefiya");

(function () {
    "use strict";

    function esc(value) {
        return frappe.utils.escape_html(String(value === undefined || value === null ? "" : value));
    }

    // Who the order pays, in the lines that decide the question. The raw
    // answer is shown below it as well, because it is what the bank actually
    // said -- but nobody compares an invoice against a parsed segment.
    function payeeBlock(payee) {
        if (!payee || !payee.name) return "";
        var row = function (label, value) {
            return "<tr><td style='padding:2px 12px 2px 0;color:#6c7680'>"
                + esc(label) + "</td><td><b>" + esc(value) + "</b></td></tr>";
        };
        var rows = row(__("Payee on the order"), payee.name);
        if (payee.iban) rows += row(__("IBAN"), payee.iban);
        if (payee.bank_name) rows += row(__("Name at the Bank"), payee.bank_name);
        if (payee.result) rows += row(__("Bank's Answer"), payee.result);
        return "<table style='margin:10px 0'>" + rows + "</table>";
    }

    function rawBlock(vop_result) {
        if (vop_result && typeof vop_result === "object") {
            var rows = Object.keys(vop_result).map(function (key) {
                return "<tr><td style='padding:2px 10px 2px 0'><b>" + esc(key)
                    + "</b></td><td>" + esc(vop_result[key]) + "</td></tr>";
            });
            return "<table style='margin-top:8px'>" + rows.join("") + "</table>";
        }
        if (vop_result) {
            return "<pre style='white-space:pre-wrap'>" + esc(vop_result) + "</pre>";
        }
        return "";
    }

    function vopPrompt(opts) {
        opts = opts || {};
        var payee = opts.payee || {};
        var remembers = !!(payee.name && payee.iban);

        var d = new frappe.ui.Dialog({
            title: __("Verification of Payee — mismatch"),
            fields: [
                {
                    fieldtype: "HTML",
                    options:
                        "<div class='alert alert-warning' style='margin-bottom:10px'>"
                        + __("The bank could not confirm that the payee name matches the IBAN. <b>No money has been sent.</b>")
                        + "</div>"
                        + __("Compare the recipient against the invoice before releasing. If the account details were changed recently or came in by email, treat this as a possible fraud attempt and clarify by phone using a known number.")
                        + payeeBlock(payee)
                        + (remembers
                            ? "<div class='text-muted' style='margin-bottom:8px'>"
                              + __("Once you release it, this payee is remembered: a later payment to the same name and the same IBAN goes through without asking again.")
                              + "</div>"
                            : "")
                        + rawBlock(opts.vop_result)
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
                        kefiya_login: opts.login,
                        user_scope: opts.scope || opts.login,
                        confirmed: 1
                    },
                    freeze: true,
                    freeze_message: __("Releasing transfer..."),
                    callback: function (r) {
                        if (opts.onResult) opts.onResult((r && r.message) || {});
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

    kefiya.vop_prompt = vopPrompt;
})();
