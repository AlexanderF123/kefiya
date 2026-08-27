// Copyright (c) 2026, Phamos GmbH and contributors
// For license information, please see license.txt
//
// One collective fetch across every bank access, for any page that wants one.
//
//   kefiya.bank_refresh({mount, btn, buttonLabel, onRefreshView, onDone, only})
//
// "only" is a list of Kefiya Login names. Given, the run touches those and
// nothing else -- that is what the "fetch the failed ones again" link in the
// finished panel uses, and what a caller wanting a single access passes.
//
// Returns a Promise resolving to the run summary, or to null when the run was
// not started at all -- missing permission, no accesses configured, or another
// run already going.
//
// Three things this exists to get right, each of them learned the hard way:
//
// No modal progress dialog. frappe.show_progress reuses its dialog only while
// the previous one is still visible, so every hide_progress made the next
// access open a fresh one -- one dialog per access -- and the overlapping
// fade-outs left orphaned modals behind. Progress lives in a panel on the page
// instead, which the modal used to cover anyway.
//
// One line of progress, not one per access. With 54 accesses the per-access
// list pushed the whole page out of sight. Everything that used to stand in
// those rows now goes into a log that is opened on demand: one block per
// account saying what was fetched and what was not, with the reason. Normally
// nobody needs it.
//
// A refusal is not a failure. The bank not offering a query and the query
// going wrong are shown as different things. Rendering both as "not available"
// once made 88 real failures of a single run read like an absent bank feature.
//
// Parallel per bank, sequential within one. FinTS allows a single dialog per
// access: two at once trigger two strong authentications and overwrite the
// shared client state that makes one TAN count for the whole bank. Different
// banks are independent. The server says which accesses belong together.

frappe.provide("kefiya");

