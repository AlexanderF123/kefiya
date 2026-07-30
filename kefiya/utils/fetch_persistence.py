# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Persist what a fetch brings back, instead of only counting it.

fetch_all used to return the balance as a number nobody stored, and reported
documents and credit-card transactions as a bare count -- the data was fetched
from the bank and then dropped on the floor. These helpers give each of them a
home:

  balance          -> Bank Account.custom_account_balance / custom_credit_line
  pending entries  -> Bank Transaction, draft, status "Pending", replaced whole
  credit card      -> Bank Transaction, same shape as a normal booking
  documents        -> File attached to the Kefiya Login

Every helper is idempotent and guarded: a fetch that already booked its
transactions must never fail because a statement PDF could not be stored.
"""

import hashlib
import json

import frappe
from frappe.utils import flt, getdate, now_datetime


def _as_dict(entry):
    """FinTS results are objects, dicts or namedtuples depending on the bank."""
    if isinstance(entry, dict):
        return entry
    try:
        return dict(entry)
    except Exception:
        return {k: getattr(entry, k) for k in dir(entry)
                if not k.startswith("_") and not callable(getattr(entry, k))}


def _first(mapping, keys, default=None):
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return default


# --------------------------------------------------------------------------
# Balance
# --------------------------------------------------------------------------

def store_balance(kefiya_login, rows):
    """Write the current balance and credit line onto the Bank Account.

    get_fints_balance() returns one row per HISAL segment. Only the row for the
    login's own account is of interest -- a bank may answer for several -- and
    the newest value wins.

    :return: {"stored": bool, "balance": float|None, "line_of_credit": float|None}
    """
    login = frappe.get_doc("Kefiya Login", kefiya_login)
    if not login.bank_account:
        return {"stored": False, "reason": "no bank account linked"}

    rows = [r for r in (rows or []) if isinstance(r, dict)]
    if not rows:
        return {"stored": False, "reason": "bank returned no balance"}

    # Prefer the row that names this login's IBAN; fall back to the first.
    row = next((r for r in rows if r.get("iban") == login.account_iban), rows[0])
    balance = row.get("balance")
    if balance is None:
        return {"stored": False, "reason": "balance missing on the response"}

    account = frappe.get_doc("Bank Account", login.bank_account)
    meta = account.meta

    # The fields are Custom Fields on this instance; skip silently where they
    # are not installed rather than failing a fetch that already succeeded.
    if meta.has_field("custom_account_balance"):
        account.custom_account_balance = flt(balance)
    if meta.has_field("custom_credit_line") and row.get("line_of_credit") is not None:
        account.custom_credit_line = flt(row.get("line_of_credit"))

    account.save(ignore_permissions=True)

    return {
        "stored": True,
        "bank_account": account.name,
        "balance": flt(balance),
        "line_of_credit": row.get("line_of_credit"),
        "available_amount": row.get("available_amount"),
        "currency": row.get("currency"),
    }


# --------------------------------------------------------------------------
# Pending (vorgemerkte) entries
# --------------------------------------------------------------------------

#: Marker in `description` identifying an entry as still only pending, so it can
#: be recognised again without a schema change.
PENDING_MARKER = "[vorgemerkt]"


def _pending_reference(bank_account, date, amount, description):
    raw = "pending|{0}|{1}|{2}|{3}".format(
        bank_account, date, amount, (description or "")[:120])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def replace_pending_transactions(kefiya_login, entries):
    """Replace this account's pending entries with what the bank now shows.

    A pending entry is not a booking: the bank may change its amount, its text
    or its date before it settles, and then it disappears from the pending list
    and reappears as a real booking. Matching the two is guesswork -- the
    booking date usually differs from the pending date, so the import's dedup
    hash would not recognise them as the same thing and the account would show
    the payment twice.

    So they are not merged at all. Every pending entry is stored as a DRAFT Bank
    Transaction with status "Pending", and every fetch deletes the previous set
    and writes the current one. Drafts stay out of reconciliation and out of the
    ledger, so nothing double-counts; once the bank settles an entry it drops
    off the pending list and the next fetch removes the draft, while the real
    booking arrives through the normal import.

    :return: {"removed": int, "created": int}
    """
    login = frappe.get_doc("Kefiya Login", kefiya_login)
    if not login.bank_account:
        return {"removed": 0, "created": 0, "reason": "no bank account linked"}

    # Drop the previous snapshot. Only drafts carrying our marker -- a submitted
    # transaction is a real booking and must never be touched here.
    existing = frappe.get_all(
        "Bank Transaction",
        filters={
            "bank_account": login.bank_account,
            "docstatus": 0,
            "description": ("like", "%{0}%".format(PENDING_MARKER)),
        },
        pluck="name",
    )
    removed = 0
    for name in existing:
        try:
            frappe.delete_doc("Bank Transaction", name,
                              ignore_permissions=True, delete_permanently=True)
            removed += 1
        except Exception:
            frappe.log_error(
                title="Kefiya: could not drop a stale pending entry",
                message=frappe.get_traceback(),
                reference_doctype="Bank Transaction",
                reference_name=name,
            )

    created = 0
    for raw in (entries or []):
        entry = _as_dict(raw)
        amount = _coerce_amount(_first(entry, ("amount", "Amount", "value")))
        if amount is None:
            continue

        date = _first(entry, ("date", "entry_date", "booking_date",
                              "BookingDate", "ValueDate"))
        try:
            date = getdate(date) if date else now_datetime().date()
        except Exception:
            date = now_datetime().date()

        text = _first(entry, ("purpose", "Purpose", "description",
                              "posting_text", "RemittanceInformation"), "")
        counterparty = _first(entry, ("applicant_name", "Name",
                                      "counterparty", "party_name"), "")

        description = "{0} {1} {2}".format(
            PENDING_MARKER, counterparty or "", text or "").strip()

        try:
            frappe.get_doc({
                "doctype": "Bank Transaction",
                "date": date,
                "status": "Pending",
                "bank_account": login.bank_account,
                "company": login.company,
                "deposit": amount if amount > 0 else 0,
                "withdrawal": -amount if amount < 0 else 0,
                "description": description,
                "reference_number": _pending_reference(
                    login.bank_account, date, amount, description),
                "bank_party_name": counterparty or None,
                # Draft on purpose: a pending entry is not a booking. It must
                # stay out of reconciliation and out of the ledger.
                "docstatus": 0,
            }).insert(ignore_permissions=True)
            created += 1
        except Exception:
            frappe.log_error(
                title="Kefiya: could not store a pending entry",
                message=frappe.get_traceback(),
                reference_doctype="Kefiya Login",
                reference_name=kefiya_login,
            )

    return {"removed": removed, "created": created}


def _coerce_amount(value):
    """FinTS amounts arrive as Decimal, float, str or an Amount object."""
    if value is None:
        return None
    for attr in ("amount", "value"):
        if hasattr(value, attr):
            value = getattr(value, attr)
            break
    try:
        return flt(value)
    except Exception:
        try:
            return flt(str(value).replace(",", "."))
        except Exception:
            return None


# --------------------------------------------------------------------------
# Credit card transactions
# --------------------------------------------------------------------------

def store_credit_card_transactions(kefiya_login, entries):
    """Book credit-card transactions like any other bank transaction.

    They used to be fetched and counted. A credit-card charge is a movement on
    the card account exactly like a transfer is on a giro account, so it gets
    the same treatment -- including the dedup by reference hash, which is what
    makes a repeated fetch harmless.

    :return: {"created": int, "skipped": int}
    """
    login = frappe.get_doc("Kefiya Login", kefiya_login)
    if not login.bank_account:
        return {"created": 0, "skipped": 0, "reason": "no bank account linked"}

    created = skipped = 0
    for raw in (entries or []):
        entry = _as_dict(raw)
        amount = _coerce_amount(_first(entry, ("amount", "Amount", "value")))
        if amount is None:
            skipped += 1
            continue

        date = _first(entry, ("date", "booking_date", "entry_date",
                              "BookingDate", "ValueDate"))
        try:
            date = getdate(date) if date else now_datetime().date()
        except Exception:
            date = now_datetime().date()

        text = _first(entry, ("purpose", "Purpose", "description",
                              "posting_text", "reason"), "")
        counterparty = _first(entry, ("applicant_name", "Name", "merchant",
                                      "counterparty"), "")

        raw_key = "cc|{0}|{1}|{2}|{3}|{4}".format(
            login.bank_account, date, amount, counterparty, (text or "")[:120])
        reference = hashlib.md5(raw_key.encode("utf-8")).hexdigest()

        if frappe.db.exists("Bank Transaction", {"reference_number": reference}):
            skipped += 1
            continue

        try:
            frappe.get_doc({
                "doctype": "Bank Transaction",
                "date": date,
                "status": "Unreconciled",
                "bank_account": login.bank_account,
                "company": login.company,
                "deposit": amount if amount > 0 else 0,
                "withdrawal": -amount if amount < 0 else 0,
                "description": " ".join(x for x in (counterparty, text) if x),
                "reference_number": reference,
                "allocated_amount": 0,
                "unallocated_amount": abs(amount),
                "bank_party_name": counterparty or None,
                "docstatus": 1,
            }).insert(ignore_permissions=True)
            created += 1
        except Exception:
            skipped += 1
            frappe.log_error(
                title="Kefiya: could not store a credit-card transaction",
                message=frappe.get_traceback(),
                reference_doctype="Kefiya Login",
                reference_name=kefiya_login,
            )

    return {"created": created, "skipped": skipped}


# --------------------------------------------------------------------------
# Electronic account statements (documents)
# --------------------------------------------------------------------------

def download_statements(controller, kefiya_login, listing, limit=12):
    """Download the statement documents themselves, not just their names.

    The list from HKEKA only says which statements exist; each one has to be
    fetched separately. They are attached to the Kefiya Login as private files,
    named by year and number so a repeated fetch recognises what it already has
    and does not download it twice.

    :param controller: an initialised FinTSController (reuses the open dialog)
    :param limit: newest N statements per run -- a first fetch can otherwise
        pull years of PDFs in one request
    :return: {"available": int, "downloaded": int, "already_present": int}
    """
    entries = [_as_dict(e) for e in (listing or [])]
    result = {"available": len(entries), "downloaded": 0, "already_present": 0}
    if not entries:
        return result

    for entry in entries[:limit]:
        # HIKAU names them statement_number / year -- checked against the
        # installed python-fints, not guessed.
        number = _first(entry, ("statement_number", "number", "Number"))
        year = _first(entry, ("year", "Year", "statement_year"))
        if number is None:
            continue

        filename = "Kontoauszug-{0}-{1}".format(year or "0000", number)
        if frappe.db.exists("File", {
            "attached_to_doctype": "Kefiya Login",
            "attached_to_name": kefiya_login,
            "file_name": filename,
        }):
            result["already_present"] += 1
            continue

        try:
            content = controller.get_fints_statement(number=number, year=year)
        except Exception:
            frappe.log_error(
                title="Kefiya: statement download failed",
                message=frappe.get_traceback(),
                reference_doctype="Kefiya Login",
                reference_name=kefiya_login,
            )
            continue

        payload = _statement_payload(content)
        if not payload:
            continue

        # A statement is not necessarily a PDF: FinTS StatementFormat allows
        # MT940 and ISO 8583 too, and a .pdf ending on an MT940 file would just
        # fail to open.
        filename = filename + _statement_suffix(content, payload)

        try:
            frappe.get_doc({
                "doctype": "File",
                "file_name": filename,
                "attached_to_doctype": "Kefiya Login",
                "attached_to_name": kefiya_login,
                "is_private": 1,
                "content": payload,
            }).insert(ignore_permissions=True)
            result["downloaded"] += 1
        except Exception:
            frappe.log_error(
                title="Kefiya: could not attach a statement",
                message=frappe.get_traceback(),
                reference_doctype="Kefiya Login",
                reference_name=kefiya_login,
            )

    return result


def _statement_suffix(content, payload):
    """Pick the file ending from what the bank actually sent."""
    fmt = str(_first(_as_dict(content), ("statement_format",), "")).upper()
    if "PDF" in fmt:
        return ".pdf"
    if "MT_940" in fmt or "MT940" in fmt:
        return ".sta"
    # No usable format field: trust the payload itself.
    if isinstance(payload, bytes) and payload[:5] == b"%PDF-":
        return ".pdf"
    return ".txt"


def _statement_payload(content):
    """Reduce whatever the bank returned to bytes worth storing."""
    if not content:
        return None
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    # Some banks wrap the document; take the first bytes-like attribute.
    data = _as_dict(content)
    for key in ("data", "content", "document", "file"):
        value = data.get(key)
        if isinstance(value, bytes):
            return value
        if isinstance(value, str) and value:
            return value.encode("utf-8")
    try:
        return json.dumps(data, default=str).encode("utf-8")
    except Exception:
        return None
