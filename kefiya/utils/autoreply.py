# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Automatische Eingangsbestätigung mit Vorgangsnummer (FEAT-11901).

Every incoming tenant/prospect email gets exactly ONE acknowledgment per
sender and case ("Anliegen"): "Wir haben Ihre Nachricht erhalten, Ihr Vorgang
lautet #…, wir melden uns bis …".

Flow (hooked on Communication.after_insert):

    incoming mail -> pick_rule()          per mailbox / Vorgangstyp
                  -> guards               kill switch, noreply senders, loops
                  -> duplicate check      Kefiya AutoReply Log (Zustandsmerker)
                  -> daily limit          guardrail per rule
                  -> compose              Email Template (Mustertext) or default
                  -> act per autonomy level:
                       0  Shadow Mode: log only what WOULD have been sent
                       1  create a draft reply Communication, human sends
                       2+ queue the email (Email Queue, threaded via In-Reply-To)

Every decision is recorded in "Kefiya AutoReply Log" and mirrored best-effort
into the site-wide "Automation Run Log" if that DocType exists. The handler
must NEVER raise: an exception here would break inbox pulling for the whole
mailbox, so everything is wrapped and logged instead.
"""

import re

import frappe
from frappe.utils import add_days, cint, formatdate, nowdate

RULE_DOCTYPE = "Kefiya AutoReply Rule"
LOG_DOCTYPE = "Kefiya AutoReply Log"

#: central process registration (axessio dev process, Abschnitt 3). Looked up
#: best-effort — the DocTypes live in the production site, not in this app.
CENTRAL_RULE_KEY = "kefiya_autoreply_incoming"

#: actions that count as "this sender/case was already acknowledged"
DEDUP_ACTIONS = ("Would Send", "Sent", "Draft Created")

#: sender patterns that must never receive an acknowledgment (bounce loops,
#: notification robots, our own kind).
UNSAFE_SENDER_RE = re.compile(
    r"(no[-_.]?reply|do[-_.]?not[-_.]?reply|mailer[-_.]?daemon|postmaster"
    r"|bounce|auto[-_.]?confirm|notification[s]?@)",
    re.IGNORECASE,
)

DEFAULT_SUBJECT = "Ihre Nachricht ist eingegangen – Vorgang {vorgangsnummer}"

DEFAULT_MESSAGE = (
    "<p>Guten Tag{sender_name_suffix},</p>"
    "<p>wir haben Ihre Nachricht erhalten. Ihr Vorgang lautet "
    "<b>#{vorgangsnummer}</b>.</p>"
    "<p>Wir melden uns bis zum <b>{frist}</b> bei Ihnen. Bitte geben Sie bei "
    "Rückfragen die Vorgangsnummer an.</p>"
    "<p>Diese Bestätigung wurde automatisch erstellt.</p>"
)


# ---------------------------------------------------------------------------
# pure helpers (unit-tested without a site)
# ---------------------------------------------------------------------------

def normalize_sender(sender):
    """Lower-cased bare email address from '"Name" <addr>' style strings."""
    if not sender:
        return ""
    sender = sender.strip()
    match = re.search(r"<([^<>]+)>", sender)
    if match:
        sender = match.group(1)
    return sender.strip().strip('"').lower()


def is_unsafe_sender(sender_email):
    """True for addresses that must never get an auto-acknowledgment."""
    if not sender_email or "@" not in sender_email:
        return True
    return bool(UNSAFE_SENDER_RE.search(sender_email))


def case_key(sender_email, reference_doctype, reference_name):
    """Duplicate key: one acknowledgment per sender and case. Mails without a
    linked Vorgang collapse onto the sender alone (cooldown handles repeats)."""
    if reference_doctype and reference_name:
        return "{0}::{1}:{2}".format(sender_email, reference_doctype, reference_name)
    return "{0}::-".format(sender_email)


def pick_rule(rules, reference_doctype):
    """Most specific enabled rule wins: exact Vorgangstyp match beats the
    catch-all rule (empty reference_doctype)."""
    fallback = None
    for rule in rules:
        rule_ref = rule.get("reference_doctype") or ""
        if reference_doctype and rule_ref == reference_doctype:
            return rule
        if not rule_ref and fallback is None:
            fallback = rule
    return fallback


def render_default(context):
    """Built-in acknowledgment text used when no Mustertext is configured."""
    sender_name = (context.get("sender_name") or "").strip()
    subject = DEFAULT_SUBJECT.format(vorgangsnummer=context["vorgangsnummer"])
    message = DEFAULT_MESSAGE.format(
        sender_name_suffix=" " + sender_name if sender_name else "",
        vorgangsnummer=context["vorgangsnummer"],
        frist=context["frist"],
    )
    return subject, message


# ---------------------------------------------------------------------------
# site-dependent pieces
# ---------------------------------------------------------------------------

def render_template(rule, context):
    """Render the configured Email Template (Mustertext), falling back to the
    built-in default text."""
    if not rule.get("email_template"):
        return render_default(context)
    template = frappe.get_doc("Email Template", rule["email_template"])
    subject = frappe.render_template(template.subject or DEFAULT_SUBJECT, context)
    body = (
        template.response_html
        if cint(template.get("use_html"))
        else template.response
    )
    if not body:
        return render_default(context)
    return subject, frappe.render_template(body, context)


def central_gate():
    """Best-effort check of the site-wide Automation Rule registration
    (axessio dev process). Returns (blocked, level_override, detail).

    The Automation Rule DocType is owned by the production site, not by this
    app, so field access is defensive: missing DocType or missing record means
    "no central override"."""
    try:
        if not frappe.db.exists("DocType", "Automation Rule"):
            return False, None, None
        meta = frappe.get_meta("Automation Rule")
        key_field = next(
            (f for f in ("rule_key", "rule_name", "title") if meta.has_field(f)),
            None,
        )
        if not key_field:
            return False, None, None
        name = frappe.db.get_value("Automation Rule", {key_field: CENTRAL_RULE_KEY})
        if not name:
            return False, None, None
        fields = [
            f for f in ("kill_switch", "autonomy_level", "enabled", "disabled")
            if meta.has_field(f)
        ]
        if not fields:
            return False, None, None
        rule = frappe.db.get_value(
            "Automation Rule", name, fields, as_dict=True
        ) or {}
        if cint(rule.get("kill_switch")):
            return True, None, "Automation Rule {0}: kill_switch".format(name)
        if meta.has_field("enabled") and not cint(rule.get("enabled", 1)):
            return True, None, "Automation Rule {0}: disabled".format(name)
        if meta.has_field("disabled") and cint(rule.get("disabled")):
            return True, None, "Automation Rule {0}: disabled".format(name)
        level = rule.get("autonomy_level")
        if level is not None and str(level).strip() != "":
            return False, cint(str(level)[:1]), None
        return False, None, None
    except Exception:
        frappe.log_error(title="Kefiya AutoReply: central gate failed")
        return False, None, None


def write_central_run_log(payload):
    """Mirror the decision into the site-wide Automation Run Log if present,
    mapping only onto fields that actually exist there."""
    try:
        if not frappe.db.exists("DocType", "Automation Run Log"):
            return
        meta = frappe.get_meta("Automation Run Log")
        doc = frappe.new_doc("Automation Run Log")
        for field, value in payload.items():
            if meta.has_field(field):
                doc.set(field, value)
        doc.flags.ignore_permissions = True
        doc.insert(ignore_permissions=True)
    except Exception:
        frappe.log_error(title="Kefiya AutoReply: Automation Run Log write failed")


def write_log(rule, comm, sender_email, key, action, detail="", reply_name=None):
    log = frappe.get_doc(
        {
            "doctype": LOG_DOCTYPE,
            "rule": rule.get("name"),
            "email_account": rule.get("email_account"),
            "sender": sender_email,
            "case_key": key,
            "reference_doctype": comm.reference_doctype,
            "reference_name": comm.reference_name,
            "communication": comm.name,
            "reply_communication": reply_name,
            "action": action,
            "autonomy_level": rule.get("autonomy_level"),
            "detail": detail,
        }
    )
    log.flags.ignore_permissions = True
    log.insert(ignore_permissions=True)

    write_central_run_log(
        {
            "rule_key": CENTRAL_RULE_KEY,
            "automation_rule": CENTRAL_RULE_KEY,
            "trigger": "Communication/{0}".format(comm.name),
            "decision": action,
            "action": action,
            "result": detail or action,
            "reference_doctype": LOG_DOCTYPE,
            "reference_name": log.name,
            "status": "Error" if action == "Error" else "Success",
        }
    )
    return log


def is_duplicate(rule, sender_email, key, has_reference):
    """Zustandsmerker: was this sender/case acknowledged before?

    With a linked Vorgang: exactly one acknowledgment, ever. Without one the
    key collapses onto the sender, limited by the rule's cooldown window
    (cooldown_days = 0 keeps "once per sender, ever", FlowFact behaviour)."""
    filters = {
        "email_account": rule.get("email_account"),
        "case_key": key,
        "action": ("in", DEDUP_ACTIONS),
    }
    if not has_reference:
        cooldown = cint(rule.get("cooldown_days"))
        if cooldown > 0:
            filters["creation"] = (">=", add_days(nowdate(), -cooldown))
    return bool(frappe.db.exists(LOG_DOCTYPE, filters))


def daily_count(rule):
    return frappe.db.count(
        LOG_DOCTYPE,
        {
            "rule": rule.get("name"),
            "action": ("in", DEDUP_ACTIONS),
            "creation": (">=", nowdate()),
        },
    )


def get_rules(email_account):
    return frappe.get_all(
        RULE_DOCTYPE,
        filters={"enabled": 1, "email_account": email_account},
        fields=[
            "name",
            "email_account",
            "reference_doctype",
            "autonomy_level",
            "email_template",
            "response_time_days",
            "daily_limit",
            "cooldown_days",
            "kill_switch",
        ],
    )


def build_context(comm, rule):
    vorgangsnummer = comm.reference_name or comm.name
    frist = formatdate(
        add_days(nowdate(), cint(rule.get("response_time_days")) or 2),
        "dd.MM.yyyy",
    )
    return {
        "vorgangsnummer": vorgangsnummer,
        "frist": frist,
        "sender_name": comm.get("sender_full_name") or "",
        "original_subject": comm.subject or "",
        "doc": comm,
    }


def create_reply_communication(comm, rule, subject, message, sent=True):
    reply = frappe.get_doc(
        {
            "doctype": "Communication",
            "communication_type": "Communication",
            "communication_medium": "Email",
            "sent_or_received": "Sent",
            "subject": subject,
            "content": message,
            "sender": frappe.db.get_value(
                "Email Account", rule.get("email_account"), "email_id"
            ),
            "recipients": comm.sender,
            "reference_doctype": comm.reference_doctype,
            "reference_name": comm.reference_name,
            "email_account": rule.get("email_account"),
            "in_reply_to": comm.name,
            "status": "Linked" if comm.reference_name else "Open",
            "email_status": "Sent" if sent else "Open",
        }
    )
    reply.flags.ignore_permissions = True
    reply.insert(ignore_permissions=True)
    return reply


def queue_email(comm, rule, reply, subject, message):
    """Queue the acknowledgment via Email Queue, threaded onto the incoming
    mail through In-Reply-To (FEAT-10223)."""
    frappe.sendmail(
        recipients=[normalize_sender(comm.sender)],
        subject=subject,
        message=message,
        reference_doctype=comm.reference_doctype or "Communication",
        reference_name=comm.reference_name or comm.name,
        communication=reply.name,
        in_reply_to=comm.get("message_id"),
        delayed=True,
    )


# ---------------------------------------------------------------------------
# entry point (hooks.py: Communication.after_insert)
# ---------------------------------------------------------------------------

def on_communication_after_insert(doc, method=None):
    """Never raises — a failure here must not break inbox pulling."""
    try:
        process_incoming(doc)
    except Exception:
        frappe.log_error(
            title="Kefiya AutoReply: unhandled error",
            message=frappe.get_traceback(),
        )


def process_incoming(comm):
    if (
        comm.communication_type != "Communication"
        or comm.sent_or_received != "Received"
        or comm.communication_medium not in (None, "", "Email")
        or not comm.get("email_account")
        or not comm.sender
    ):
        return

    sender_email = normalize_sender(comm.sender)
    if is_unsafe_sender(sender_email):
        return

    # never acknowledge ourselves (loop guard)
    own_address = frappe.db.get_value(
        "Email Account", comm.email_account, "email_id"
    )
    if own_address and sender_email == own_address.strip().lower():
        return

    rules = get_rules(comm.email_account)
    rule = pick_rule(rules, comm.reference_doctype)
    if not rule:
        return

    has_reference = bool(comm.reference_doctype and comm.reference_name)
    key = case_key(sender_email, comm.reference_doctype, comm.reference_name)

    if cint(rule.get("kill_switch")):
        return  # Not-Aus: keine Aktion, kein Log-Spam

    blocked, level_override, gate_detail = central_gate()
    if blocked:
        write_log(rule, comm, sender_email, key, "Blocked", gate_detail or "")
        return

    level = cint((rule.get("autonomy_level") or "0")[:1])
    if level_override is not None:
        level = min(level, level_override)

    if is_duplicate(rule, sender_email, key, has_reference):
        write_log(
            rule, comm, sender_email, key,
            "Skipped Duplicate",
            "Absender/Vorgang wurde bereits bestätigt.",
        )
        return

    limit = cint(rule.get("daily_limit")) or 200
    if daily_count(rule) >= limit:
        write_log(
            rule, comm, sender_email, key,
            "Blocked",
            "Tageslimit ({0}) erreicht — Anomalie-Leitplanke.".format(limit),
        )
        return

    context = build_context(comm, rule)
    try:
        subject, message = render_template(rule, context)
    except Exception:
        write_log(
            rule, comm, sender_email, key, "Error",
            "Mustertext konnte nicht gerendert werden:\n{0}".format(
                frappe.get_traceback()
            ),
        )
        return

    if level <= 0:
        write_log(
            rule, comm, sender_email, key,
            "Would Send",
            "Shadow Mode. Betreff: {0}\n\n{1}".format(subject, message[:1000]),
        )
        return

    if level == 1:
        reply = create_reply_communication(comm, rule, subject, message, sent=False)
        write_log(
            rule, comm, sender_email, key,
            "Draft Created",
            "Antwortentwurf angelegt, Versand durch Menschen.",
            reply_name=reply.name,
        )
        return

    reply = create_reply_communication(comm, rule, subject, message, sent=True)
    queue_email(comm, rule, reply, subject, message)
    write_log(
        rule, comm, sender_email, key,
        "Sent",
        "In E-Mail-Queue eingestellt. Betreff: {0}".format(subject),
        reply_name=reply.name,
    )
