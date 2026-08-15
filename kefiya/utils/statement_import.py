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
    """Text out of bytes, trying the encodings these exports actually use."""
    if isinstance(raw, str):
        return raw
    for encoding in _ENCODINGS:
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    # Last resort: never fail the import over one unmappable byte.
    return raw.decode("utf-8", errors="replace")


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

    return {
        "date": date,
        "amount": amount,
        "description": cell("description"),
        "counterparty": cell("counterparty"),
        "iban": cell("iban").replace(" ", "").upper() or None,
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

    for row in rows:
        if not any(str(cell).strip() for cell in row):
            continue
        result["total"] += 1

        entry = to_entry(row, columns, profile)
        if entry is None:
            result["unreadable"] += 1
            continue

        entry["reference_number"] = reference_number(bank_account, entry)

        # A file that repeats a row within itself must not book it twice
        # either -- the database check alone would not catch that.
        if entry["reference_number"] in seen_in_file or frappe.db.exists(
                "Bank Transaction",
                {"reference_number": entry["reference_number"]}):
            result["duplicates"] += 1
            continue

        seen_in_file.add(entry["reference_number"])
        result["new"] += 1
        result["entries"].append(entry)
        if len(result["sample"]) < 5:
            result["sample"].append({
                "date": str(entry["date"]),
                "description": (entry["description"] or "")[:60],
                "in": entry["amount"] if entry["amount"] > 0 else 0,
                "out": -entry["amount"] if entry["amount"] < 0 else 0,
            })

    return result
