// Copyright (c) 2026, Phamos GmbH and contributors
// For license information, please see license.txt
//
// The three things one does with a booking one is looking at: print it, pass
// the money on, mark it for later. In StarMoney they sit on the right mouse
// button, so they sit there here too -- and, because a menu that only opens on
// right-click is a menu half the people never find, on the form's Actions menu
// as well. Both routes call the same three functions.

frappe.provide("kefiya.transaction_actions");

(function () {
    "use strict";

    const ACTIONS = kefiya.transaction_actions;

    // The print format built for a single booking. Where it is not installed,
    // printing falls back to whatever the site's default is rather than
    // failing -- a missing format is not a reason to refuse to print.
    const SINGLE_RECEIPT = "Banktransaktion Einzelbeleg";

    ACTIONS.print = function (name) {
        if (!name) return;
        frappe.db.get_value("Print Format", SINGLE_RECEIPT, "name")
            .then(function (r) {
                const format = (r && r.message && r.message.name)
                    ? SINGLE_RECEIPT : null;
                const url = frappe.urllib.get_full_url(
                    "/printview?doctype=" + encodeURIComponent("Bank Transaction")
                    + "&name=" + encodeURIComponent(name)
                    + (format ? "&format=" + encodeURIComponent(format) : "")
                    + "&no_letterhead=0&trigger_print=1");
                window.open(url, "_blank");
            });
    };

    ACTIONS.mark = function (names, flagged, after) {
        const list = Array.isArray(names) ? names : [names];
        if (!list.length) return;
        frappe.call({
            method: "kefiya.utils.transaction_actions.set_followup",
            args: { names: list, flagged: flagged ? 1 : 0 },
            freeze: true,
            freeze_message: __("Kennzeichen wird gesetzt ..."),
            callback: function (r) {
                const res = (r && r.message) || {};
                if (res.reason) {
                    frappe.msgprint({
                        title: __("Wiedervorlage"),
                        message: res.reason,
                        indicator: "orange",
                    });
                    return;
                }
                frappe.show_alert({
                    message: flagged
                        ? __("{0} zur Wiedervorlage vorgemerkt",
                             [res.updated || 0])
                        : __("Kennzeichen bei {0} entfernt", [res.updated || 0]),
                    indicator: "green",
                });
                if (after) after(res);
            },
        });
    };

    // Forward: the booking supplies the amount and the counterparty, the user
    // supplies everything they want different. Nothing is saved here -- what
    // opens is an unsaved draft, so a mis-click costs nothing.
    ACTIONS.forward = function (name) {
        frappe.call({
            method: "kefiya.utils.transaction_actions.transfer_from_transaction",
            args: { name: name },
            freeze: true,
            callback: function (r) {
                const data = r && r.message;
                if (!data) return;
                if (!data.kefiya_login) {
                    frappe.msgprint({
                        title: __("Weiter überweisen"),
                        message: __("Zu diesem Bankkonto ist kein Kefiya-Zugang hinterlegt. Ohne Zugang lässt sich von hier nichts überweisen."),
                        indicator: "orange",
                    });
                    return;
                }
                frappe.new_doc("Kefiya Transfer", {
                    kefiya_login: data.kefiya_login,
                    company: data.company,
                }, function (doc) {
                    doc.items = [];
                    const row = frappe.model.add_child(doc, "items");
                    Object.assign(row, data.item);
                    frappe.show_alert({
                        message: __("Aus Buchung {0} übernommen -- bitte Empfänger und Betrag prüfen.", [data.source]),
                        indicator: "blue",
                    });
                });
            },
        });
    };

    // ---------------------------------------------------------------------
    // The menu itself
    // ---------------------------------------------------------------------

    ACTIONS.entries_for = function (name, is_flagged, after) {
        return [
            {
                label: __("Drucken"),
                icon: "printer",
                action: function () { ACTIONS.print(name); },
            },
            {
                label: __("Weiter überweisen"),
                icon: "arrow-right",
                action: function () { ACTIONS.forward(name); },
            },
            {
                label: is_flagged
                    ? __("Wiedervorlage entfernen")
                    : __("Zur Wiedervorlage markieren"),
                icon: "flag",
                action: function () {
                    ACTIONS.mark(name, !is_flagged, after);
                },
            },
        ];
    };

    // Attach the menu to any table of bookings, wherever it is drawn. The
    // Workspace pages (Online-Banking, Finance Overview) build their own rows
    // and would otherwise each grow their own copy of this.
    //
    //   container  DOM element the rows live in
    //   selector   what a row looks like, e.g. "tr.fr"
    //   name_of    row element -> Bank Transaction name
    //   flagged_of row element -> is it already marked? (optional)
    //   after      called once something changed (optional)
    ACTIONS.attach_to = function (container, options) {
        if (!container || !options || !options.selector || !options.name_of) {
            return;
        }
        const rows = container.querySelectorAll(options.selector);
        Array.prototype.forEach.call(rows, function (row) {
            row.oncontextmenu = function (event) {
                const name = options.name_of(row);
                if (!name) return;
                const flagged = options.flagged_of
                    ? !!options.flagged_of(row) : false;
                ACTIONS.open_menu(
                    event, ACTIONS.entries_for(name, flagged, options.after));
            };
        });
    };

    function close_menu() {
        $(".kefiya-context-menu").remove();
        $(document).off(".kefiya-context-menu");
    }

    ACTIONS.open_menu = function (event, entries) {
        event.preventDefault();
        close_menu();

        const menu = $('<ul class="dropdown-menu kefiya-context-menu"></ul>');
        entries.forEach(function (entry) {
            const item = $('<li><a class="dropdown-item" href="#"></a></li>');
            item.find("a").text(entry.label).on("click", function (e) {
                e.preventDefault();
                close_menu();
                entry.action();
            });
            menu.append(item);
        });

        menu.css({
            display: "block",
            position: "fixed",
            left: event.clientX + "px",
            top: event.clientY + "px",
            "z-index": 1060,
        }).appendTo(document.body);

        // Keep it on screen when the click was near an edge.
        const rect = menu[0].getBoundingClientRect();
        if (rect.right > window.innerWidth) {
            menu.css("left", Math.max(0, window.innerWidth - rect.width - 8) + "px");
        }
        if (rect.bottom > window.innerHeight) {
            menu.css("top", Math.max(0, window.innerHeight - rect.height - 8) + "px");
        }

        // Any click elsewhere, any scroll, Escape: gone.
        $(document).on("click.kefiya-context-menu", close_menu);
        $(document).on("scroll.kefiya-context-menu", close_menu);
        $(document).on("keydown.kefiya-context-menu", function (e) {
            if (e.key === "Escape") close_menu();
        });
    };
})();
