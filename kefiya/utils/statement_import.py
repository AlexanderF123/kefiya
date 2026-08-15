# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Read a statement file into bookings -- whatever shape the file has.

Kefiya Bank Statement Import could read exactly one CSV: it skipped seven
header rows and then addressed columns by position (0 date, 3 name, 4 purpose,
5 IBAN, 7 amount). A file with a different layout was not rejected, it was
misread -- the amount column of one export is the postcode column of another.

Three things this module does that the positional reader could not:

  * It finds the header row and maps columns BY NAME, so a bank that adds a
    column in the middle does not silently shift every field after it.
  * It knows that a credit card counts the other way round. On a giro account
    a positive amount is money arriving; on a card statement a positive amount
    is a charge -- money leaving. Read with the giro convention, a year of card
    spending books as income. The convention belongs to the format, so it is
    declared with it.
  * It gives every booking a reference the same way a fetched one gets it, so
    importing the same file twice is harmless. The old import had no dedup at
    all: the second import of a file was a second set of bookings.

An account statement is not a trusted document. Every value is parsed
defensively and a row that cannot be read is reported as unreadable rather
than guessed at.
"""

import csv
import hashlib
import io
import re

import frappe
from frappe import _
from frappe.utils import flt, getdate


# --------------------------------------------------------------------------
# Formats
# --------------------------------------------------------------------------

#: Column names are matched case-insensitively, ignoring punctuation and
#: whitespace, and a header only has to CONTAIN the alias -- exports append
#: things like "(EUR)" and banks rename columns between releases.
#:
#: `charges_are_positive` is the sign convention: True where a positive amount
#: means money left the account (every credit card statement), False where a
#: positive amount means money arrived (every giro account).
PROFILES = {
    "amex": {
        "label": "American Express",
        "charges_are_positive": True,
        "columns": {
            "date": ("datum", "date", "transaction date"),
            "amount": ("betrag", "amount"),
            "description": ("beschreibung", "description",
                            "erscheint auf ihrer abrechnung als"),
            "counterparty": ("karteninhaber", "card member", "cardmember"),
            "reference": ("referenz", "reference"),
        },
        # A card statement names no IBAN -- a card has none.
        "required": ("date", "amount"),
    },
    # A StarMoney export names 75 columns and, importantly, carries SEVERAL
    # ACCOUNTS in one file -- one export covering every access the program
    # knows. Its "IBAN" column is therefore the account the booking belongs
    # TO, not the counterparty: read as a counterparty IBAN (which is what a
    # generic giro profile would do) every booking would name its own account
    # as the other side. Hence `own_iban`, which also lets one file be split
    # across the Bank Accounts it covers instead of by hand beforehand.
    "starmoney": {
        "label": "StarMoney CSV",
        "charges_are_positive": False,
        "columns": {
            "own_iban": ("iban",),
            "date": ("buchungstag",),
            "value_date": ("wertstellungstag",),
            "amount": ("betrag",),
            "counterparty": ("beguenstigter absender name",),
            "description": ("verwendungszweckzeile 1",),
            "posting_text": ("buchungstext",),
            # The bank's own running number for the booking. Stable across a
            # re-export of the same period, which is what a reference is for.
            "reference": ("laufende nummer",),
        },
        "required": ("date", "amount", "own_iban"),
    },
    "sepa_csv": {
        "label": "SEPA / Giro CSV",
        "charges_are_positive": False,
        "columns": {
            "date": ("buchungstag", "datum", "date", "valutadatum"),
            "amount": ("betrag", "amount", "umsatz"),
            "description": ("verwendungszweck", "beschreibung", "purpose",
                            "description"),
            "counterparty": ("beguenstigter", "begünstigter", "zahlungspflichtiger",
                             "name", "auftraggeber", "empfaenger", "empfänger"),
            "iban": ("iban", "kontonummer", "account"),
            "reference": ("referenz", "reference", "mandatsreferenz"),
        },
        "required": ("date", "amount"),
    },
}


def _normalise_header(value):
    """Compare header cells without caring about case, spacing or umlauts."""
    text = str(value or "").strip().lower()
    text = (text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
                .replace("ß", "ss"))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _match_columns(header, profile):
    """Position of each canonical field in this header row, or {}.

    A header only has to contain the alias, so "Betrag (EUR)" still matches
    "betrag" -- but the LONGEST matching alias wins, so "datum" does not claim
    the "valutadatum" column while a plain "Datum" column is present.
    """
    cells = [_normalise_header(cell) for cell in header]
    found = {}
    for field, aliases in profile["columns"].items():
        best = None
        for index, cell in enumerate(cells):
            if not cell:
                continue
            for alias in aliases:
                if alias == cell:
                    best = (2, len(alias), index)
                    break
                if alias in cell and (best is None or best[0] < 2):
                    candidate = (1, len(alias), index)
                    if best is None or candidate[:2] > best[:2]:
                        best = candidate
            if best and best[0] == 2 and best[2] == index:
                break
        if best:
            found[field] = best[2]
    return found


def detect_profile(header):
    """Which known format this header row belongs to, or (None, {}).

    The profile that maps the most columns wins; a tie goes to the one whose
    required fields are all present.
    """
    best_name, best_columns, best_score = None, {}, 0
    for name, profile in PROFILES.items():
        columns = _match_columns(header, profile)
        if not all(field in columns for field in profile["required"]):
            continue
        score = len(columns)
        if score > best_score:
            best_name, best_columns, best_score = name, columns, score
    return best_name, best_columns


# --------------------------------------------------------------------------
# Values
# --------------------------------------------------------------------------

_AMOUNT_NOISE = re.compile(r"[^\d,.\-+]")


def parse_amount(value):
    """Read an amount without guessing which separator means what.

    The old reader treated a plain "1234" as 12.34 -- it split off the last two
    digits whenever it found no separator, so an amount written without decimals
    was silently divided by a hundred. Here a number without a separator is that
    number.

    Handles: "1.234,56", "1,234.56", "1234.56", "1234", "-12,50", "12,50-",
    "EUR 1.234,56", non-breaking spaces.

    :return: float, or None when the text is not an amount
    """
    if value is None:
        return None
    text = str(value).replace("\xa0", " ").strip().strip('"').strip()
    if not text:
        return None

    trailing_minus = text.endswith("-") and not text.startswith("-")
    text = _AMOUNT_NOISE.sub("", text)
    if trailing_minus:
        text = "-" + text.rstrip("-")
    text = text.replace("+", "")
    if not text or text in ("-", ".", ","):
        return None

    negative = text.startswith("-")
    digits = text.lstrip("-")

    last_dot, last_comma = digits.rfind("."), digits.rfind(",")
    if last_dot >= 0 and last_comma >= 0:
        # Both present: the one further right is the decimal separator.
        if last_comma > last_dot:
            digits = digits.replace(".", "").replace(",", ".")
        else:
            digits = digits.replace(",", "")
    elif last_comma >= 0:
        # "1,50" is fifty cents, "1,500" is a thousand and a half.
        digits = (digits.replace(",", ".") if len(digits) - last_comma - 1 == 2
                  else digits.replace(",", ""))
    elif last_dot >= 0:
        digits = (digits if len(digits) - last_dot - 1 == 2
                  else digits.replace(".", ""))

    try:
        amount = float(digits)
    except ValueError:
        return None
    return -amount if negative else amount


#: Written out rather than left to dateutil: an ambiguous "01/02/2026" must not
#: silently become the first of February in one file and the second of January
#: in the next. German exports lead with the day.
_DATE_FORMATS = ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y",
                 "%d-%m-%Y", "%Y/%m/%d")


def parse_date(value):
    """Read a booking date, or None. Never today's date as a fallback --
    a booking filed under the wrong day is worse than one that is reported
    as unreadable."""
    from datetime import datetime

    text = str(value or "").strip().strip('"')
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return getdate(text)
    except Exception:
        return None


# --------------------------------------------------------------------------
# Reading the file
# --------------------------------------------------------------------------

#: utf-8-sig first: an export written by Excel carries a byte order mark, and
#: read as plain utf-8 its first header cell begins with an invisible character
#: that stops it matching anything.
_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "iso-8859-1")


def decode(raw):
    """Text out of bytes, trying the encodings these exports actually use.

    The byte order mark is stripped BEFORE the encodings are tried, not left
    to utf-8-sig. A real StarMoney export turned out to carry a UTF-8 BOM in
    front of a cp1252 body -- the mark says "this is UTF-8" and the umlauts
    say otherwise. Read as utf-8-sig it fails on the first umlaut; read as
    cp1252 with the mark left in place, the first header cell begins with
    "ï»¿" and matches no column name. Removing the mark first makes both
    halves readable.
    """
    if isinstance(raw, str):
        return raw.lstrip("﻿")
    if raw[:3] == b"\xef\xbb\xbf":
        raw = raw[3:]

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass

    # Not one encoding but two. A real export turned out to hold 887 UTF-8
    # lines and 1.695 cp1252 lines in the same file -- accesses exported at
    # different times, concatenated. Decoded wholesale either way, one half
    # comes out wrong: as cp1252 every "Ü" becomes "Ãœ", as UTF-8 the file
    # will not decode at all.
    #
    # Line by line, both halves come out right. Splitting on the newline byte
    # is safe for every encoding here, because none of them uses 0x0A inside
    # a multi-byte sequence -- and the lines are rejoined exactly as found, so
    # a newline inside a quoted CSV field survives untouched.
    out = []
    for line in raw.split(b"\n"):
        for encoding in _ENCODINGS:
            try:
                out.append(line.decode(encoding))
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            out.append(line.decode("utf-8", errors="replace"))
    return "\n".join(out)


def _delimiter(sample):
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except Exception:
        # Sniffer gives up on short or irregular files; the German exports are
        # semicolon-separated far more often than not.
        return ";" if sample.count(";") >= sample.count(",") else ","


def read_rows(text, max_header_scan=25):
    """Split the text into a header row and the data rows beneath it.

    The header is not assumed to be the first line. Exports put a title, an
    account summary and a blank line above it -- the old reader hard-coded
    "skip seven", which is a fact about one file, not about statements.

    :return: (profile_name, columns, rows, header_index) -- profile None when
        no known format matched.
    """
    reader = csv.reader(io.StringIO(text), delimiter=_delimiter(text[:4096]))
    rows = [row for row in reader]

    for index, row in enumerate(rows[:max_header_scan]):
        if not any(str(cell).strip() for cell in row):
            continue
        name, columns = detect_profile(row)
        if name:
            return name, columns, rows[index + 1:], index

    return None, {}, rows, None


# --------------------------------------------------------------------------
# Rows to bookings
# --------------------------------------------------------------------------

def to_entry(row, columns, profile):
    """One canonical booking out of one CSV row, or None if unreadable."""
    def cell(field):
        index = columns.get(field)
        if index is None or index >= len(row):
            return ""
        return str(row[index] or "").strip().strip('"').strip()

    date = parse_date(cell("date"))
    amount = parse_amount(cell("amount"))
    if date is None or amount is None:
        return None

    # The sign convention of the format, applied once and here, so everything
    # downstream can think in "money in / money out" alone.
    if profile["charges_are_positive"]:
        amount = -amount

    # The posting text ("LASTSCHRIFT", "RECHNUNG", "DAUERAUFTRAG") is what the
    # bank called the movement; the purpose line is what the payer wrote. Both
    # are worth keeping, and neither is worth losing to the other.
    description = " ".join(
        part for part in (cell("posting_text"), cell("description")) if part)

    return {
        "date": date,
        "amount": amount,
        "description": description,
        "counterparty": cell("counterparty"),
        "iban": cell("iban").replace(" ", "").upper() or None,
        # The account the booking belongs TO, where the format names it. A
        # file covering twenty accesses is split by this rather than by hand.
        "own_iban": cell("own_iban").replace(" ", "").upper() or None,
        "reference": cell("reference") or None,
    }


def reference_number(bank_account, entry):
    """The identity of a booking, so a second import recognises it.

    Built the same way store_credit_card_transactions() builds it for a fetched
    card booking, and deliberately NOT from the row number: a file downloaded a
    week later has the same bookings at different positions.

    Where the export carries the bank's own reference, that is used instead --
    it is the only identifier that survives a changed description.
    """
    if entry.get("reference"):
        raw = "st|{0}|{1}".format(bank_account, entry["reference"])
    else:
        raw = "st|{0}|{1}|{2}|{3}|{4}".format(
            bank_account, entry["date"], entry["amount"],
            entry.get("counterparty") or "",
            (entry.get("description") or "")[:120])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def already_booked(bank_account, entry):
    """Is this booking already on the account, under whatever reference?

    The reference hash only recognises what THIS module wrote. A booking the
    bank itself delivered by FinTS carries the bank's reference, so a hash
    comparison sees a stranger and books it a second time -- which is exactly
    the situation when a statement file is used to fill a gap in an account
    that is otherwise fetched.

    So the second line of defence compares what a booking IS: same account,
    same day, same amount. That is deliberately blunt. Two genuinely distinct
    bookings of the same amount on the same day do exist -- two identical
    parking fees, two equal rent payments -- and this will hold the second one
    back. Reporting a real booking as "already present" is recoverable by
    looking at the day; creating a duplicate in the ledger is the error that
    took 3.000 entries to notice the last time.

    :return: name of the existing Bank Transaction, or None
    """
    amount = flt(entry["amount"])
    side = ("deposit", flt(amount)) if amount > 0 else ("withdrawal", flt(-amount))

    rows = frappe.get_all(
        "Bank Transaction",
        filters={
            "bank_account": bank_account,
            "date": str(entry["date"]),
            side[0]: side[1],
        },
        fields=["name"], limit=1)
    return rows[0]["name"] if rows else None


def file_content(file_url):
    """The attached file's bytes, through the File document.

    Not site_path + file_url: that string only happens to be the path for a
    public file, and a private attachment lives somewhere else entirely.
    """
    name = frappe.db.get_value("File", {"file_url": file_url})
    if not name:
        frappe.throw(_("The attached file could not be found: {0}").format(
            file_url))
    return frappe.get_doc("File", name).get_content()


def normalise_pushed(entry, profile_name=None, charges_are_positive=None):
    """One booking out of one record handed over by an outside service.

    A card issuer that speaks no FinTS is still reachable -- through a licensed
    account information service (the PSD2 route a bank aggregator provides) or
    through a document service that already holds the connection. What arrives
    from either is a record, not a CSV row, so it needs the same treatment
    without the file reading: amounts and dates parsed defensively, and above
    all the SIGN settled.

    The sign is why this takes a profile rather than assuming one. A card
    feed states a charge as a positive number; a giro feed states money
    arriving as a positive number. Guessing wrong books a year of spending as
    income, and nothing downstream would notice.

    :param entry: dict from the caller, keys as tolerated by _first()
    :param profile_name: key in PROFILES whose sign convention applies
    :param charges_are_positive: explicit override, wins over the profile
    :return: canonical entry, or None when it cannot be read
    """
    if charges_are_positive is None:
        if profile_name not in PROFILES:
            frappe.throw(_(
                "Unknown statement format {0}. Pass a known format or state"
                " the sign convention explicitly -- a card feed and a giro"
                " feed count the opposite way round."
            ).format(profile_name))
        charges_are_positive = PROFILES[profile_name]["charges_are_positive"]

    def pick(*keys):
        for key in keys:
            if key in entry and entry[key] not in (None, ""):
                return entry[key]
        return None

    date = parse_date(pick("date", "bookingDate", "booking_date", "datum",
                           "valueDate", "transactionDate"))
    amount = parse_amount(pick("amount", "betrag", "value"))
    if date is None or amount is None:
        return None

    if charges_are_positive:
        amount = -amount

    iban = pick("iban", "counterpartyIban", "bank_party_iban")
    return {
        "date": date,
        "amount": amount,
        "description": str(pick("description", "purpose", "verwendungszweck",
                                "beschreibung", "reference_text") or ""),
        "counterparty": str(pick("counterparty", "counterpartyName",
                                 "merchant", "name", "karteninhaber") or ""),
        "iban": str(iban).replace(" ", "").upper() if iban else None,
        # The service's own id is the best reference there is: it survives a
        # changed description and a re-download of the same period.
        "reference": pick("reference", "referenz", "transactionId",
                          "transaction_id", "id"),
    }


@frappe.whitelist()
def ingest(bank_account, entries, profile=None, charges_are_positive=None,
           dry_run=1):
    """Book what an outside service fetched, deciding here rather than there.

    This is the endpoint an automation calls -- the transport fetches, this
    validates and books. The caller never writes a Bank Transaction itself:
    the sign convention, the deduplication and the permission check belong on
    this side, where they are the same for every source.

    Defaults to a dry run. A bulk write that only happens when it was asked
    for by name is one that cannot be triggered by a misconfigured workflow.

    :param entries: list of dicts (or its JSON form)
    :param profile: key in PROFILES supplying the sign convention
    :param dry_run: 1 = report what would happen, write nothing
    :return: {"created"|"would_create", "duplicates", "unreadable", "sample"}
    """
    from frappe.utils import cint

    # Permission gate: a whitelisted endpoint is callable by any logged-in
    # user, and this one creates bookings on a named account.
    frappe.has_permission("Bank Account", ptype="write", doc=bank_account,
                          throw=True)
    frappe.has_permission("Bank Transaction", ptype="create", throw=True)

    if isinstance(entries, str):
        entries = frappe.parse_json(entries)
    if not isinstance(entries, (list, tuple)):
        frappe.throw(_("ingest expects a list of entries."))

    if charges_are_positive is not None:
        charges_are_positive = bool(cint(charges_are_positive))

    company = frappe.db.get_value("Bank Account", bank_account, "company")
    result = {"total": len(entries), "duplicates": 0, "unreadable": 0,
              "created": 0, "would_create": 0, "sample": [],
              "dry_run": bool(cint(dry_run))}
    seen = set()

    for raw in entries:
        entry = normalise_pushed(
            raw if isinstance(raw, dict) else {},
            profile_name=profile, charges_are_positive=charges_are_positive)
        if entry is None:
            result["unreadable"] += 1
            continue

        reference = reference_number(bank_account, entry)
        if reference in seen or frappe.db.exists(
                "Bank Transaction", {"reference_number": reference}):
            result["duplicates"] += 1
            continue
        seen.add(reference)

        if len(result["sample"]) < 5:
            result["sample"].append({
                "date": str(entry["date"]),
                "description": (entry["description"] or "")[:60],
                "in": entry["amount"] if entry["amount"] > 0 else 0,
                "out": -entry["amount"] if entry["amount"] < 0 else 0,
            })

        if result["dry_run"]:
            result["would_create"] += 1
            continue

        # Created as a draft on purpose. Submitting is an approval, and an
        # approval is not something an unattended feed gives itself.
        frappe.get_doc({
            "doctype": "Bank Transaction",
            "date": str(entry["date"]),
            "status": "Unreconciled",
            "bank_account": bank_account,
            "company": company,
            "deposit": entry["amount"] if entry["amount"] > 0 else 0,
            "withdrawal": -entry["amount"] if entry["amount"] < 0 else 0,
            "description": " ".join(
                x for x in (entry["counterparty"], entry["description"]) if x),
            "bank_party_iban": entry.get("iban"),
            "bank_party_name": entry["counterparty"] or None,
            "reference_number": reference,
            "allocated_amount": 0,
            "unallocated_amount": abs(entry["amount"]),
        }).insert(ignore_permissions=True)
        result["created"] += 1

    return result


@frappe.whitelist()
def attach_statement(bank_account, filename, content_base64, period=None):
    """File a statement document that came from outside FinTS.

    The gap this closes is a specific one: the PSD2 account information route
    delivers bookings and balances and no documents at all -- there is no
    statement PDF in it, by design. A card issuer that speaks no FinTS
    therefore leaves the bookings reachable and the statements not.

    So a document service that already holds that connection can hand the PDF
    over here, and it lands exactly where a fetched one lands: attached to the
    BANK ACCOUNT as a private file, named so that handing the same one over
    twice is recognised rather than filed twice. Same rule as
    download_statements() in fetch_persistence.

    :param content_base64: the document itself, base64 encoded
    :param period: e.g. "2026-08"; only used to build a stable name
    :return: {"stored": bool, "file": name|None, "reason": str|None}
    """
    import base64

    frappe.has_permission("Bank Account", ptype="write", doc=bank_account,
                          throw=True)

    # A statement is a private document about an account. Keeping the name
    # deterministic is what makes a repeated hand-over idempotent.
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(filename or "")).strip("-")
    if not safe:
        safe = "Kontoauszug-{0}".format(period or "unbenannt")
    if period and period not in safe:
        safe = "{0}-{1}".format(period, safe)

    existing = frappe.db.exists("File", {
        "attached_to_doctype": "Bank Account",
        "attached_to_name": bank_account,
        "file_name": safe,
    })
    if existing:
        return {"stored": False, "file": existing,
                "reason": "already present"}

    try:
        payload = base64.b64decode(content_base64 or "", validate=True)
    except Exception:
        frappe.throw(_("The document could not be decoded."))
    if not payload:
        frappe.throw(_("The document is empty."))

    doc = frappe.get_doc({
        "doctype": "File",
        "file_name": safe,
        "attached_to_doctype": "Bank Account",
        "attached_to_name": bank_account,
        "is_private": 1,
        "content": payload,
    }).insert(ignore_permissions=True)
    return {"stored": True, "file": doc.name, "reason": None}


def plan(file_url, bank_account):
    """Read the file and report what an import WOULD do. Writes nothing.

    This is the dry run the process asks for before a bulk write: the reader
    can see which format was recognised, how the first bookings were
    understood -- above all which way round the signs came out -- and how many
    rows are already present, before a single Bank Transaction exists.

    :return: dict(profile, label, header_row, total, new, duplicates,
        unreadable, sample, entries)
    """
    text = decode(file_content(file_url))
    profile_name, columns, rows, header_index = read_rows(text)

    result = {
        "profile": profile_name,
        "label": PROFILES[profile_name]["label"] if profile_name else None,
        "header_row": header_index,
        "total": 0, "new": 0, "duplicates": 0, "unreadable": 0,
        "sample": [], "entries": [],
    }
    if not profile_name:
        result["reason"] = _(
            "No known column layout was recognised in this file.")
        return result

    profile = PROFILES[profile_name]
    seen_in_file = set()
    by_iban = {}
    result["accounts"] = {}

    for row in rows:
        if not any(str(cell).strip() for cell in row):
            continue
        result["total"] += 1

        entry = to_entry(row, columns, profile)
        if entry is None:
            result["unreadable"] += 1
            continue

        # A file may cover many accounts -- a StarMoney export covers every
        # access the program knows. The row says which one it belongs to, so
        # nobody has to split the file by hand and nobody can file April's
        # bookings of one account against another.
        target = bank_account
        if entry.get("own_iban"):
            if entry["own_iban"] not in by_iban:
                by_iban[entry["own_iban"]] = _bank_account_for_iban(
                    entry["own_iban"])
            target = by_iban[entry["own_iban"]]
            if not target:
                result.setdefault("unmatched_ibans", {})
                key = _mask_own(entry["own_iban"])
                result["unmatched_ibans"][key] = \
                    result["unmatched_ibans"].get(key, 0) + 1
                continue

        entry["bank_account"] = target
        entry["reference_number"] = reference_number(target, entry)

        per = result["accounts"].setdefault(
            target, {"new": 0, "duplicates": 0})

        # Three ways the same booking can already be here, checked in order of
        # cost: twice within this file, already imported by this module, or
        # already delivered by the bank under its own reference. The last one
        # is the case that matters when a file fills a gap in an account that
        # is otherwise fetched -- a reference comparison alone would miss it
        # entirely and book everything a second time.
        if (entry["reference_number"] in seen_in_file
                or frappe.db.exists(
                    "Bank Transaction",
                    {"reference_number": entry["reference_number"]})
                or already_booked(target, entry)):
            result["duplicates"] += 1
            per["duplicates"] += 1
            continue

        seen_in_file.add(entry["reference_number"])
        result["new"] += 1
        per["new"] += 1
        result["entries"].append(entry)
        if len(result["sample"]) < 5:
            result["sample"].append({
                "date": str(entry["date"]),
                "description": (entry["description"] or "")[:60],
                "in": entry["amount"] if entry["amount"] > 0 else 0,
                "out": -entry["amount"] if entry["amount"] < 0 else 0,
            })

    return result


def _mask_own(iban):
    return "..." + str(iban)[-4:] if iban else None


def _bank_account_for_iban(iban):
    """The Bank Account carrying this IBAN, or None.

    Compared without spaces and in upper case, because an IBAN is written
    both ways and a file must not fail to match over a blank.
    """
    cleaned = str(iban or "").replace(" ", "").upper()
    if not cleaned:
        return None
    for row in frappe.get_all("Bank Account",
                              filters={"iban": ["is", "set"]},
                              fields=["name", "iban"]):
        if str(row["iban"] or "").replace(" ", "").upper() == cleaned:
            return row["name"]
    return None
