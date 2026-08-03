frappe.ui.form.on("Bank Transaction", {
    refresh: function (frm) {
        // The controller comes from app_include_js. Checked rather than
        // assumed: a form that loads before it must open normally, without
        // the actions, instead of throwing on a name that is not there yet.
        if (frm.is_new() || typeof kefiya === "undefined"
                || !kefiya.transaction_actions) {
            return;
        }

        const actions = kefiya.transaction_actions;
        const reload = function () { frm.reload_doc(); };
        const entries = function () {
            return actions.entries_for(
                frm.doc.name, !!frm.doc.kefiya_followup, reload);
        };

        // Discoverable route: the standard menu. Someone who never thinks to
        // right-click still finds all three.
        entries().forEach(function (entry) {
            frm.add_custom_button(entry.label, entry.action, __("Aktionen"));
        });

        // The StarMoney route: right-click anywhere on the document.
        frm.$wrapper.off("contextmenu.kefiya")
            .on("contextmenu.kefiya", ".form-layout", function (event) {
                // Leave input fields alone -- cut/copy/paste belongs to the
                // browser and taking it away would be a loss, not a feature.
                if ($(event.target).is("input, textarea, select, [contenteditable]")) {
                    return;
                }
                actions.open_menu(event, entries());
            });
    },
});

frappe.ui.form.on("Bank Transaction Payments", {
    payment_entry: function(frm, cdt, cdn){
        let row = locals[cdt][cdn];
        frappe.db.get_doc(row.payment_document, row.payment_entry)
                .then(payment_entry => {
                    let allocated_amount = 0
                    if (row.payment_document == "Payment Entry"){
                        allocated_amount = payment_entry.total_allocated_amount
                    } else if (row.payment_document == "Journal Entry"){
                        allocated_amount = payment_entry.total_debit
                    } else if (row.payment_document == "Sales Invoice"){
                        allocated_amount = payment_entry.outstanding_amount
                    } else if (row.payment_document == "Purchase Invoice"){
                        allocated_amount = payment_entry.outstanding_amount
                    } else if (row.payment_document == "Expense Claim"){
                        allocated_amount = payment_entry.grand_total
                    }
                    
                    frappe.model.set_value(cdt, cdn, "allocated_amount", allocated_amount);
                })
    }
});