(function () {
    "use strict";

    // Resolved when it is needed, not when the file loads: the bundle may be
    // parsed before the translations for this session are in place.
    function idleLabel() { return __("Fetch transactions"); }
    var run = null;

    // Colours come from the desk's own tokens, so the panel follows whatever
    // theme the site uses instead of carrying one of its own.
    var C_ERR = "var(--red-500, #c0392b)";
    var C_OK = "var(--green-500, #1a7f37)";
    var C_WAIT = "var(--orange-500, #b26a00)";
    var C_MUTED = "var(--text-muted, #6c757d)";

    // Server error boxes are muted for the whole run. Depth counting keeps
    // nested muting correct, and every exit path unmutes, so a failed run
    // never leaves the session silent.
    var muteDepth = 0;
    var muteKeep = null;

    function muteErrors() {
        if (muteDepth === 0 && frappe.request && frappe.request.report_error) {
            muteKeep = frappe.request.report_error;
            frappe.request.report_error = function () {};
        }
        muteDepth++;
    }

    function unmuteErrors() {
        if (muteDepth === 0) return;
        muteDepth--;
        if (muteDepth === 0 && frappe.request && muteKeep) {
            frappe.request.report_error = muteKeep;
            muteKeep = null;
        }
    }

    function esc(v) {
        if (v === null || v === undefined) v = "";
        return frappe.utils.escape_html("" + v);
    }

    // A readable message out of a failed frappe.call response.
    function errText(r) {
        try {
            if (!r) return "";
            var d = r.responseJSON || r;
            if (d && d.exception) return "" + d.exception;
            if (d && d._error_message) return "" + d._error_message;
            var sm = (d && d._server_messages) || r._server_messages;
            if (sm) {
                try {
                    var a = JSON.parse(sm);
                    if (a && a.length) {
                        var o = JSON.parse(a[0]);
                        return o.message || a[0];
                    }
                } catch (ignoredA) {
                    return "" + sm;
                }
            }
            if (r.responseText) return ("" + r.responseText).slice(0, 220);
        } catch (ignoredB) {}
        return "";
    }

    // Held by reference, not by selector, so it works inside a shadow root as
    // well as in plain DOM.
    function panel() {
        if (!run || !run.mount) return null;
        if (run.panel && run.panel.isConnected) return run.panel;
        var el = document.createElement("div");
        el.setAttribute("style",
            "border:1px solid var(--border-color);border-radius:8px;"
            + "padding:10px 12px;margin-bottom:12px;background:var(--card-bg)");
        run.mount.insertAdjacentElement("afterbegin", el);
        run.panel = el;
        return el;
    }

    function render() {
        var el = panel();
        if (!el) return;
        var total = (run.order || []).length || 1;
        var pct = Math.min(100, Math.round(run.done / total * 100));

        var head;
        if (run.busy) {
            head = __("Fetching accounts …") + " " + pct + " %";
        } else {
            head = __("Account fetch finished") + " · "
                + __("{0} of {1} accesses", [run.done, total]);
            if (run.fail) head += " · " + __("{0} failed", [run.fail]);
            if (run.tan) head += " · " + __("{0}× awaiting release", [run.tan]);
        }

        var barColor = run.fail ? C_ERR : C_OK;
        var bar = "<div style='height:6px;border-radius:3px;"
            + "background:var(--border-color);overflow:hidden;margin:6px 0 2px'>"
            + "<div style='height:6px;width:" + pct + "%;background:" + barColor
            + "'></div></div>";

        // The log link used to appear only once the run had finished. A
        // collective fetch takes minutes, so an access that broke in the first
        // one stayed invisible for the rest of them -- and by the time the log
        // could be opened, the run had long moved past it. It is offered from
        // the first entry on.
        var links = "";
        if (run.log && run.log.length) {
            links = "<div style='margin-top:6px'>"
                + "<a href='#' data-kefiya='log' style='font-size:11px'>"
                + esc(__("Show log")) + "</a>";
        }
        if (!run.busy && run.onRefreshView) {
            links = (links || "<div style='margin-top:6px'>")
                + (run.log && run.log.length
                    ? " <span style='color:" + C_MUTED + "'>·</span> " : "")
                + "<a href='#' data-kefiya='upd' style='font-size:11px'>"
                + esc(__("Refresh view")) + "</a>";
        }
        // Repeating the whole run to reach the three accesses that broke costs
        // minutes and a strong authentication per bank. This repeats only
        // those three.
        var again = run.busy ? [] : unfinished();
        if (again.length) {
            links = (links || "<div style='margin-top:6px'>")
                + (links ? " <span style='color:" + C_MUTED + "'>·</span> " : "")
                + "<a href='#' data-kefiya='again' style='font-size:11px'>"
                + esc(__("Fetch the {0} unfinished accesses again",
                         [again.length])) + "</a>";
        }
        if (links) links += "</div>";

        el.innerHTML = "<div style='font-weight:600;color:"
            + (run.fail ? C_ERR : "var(--text-color)") + "'>"
            + esc(head) + "</div>" + bar + liveProblems() + links;

        var u = el.querySelector("[data-kefiya=upd]");
        if (u) u.onclick = function (e) { e.preventDefault(); run.onRefreshView(); };
        var g = el.querySelector("[data-kefiya=log]");
        if (g) g.onclick = function (e) { e.preventDefault(); showLog(); };
        var a = el.querySelector("[data-kefiya=again]");
        if (a) {
            // Read before the new run replaces `run` -- afterwards the list
            // this link was drawn for no longer exists.
            var names = again.slice();
            var opts = (run && run.options) || {};
            a.onclick = function (e) {
                e.preventDefault();
                kefiya.bank_refresh(Object.assign({}, opts, { only: names }));
            };
        }

        // A log that is already open must not freeze at the state it had when
        // it was opened -- that was the other half of "you only see it
        // afterwards".
        if (run.logDialog && run.logDialog.$wrapper
                && run.logDialog.$wrapper.is(":visible")) {
            var field = run.logDialog.fields_dict
                && run.logDialog.fields_dict.body;
            if (field) field.$wrapper.html(logBody());
        }
    }

    // The accesses of the current run that did not come through: a real
    // failure, or a release the bank is still waiting for. Both are worth a
    // second attempt -- the release because the user has meanwhile confirmed
    // it in the app, the failure because most of them are transient.
    function unfinished() {
        return ((run && run.log) || []).filter(function (e) {
            return e.state === "err" || e.state === "tan";
        }).map(function (e) { return e.ln; });
    }

    // The shortest true sentence about one failed access: the reason the
    // server gave, or the first line that came back marked as an error.
    function shortProblem(entry) {
        if (entry.detail) return entry.detail;
        var bad = (entry.lines || []).filter(function (l) {
            return l.kind === "err";
        })[0];
        if (bad) return bad.label + ": " + bad.text;
        return entry.state === "tan"
            ? __("awaiting release") : __("failed");
    }

    // Failures while the run is still going, right under the bar. Bounded, so
    // a long run cannot push the rest of the page away.
    function liveProblems() {
        var bad = ((run && run.log) || []).filter(function (e) {
            return e.state === "err" || e.state === "tan";
        });
        if (!bad.length) return "";

        var shown = bad.slice(-5);
        var hidden = bad.length - shown.length;
        var rows = shown.map(function (e) {
            var col = e.state === "err" ? C_ERR : C_WAIT;
            var icon = e.state === "err" ? "✗" : "🔑";
            return "<div style='margin-top:3px;line-height:1.35'>"
                + "<span style='color:" + col + "'>" + icon + "</span> "
                + "<span style='font-weight:600'>" + esc(e.ln) + "</span>"
                + "<span style='color:" + C_MUTED + "'> — </span>"
                + "<span style='color:" + col + "'>"
                + esc(String(shortProblem(e)).slice(0, 160)) + "</span></div>";
        }).join("");

        var more = hidden > 0
            ? "<div style='margin-top:3px;color:" + C_MUTED + "'>"
                + esc(__("and {0} more — see the log", [hidden])) + "</div>"
            : "";

        return "<div style='margin-top:8px;font-size:11px'>" + rows + more
            + "</div>";
    }

    // What the server reported per account, turned into readable lines.
    // errors and unsupported are kept strictly apart: a real failure must not
    // look like an absent bank feature.
    function buildLines(x) {
        var lines = [];
        var errs = x.errors || [];
        var uns = x.unsupported || [];
        var why = x.error_details || {};
        var whyNot = x.unsupported_details || {};

        function add(label, text, kind) {
            lines.push({ label: label, text: text, kind: kind || "ok" });
        }

        // name = the identifier _optional_fetch uses on the server.
        function report(label, name, describe) {
            if (errs.indexOf(name) >= 0) {
                add(label, __("Error") + ": "
                    + (why[name] || __("reason in the Error Log")), "err");
                return;
            }
            if (uns.indexOf(name) >= 0) {
                // Some banks refuse the query for this account only, rather
                // than not knowing it. Where the server could tell the two
                // apart, the more precise reason stands here.
                add(label, whyNot[name] || __("not offered by the bank"),
                    "none");
                return;
            }
            var d = describe();
            add(label, d === null ? __("nothing delivered") : d,
                d === null ? "none" : "ok");
        }

        var t = x.transactions || {};
        if (x.skipped || t.status === "skipped") {
            add(__("Fetch"), __("This access is excluded from the fetch"), "none");
            return lines;
        }
        if (t.status === "tan_required") {
            add(__("Transactions"),
                x.message || __("Release required, then fetch again"),
                "err");
            return lines;
        }
        add(__("Transactions"), __("{0} new", [t.new_count || 0]));

        if (x.account_kind) {
            // The kind is a stable English key in the database -- a Select
            // option other code matches on. Only what is shown gets
            // translated; the stored value must not.
            add(__("Account Kind"), __(x.account_kind), "none");
        }
        // Only present when the books and the bank disagree about what this
        // account is. Marked as an error rather than a note: an account that
        // is not money counted as money overstates what can be paid out.
        if (x.ledger_complaint) {
            add(__("Ledger"), x.ledger_complaint, "err");
        }

        report(__("Balance"), "balance", function () {
            var b = x.balance;
            if (!b) return null;
            if (!b.stored) {
                return __("not stored") + " ("
                    + (b.reason || __("unknown")) + ")";
            }
            var cur = b.currency || undefined;
            var s = format_currency(b.balance, cur);
            if (b.line_of_credit) {
                s += " · " + __("Credit line") + " "
                    + format_currency(b.line_of_credit, cur);
            }
            // The same balance, counted back over the bookings just fetched.
            if (b.running && b.running.updated) {
                s += " · " + __("{0} bookings given a balance",
                                [b.running.updated]);
            } else if (b.running && b.running.reason) {
                s += " · " + b.running.reason;
            }
            return s;
        });

        report(__("Pending"), "pending_transactions", function () {
            var p = x.pending;
            if (!p) return null;
            return __("{0} new, {1} unchanged, {2} settled",
                      [p.created || 0, p.updated || 0, p.cancelled || 0]);
        });

        report(__("Securities"), "holdings", function () {
            var h = x.holdings;
            if (!h) return null;
            return __("{0} new, {1} updated",
                      [h.created || 0, h.updated || 0]);
        });

        // HKDBS: money we collect once on a date. It was labelled "standing
        // orders" here, which is a different business transaction entirely.
        report(__("Scheduled debits"), "scheduled_debits", function () {
            var p = x.planned;
            if (!p) return null;
            return __("{0} new, {1} unchanged, {2} cancelled",
                      [p.created || 0, p.updated || 0, p.cancelled || 0]);
        });

        report(__("Standing orders"), "standing_orders", function () {
            var o = x.standing_orders;
            if (!o) return null;
            var txt = __("{0} held by the bank", [o.count || 0]);
            if (o.count && !o.schedule_confirmed) {
                txt += " · " + __("cycle not yet verified");
            }
            return txt;
        });

        report(__("Statements"), "statements", function () {
            var s = x.statements;
            if (!s) return null;
            if (s.reason) return s.reason;
            var txt = __("{0} downloaded of {1} available",
                         [s.downloaded || 0, s.available || 0]);
            if (s.already_present) {
                txt += ", " + __("{0} already present", [s.already_present]);
            }
            if (s.failed_at) {
                txt += " · " + __("stopped at statement {0}", [s.failed_at]);
            }
            return txt;
        });

        report(__("Credit card"), "credit_card", function () {
            var c = x.credit_card;
            if (!c) return null;
            if (c.reason) return c.reason;
            return __("{0} new", [c.created || 0])
                + (c.skipped
                    ? (", " + __("{0} already known", [c.skipped])) : "");
        });

        report(__("Transfer limit"), "transfer_limit", function () {
            var l = x.transfer_limit;
            if (!l) return null;
            if (l.reason) return l.reason;
            if (!l.amount) return null;
            return format_currency(l.amount)
                + (l.limit_type ? (" · " + l.limit_type) : "");
        });

        return lines;
    }

    function logBody() {
        var entries = (run && run.log) || [];
        var body;
        if (!entries.length) {
            body = "<div style='color:" + C_MUTED + "'>"
                + esc(__("No entries.")) + "</div>";
        } else {
            body = entries.map(function (e) {
                var icon = e.state === "err" ? "✗"
                    : (e.state === "tan" ? "🔑"
                        : (e.state === "skip" ? "·" : "✓"));
                var col = e.state === "err" ? C_ERR
                    : (e.state === "tan" ? C_WAIT
                        : (e.state === "skip" ? C_MUTED : C_OK));
                var rows = (e.lines || []).map(function (l) {
                    var lc = l.kind === "err" ? C_ERR
                        : (l.kind === "none" ? C_MUTED : "inherit");
                    var lw = l.kind === "err" ? "600" : "400";
                    return "<tr><td style='padding:1px 12px 1px 0;color:"
                        + C_MUTED + ";white-space:nowrap;vertical-align:top'>"
                        + esc(l.label) + "</td><td style='padding:1px 0;color:"
                        + lc + ";font-weight:" + lw + "'>"
                        + esc(l.text) + "</td></tr>";
                }).join("");
                var detail = e.detail
                    ? "<div style='white-space:pre-wrap;word-break:break-word;"
                        + "color:" + C_ERR + ";font-size:11px;margin-top:4px'>"
                        + esc(e.detail) + "</div>"
                    : "";
                return "<div style='margin-bottom:12px;padding-bottom:8px;"
                    + "border-bottom:1px solid var(--border-color)'>"
                    + "<div style='font-weight:600'><span style='color:" + col
                    + "'>" + icon + "</span> " + esc(e.ln) + "</div>"
                    + "<table style='font-size:12px;margin-top:4px'>" + rows
                    + "</table>" + detail + "</div>";
            }).join("");
        }
        return body;
    }

    function showLog() {
        var dlg = new frappe.ui.Dialog({
            title: __("Log of the account fetch"),
            size: "large",
            fields: [{ fieldtype: "HTML", fieldname: "body",
                       options: logBody() }],
            primary_action_label: __("Close"),
            primary_action: function () { dlg.hide(); }
        });

        // Held on to so render() can refresh it while the run continues. The
        // log used to be a snapshot of the moment it was opened, which during
        // a running fetch is the least interesting moment there is.
        if (run) run.logDialog = dlg;
        dlg.$wrapper.on("hidden.bs.modal", function () {
            if (run && run.logDialog === dlg) run.logDialog = null;
        });

        dlg.show();
    }

    function record(ln, state, lines, detail) {
        if (!run) return;
        run.log.push({ ln: ln, state: state, lines: lines || [],
                       detail: detail || "" });
        run.done++;
        if (state === "err") run.fail++;
        else if (state === "tan") run.tan++;
        else if (state === "skip") run.skip++;
        else run.ok++;
        render();
    }

    // Safety net only. Bootstrap loses track of its backdrop stack when modals
    // overlap, and a surviving backdrop leaves the page dimmed and unclickable.
    // Runs once at the end and never while a dialog is open.
    function cleanupBackdrops() {
        try {
            if (document.querySelector(".modal.show")) return;
            var b = document.querySelectorAll(".modal-backdrop");
            for (var i = 0; i < b.length; i++) {
                if (b[i].parentNode) b[i].parentNode.removeChild(b[i]);
            }
            document.body.classList.remove("modal-open");
        } catch (ignoredD) {}
    }

    // "Freigabe erforderlich" named no bank and no account. In a collective
    // run a dozen accesses stop for a release one after the other, and the box
    // on screen looked identical every time -- so the user had to guess which
    // banking app to open. The payload now carries the access; this puts it
    // where the eye lands, in the heading and in the first line of the dialog.
    function tanTitle(data) {
        return data.account_label
            ? __("Verification required") + " – " + data.account_label
            : __("Verification required");
    }

    function tanContextField(data) {
        if (!data.account_detail) return null;
        return {
            fieldtype: "HTML", fieldname: "kefiya_tan_context",
            options: '<div class="text-muted small" '
                + 'style="margin-bottom:8px">'
                + frappe.utils.escape_html(data.account_detail) + "</div>"
        };
    }

    // What the bank asks, where it does not ask in words. comdirect sends a
    // photoTAN -- a coloured mosaic the phone app reads before it shows the
    // digits -- and a Sparkasse sends chipTAN-QR the same way. Without the
    // picture the box asks for a TAN and shows nothing to scan.
    //
    // Sized in millimetres, not pixels: a photoTAN app reads the mosaic off
    // the screen, and on a high-resolution display a picture given in pixels
    // comes out too small to focus on. 40 mm is what the banks' own web
    // interfaces use.
    function tanChallengeField(data) {
        var c = data.challenge;
        if (!c || (!c.image && !c.text)) return null;

        var html = '<div class="kefiya-tan-challenge" '
            + 'style="text-align:center;margin-bottom:10px">';
        if (c.image && c.image.data) {
            html += '<img alt="' + __("Bank challenge") + '" '
                + 'style="width:40mm;height:40mm;image-rendering:pixelated;'
                + 'border:1px solid var(--border-color);border-radius:4px;'
                + 'background:#fff;padding:4px" src="data:'
                + frappe.utils.escape_html(c.image.mime || "image/png")
                + ";base64," + frappe.utils.escape_html(c.image.data) + '">';
            html += '<div class="text-muted small" style="margin-top:6px">'
                + __("Scan this with your banking app, then enter the TAN it"
                    + " shows.") + "</div>";
        }
        if (c.text) {
            html += '<div class="small" style="margin-top:6px;text-align:left">'
                + frappe.utils.escape_html(c.text) + "</div>";
        }
        return { fieldtype: "HTML", fieldname: "kefiya_tan_challenge",
                 options: html + "</div>" };
    }

    function tanPrompt(data, done) {
        var fields = [];
        if (data.possible_tan_modes) {
            fields.push({ fieldtype: "Select", fieldname: "tan_mode",
                label: __("TAN Mode"), options: data.possible_tan_modes,
                reqd: 1 });
            if (data.possible_tan_mediums) {
                fields[0].default = data.possible_tan_modes[0];
                fields[0].read_only = 1;
                fields.push({ fieldtype: "Select", fieldname: "tan_medium",
                    label: __("TAN Medium"),
                    options: data.possible_tan_mediums, reqd: 1 });
            }
        }
        if (data.tan_required || data.mfa_required) {
            if (data.possible_tan_modes && !fields[0].default) {
                fields[0].default = data.possible_tan_modes[0];
                fields[0].read_only = 1;
            }
            if (data.possible_tan_mediums) {
                fields[1].default = data.possible_tan_mediums[0];
                fields[1].read_only = 1;
            }
            fields.push({ fieldtype: "Check", fieldname: "mfa_confirmation",
                label: __("Confirm MFA"), default: 1, hidden: 1 });
            if (data.tan_required) {
                fields.push({ fieldtype: "Data", fieldname: "tan",
                    label: __("TAN"), reqd: 1 });
            } else if (data.mfa_required) {
                fields.push({ fieldtype: "HTML", fieldname: "waiting",
                    label: __("Waiting for Interaction"),
                    options: __("Follow the instructions on your banking app or device.") });
            }
        }
        // Prepended only now: everything above addresses the fields by index
        // (fields[0] is the mode, fields[1] the medium), so an entry inserted
        // ahead of them earlier would silently make the mode read-only field
        // the wrong one.
        var context = tanContextField(data);
        if (context) fields.unshift(context);
        // Above the account line: the picture is the question, and the
        // question belongs at the top.
        var challenge = tanChallengeField(data);
        if (challenge) fields.unshift(challenge);

        var dialog = frappe.prompt(fields, function (values) {
            // Explicit feedback, because the run mutes the standard error box.
            frappe.call({
                method: "kefiya.utils.client.resolve_tan_interaction",
                args: { fints_login: data.docname,
                        values: Object.assign({}, data, values) },
                silent: true,
                callback: function () { if (done) done(); },
                error: function (r) {
                    frappe.show_alert({
                        message: __("TAN release failed.") + " "
                            + errText(r),
                        indicator: "red"
                    }, 10);
                    if (done) done();
                }
            });
        }, tanTitle(data));

        // Into the TAN field, not into the dialog. The mode and the medium
        // above it are read-only -- the only thing to do here is type six
        // digits, and Frappe leaves the focus on the dialog itself, so it took
        // a click first. A TAN expires while you look for the cursor.
        //
        // On the decoupled procedure there IS no TAN field: the release
        // happens in the banking app and the dialog only says so. Focusing
        // whatever happens to be first would put the cursor somewhere the user
        // must not change, so nothing is focused at all.
        focusTanField(dialog);
        return dialog;
    }

    // frappe.prompt resolves its dialog synchronously but shows it through a
    // Bootstrap transition, so the input is not focusable at the moment the
    // call returns. shown.bs.modal is the event that says it is; the timeout
    // is the fallback for a desk that renders the modal without the
    // transition, where the event has already fired.
    function focusTanField(dialog) {
        if (!dialog || !dialog.get_field) return;
        var put = function () {
            try {
                var f = dialog.get_field("tan");
                if (f && f.$input) f.$input.focus().select();
            } catch (ignored) {}
        };
        try { dialog.$wrapper.on("shown.bs.modal", put); } catch (ignoredA) {}
        setTimeout(put, 300);
    }

    // Shared, because a TAN prompt is a TAN prompt: the outgoing-payments page
    // needs the same box when the bank asks for a release on a send. Two copies
    // of it drifted apart once already -- the second one named neither the bank
    // nor the account, which is the whole reason the context lines exist.
    kefiya.tan_prompt = tanPrompt;

    // The Kefiya Login form builds its own TAN box (it has the form's docname
    // where this one has a login from the run). It gets the focus rule from
    // here rather than a second copy of it -- these two boxes have drifted
    // apart once already.
    kefiya.focus_tan_field = focusTanField;

    // Set when the user has answered a TAN box during a run: the release is
    // given, so the accounts the bank held back can be fetched -- and nothing
    // else was going to do it.
    //
    // Three steps used to stand between the release and the bookings: confirm
    // in the banking app, click OK in the box (which only opens the session --
    // resolve_tan_interaction builds a controller and stops), then find the
    // "fetch the unfinished accesses again" link. Two of those three are
    // invisible, and 24 accounts sat unfetched behind them.
    var resumeWanted = false;

    function bindRealtime() {
        if (kefiya._bank_refresh_realtime) return;
        kefiya._bank_refresh_realtime = true;
        // No progressbar handler: it wrote into the per-access row that no
        // longer exists. The TAN prompt stays -- it is the only point at
        // which the run needs the user.
        frappe.realtime.on("fints_tan_interaction_required", function (data) {
            if (!run || !run.busy) return;
            tanPrompt(data, function () {
                resumeWanted = true;
                // Not now: the worker still holds the access, and a second
                // dialog on it is the very damage the run is built to avoid.
                // The end of the run picks this up.
                maybeResume();
            });
        });
    }

    // Fetch what the bank held back, once the run that hit the release has
    // finished. Guarded three ways: only after a release was actually given,
    // only when no run is going, and only once -- a second release inside the
    // resumed run sets the flag again on its own.
    function maybeResume() {
        if (!resumeWanted) return;
        if (run && run.busy) return;
        resumeWanted = false;
        var again = unfinished();
        if (!again.length) return;
        var opts = (run && run.options) || {};
        frappe.show_alert({
            message: __("Release accepted — fetching the {0} accounts that"
                        + " were waiting for it.", [again.length]),
            indicator: "blue"
        }, 7);
        kefiya.bank_refresh(Object.assign({}, opts, { only: again }));
    }

    // One account's outcome, whoever fetched it. The worker and the
    // account-by-account fallback below hand in the same summary, so they must
    // read it the same way -- two copies of this drifted once and the log said
    // "2 neu" for every account in the run.
    function noteResult(ln, x, failure) {
        if (!run) return "err";
        if (failure) {
            record(ln, "err",
                [{ label: __("Fetch"), text: __("failed"), kind: "err" }],
                String(failure).slice(0, 600));
            return "err";
        }
        x = x || {};
        var t = x.transactions || {};
        var state = "ok";
        if (x.skipped || t.status === "skipped") state = "skip";
        else if (x.tan_required || t.status === "tan_required") state = "tan";
        run.tot += (t.new_count || 0);
        record(ln, state, buildLines(x));
        return state;
    }

    function progressLabel(btn, total) {
        if (btn) {
            btn.textContent = __("Fetching …") + " ("
                + run.done + "/" + total + ")";
        }
    }

    // Runs a worker is holding, by the id start_fetch_group gave them. The
    // realtime handlers are bound once for the page, so this map is how an
    // event finds the group it belongs to.
    var pending = {};

    function bindGroupRealtime() {
        if (kefiya._bank_refresh_group_realtime) return;
        kefiya._bank_refresh_group_realtime = true;
        frappe.realtime.on("kefiya_fetch_progress", function (d) {
            var g = d && pending[d.run];
            if (!g) return;
            g.seen();
            noteResult(d.login, d.summary, d.error);
            progressLabel(g.btn, g.total);
        });
        frappe.realtime.on("kefiya_fetch_group_done", function (d) {
            var g = d && pending[d.run];
            if (!g) return;
            g.done();
        });
    }

    // How long a group may say nothing before the run stops waiting for it.
    // A worker that dies -- killed, out of memory, a bank that never answers
    // -- publishes no closing event, and without this the panel would sit at
    // "fetching" until the page is reloaded.
    var GROUP_SILENCE_MS = 10 * 60 * 1000;

    // One bank access, one dialog, all of its accounts -- the whole point of
    // fetch_group, which the server has had all along and nobody called. The
    // browser used to fetch account by account, so thirty accounts on one
    // access meant thirty handshakes and thirty strong authentications
    // against the same bank.
    function fetchWholeAccess(logins, btn, total) {
        return new Promise(function (res) {
            frappe.call({
                method: "kefiya.utils.client.start_fetch_group",
                args: { logins: logins, user_scope: logins[0] },
                silent: true,
                callback: function (r) {
                    var id = r && r.message && r.message.run;
                    if (!id) { res(fetchOneByOne(logins, btn, total)); return; }
                    var timer = null;
                    var settled = false;
                    var finish = function () {
                        if (settled) return;
                        settled = true;
                        if (timer) clearTimeout(timer);
                        delete pending[id];
                        res(null);
                    };
                    var arm = function () {
                        if (timer) clearTimeout(timer);
                        timer = setTimeout(function () {
                            // Whatever never reported is neither fetched nor
                            // failed as far as we know. Say that, rather than
                            // leave the bar short of its total for good.
                            logins.forEach(function (ln) {
                                if (!recorded(ln)) {
                                    noteResult(ln, null, __(
                                        "The worker stopped reporting. Fetch"
                                        + " this access again."));
                                }
                            });
                            finish();
                        }, GROUP_SILENCE_MS);
                    };
                    pending[id] = { btn: btn, total: total,
                                    seen: arm, done: finish };
                    arm();
                },
                // An older server without the endpoint, or a caller without
                // the rights the worker would need. Neither is a reason to
                // fetch nothing.
                error: function () { res(fetchOneByOne(logins, btn, total)); }
            });
        });
    }

    function recorded(ln) {
        return ((run && run.log) || []).some(function (e) {
            return e.ln === ln;
        });
    }

    // The fallback: one request per account, as it was before the worker.
    // Keeps the client-side stop at a parked release, because here the client
    // is the only one who can see it.
    function fetchOneByOne(logins, btn, total) {
        var chain = Promise.resolve();
        var held = null;
        logins.forEach(function (ln) {
            chain = chain.then(function () {
                if (held) {
                    record(ln, "tan", [{
                        label: __("Fetch"),
                        text: __("not attempted — {0} is waiting"
                                 + " for a release", [held]),
                        kind: "err"
                    }]);
                    return;
                }
                progressLabel(btn, total);
                return fetchOne(ln).then(function (state) {
                    if (state === "tan") held = ln;
                });
            });
        });
        return chain;
    }

    function fetchOne(ln) {
        return new Promise(function (res) {
            frappe.call({
                method: "kefiya.utils.client.fetch_all",
                args: { kefiya_login: ln, user_scope: ln },
                silent: true,
                callback: function (r) {
                    res(noteResult(ln, (r && r.message) || {}));
                },
                error: function (r) {
                    res(noteResult(ln, null, errText(r) || __("Error")));
                }
            });
        });
    }

    kefiya.bank_refresh = function (options) {
        options = options || {};
        var btn = options.btn || null;
        var label = options.buttonLabel || (btn && btn.textContent)
            || idleLabel();
        var release = function () {
            if (btn) { btn.disabled = false; btn.textContent = label; }
        };

        if (run && run.busy) {
            frappe.show_alert({
                message: __("An account fetch is already running."),
                indicator: "orange"
            }, 5);
            return Promise.resolve(null);
        }

        // Without read access frappe.db.get_list returns an empty list, which
        // would otherwise read as "no bank access configured".
        if (frappe.model && frappe.model.can_read
                && !frappe.model.can_read("Kefiya Login")) {
            frappe.msgprint({
                title: __("No permission"),
                message: __("You do not have permission to fetch the bank accesses."),
                indicator: "red"
            });
            return Promise.resolve(null);
        }

        bindRealtime();
        bindGroupRealtime();
        if (btn) { btn.disabled = true; btn.textContent = __("Checking …"); }

        // A restricted run still asks the server for the list: `only` names
        // logins, and a name that has meanwhile been deleted or had its
        // account removed must drop out rather than fail the run.
        var wanted = null;
        if (options.only && options.only.length) {
            wanted = {};
            options.only.forEach(function (ln) { wanted[ln] = true; });
        }

        return frappe.db.get_list("Kefiya Login", {
            fields: ["name", "account_iban"], limit: 200
        }).then(function (rows) {
            var logins = (rows || [])
                .filter(function (r) { return r.account_iban; })
                .filter(function (r) { return !wanted || wanted[r.name]; })
                .map(function (r) { return r.name; });
            if (!logins.length) {
                frappe.msgprint(wanted
                    ? __("None of these accesses is still configured.")
                    : __("No bank access with an account configured."));
                release();
                return null;
            }
            // Panels used to stack: the second run drew its own above the
            // first, and the finished one stayed to be read as current.
            if (run && run.panel && run.panel.isConnected) {
                run.panel.parentNode.removeChild(run.panel);
            }
            run = {
                busy: true, order: logins.slice(), log: [],
                tot: 0, ok: 0, tan: 0, fail: 0, skip: 0, done: 0,
                mount: options.mount || null, panel: null, logDialog: null,
                onRefreshView: options.onRefreshView || null,
                options: options
            };
            render();

            muteErrors();
            // The server says which accesses share a bank; each group is one
            // chain, the chains run beside each other. Where the call is not
            // available, everything stays in a single chain.
            return new Promise(function (res) {
                frappe.call({
                    method: "kefiya.utils.client.get_fetch_groups",
                    silent: true,
                    callback: function (r) {
                        var g = ((r && r.message) || []).map(function (x) {
                            return x.logins || [];
                        });
                        res(g.length ? g : [logins]);
                    },
                    error: function () { res([logins]); }
                });
            }).then(function (groups) {
                // The server leaves out accesses marked "skip". Without this
                // reconciliation the progress counted against a total that is
                // never reached, and the bar stopped short.
                var known = {};
                logins.forEach(function (ln) { known[ln] = true; });
                // get_fetch_groups answers for every access. In a restricted
                // run the groups are the right chains but the wrong contents,
                // so `known` is what decides -- it already holds only the
                // logins this run is allowed to touch.
                var planned = [];
                groups.forEach(function (grp) {
                    grp.forEach(function (ln) {
                        if (known[ln]) planned.push(ln);
                    });
                });
                if (planned.length) run.order = planned;
                var total = run.order.length;

                var chains = groups.map(function (grp) {
                    var mine = grp.filter(function (ln) { return known[ln]; });
                    if (!mine.length) return Promise.resolve();
                    // The whole access in one go. The stop at a parked
                    // release lives in fetch_group now: the server is the
                    // only one that sees it the moment it happens, and it is
                    // the one holding the dialog the release belongs to.
                    return fetchWholeAccess(mine, btn, total);
                });
                return Promise.all(chains).then(function () {
                    run.busy = false;
                    render();
                    unmuteErrors();
                    cleanupBackdrops();
                    release();
                    var summary = { total: run.tot, ok: run.ok, tan: run.tan,
                                    fail: run.fail, accounts: total };
                    frappe.show_alert({
                        message: __("Account fetch done") + " · "
                            + __("{0} new transactions", [run.tot]) + " · "
                            + run.ok + "/" + total + " "
                            + __("accounts")
                            + (run.tan
                                ? (" · " + __("{0}× awaiting release", [run.tan]))
                                : "")
                            + (run.fail
                                ? (" · " + __("{0} failed", [run.fail])) : ""),
                        indicator: (run.tan || run.fail) ? "orange" : "green"
                    }, 9);
                    if (options.onDone) {
                        try { options.onDone(summary); } catch (ignoredC) {}
                    }
                    // A release given while this run was going: the accounts
                    // the bank held back are fetched now, without the user
                    // having to find a link for it.
                    maybeResume();
                    return summary;
                });
            });
        }).catch(function (r) {
            if (run) { run.busy = false; render(); }
            unmuteErrors();
            cleanupBackdrops();
            release();
            maybeResume();
            frappe.msgprint(__("The account fetch was aborted.") + " "
                + errText(r));
            return null;
        });
    };
})();
