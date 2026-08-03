// Copyright (c) 2026, Phamos GmbH and contributors
// For license information, please see license.txt
//
// The same three actions in the list, where one is usually looking when one
// wants them: right-click a row for that booking, or tick several and use the
// bulk entry to mark them all at once.

frappe.listview_settings["Bank Transaction"] = Object.assign(
    frappe.listview_settings["Bank Transaction"] || {},
    {
        add_fields: ["kefiya_followup"],

        get_indicator: function (doc) {
            // A flag one cannot see in the list is a flag one has to remember,
            // which is the thing the flag was meant to replace.
            if (doc.kefiya_followup) {
                return [__("Wiedervorlage"), "orange", "kefiya_followup,=,1"];
            }
            if (doc.docstatus === 2) return [__("Storniert"), "red", "docstatus,=,2"];
            if (doc.unallocated_amount > 0) {
                return [__("Nicht zugeordnet"), "blue", "unallocated_amount,>,0"];
            }
            if (doc.docstatus === 1) return [__("Verbucht"), "green", "docstatus,=,1"];
            return [__("Entwurf"), "gray", "docstatus,=,0"];
        },

        onload: function (listview) {
            if (typeof kefiya === "undefined") return;
            const actions = kefiya.transaction_actions;
            if (!actions) return;

            listview.page.add_actions_menu_item(
                __("Zur Wiedervorlage markieren"), function () {
                    const names = listview.get_checked_items(true);
                    if (!names.length) {
                        frappe.msgprint(__("Bitte zuerst Buchungen auswählen."));
                        return;
                    }
                    actions.mark(names, true, function () {
                        listview.refresh();
                    });
                }, false);

            listview.page.add_actions_menu_item(
                __("Wiedervorlage entfernen"), function () {
                    const names = listview.get_checked_items(true);
                    if (!names.length) {
                        frappe.msgprint(__("Bitte zuerst Buchungen auswählen."));
                        return;
                    }
                    actions.mark(names, false, function () {
                        listview.refresh();
                    });
                }, false);

            // Right-click a row. Delegated once on the list container, so rows
            // that are drawn later are covered without re-binding.
            $(listview.$result).off("contextmenu.kefiya")
                .on("contextmenu.kefiya", ".list-row-container", function (event) {
                    if ($(event.target).is("input, a, .list-row-checkbox")) return;
                    const name = $(this).find("[data-name]").first().attr("data-name")
                        || $(this).attr("data-name");
                    if (!name) return;
                    const row = (listview.data || []).find(function (d) {
                        return d.name === name;
                    }) || {};
                    actions.open_menu(event, actions.entries_for(
                        name, !!row.kefiya_followup, function () {
                            listview.refresh();
                        }));
                });
        },
    }
);
