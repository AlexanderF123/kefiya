# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Storage layer for FinTS securities holdings (Depot / Wertpapiere).

Holdings are an informational point-in-time snapshot, never a GL posting.
``refresh_holdings`` is the source-agnostic ingest entry point; the FinTS
controllers fetch the raw holdings (get_holdings / HKWPD) and hand a list of
plain dicts to it. One row per (login, ISIN, valuation date) yields a time
series for portfolio reporting.
"""

import hashlib

import frappe
from frappe.utils import now_datetime, getdate, flt

from kefiya.utils import securities_depot

DOCTYPE = "Kefiya Security Holding"


def compute_holding_key(securities_account, isin, valuation_date):
    """Stable hash for one snapshot (per securities account, ISIN, valuation date)."""
    parts = [
        (securities_account or "").strip(),
        (isin or "").strip().upper(),
        str(getdate(valuation_date)) if valuation_date else "",
    ]
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()


def get_or_create_securities_account(account_number, company, kefiya_login=None):
    """Return the Kefiya Securities Account (Depot) for an account number,
    creating it (owned by ``company``) if it does not exist yet."""
    if not account_number:
        return None
    name = frappe.db.get_value(
        "Kefiya Securities Account", {"account_number": account_number}, "name"
    )
    if name:
        return name
    account = frappe.get_doc({
        "doctype": "Kefiya Securities Account",
        "account_number": account_number,
        "company": company,
        "kefiya_login": kefiya_login,
    })
    account.insert(ignore_permissions=True)
    return account.name


def refresh_holdings(kefiya_login, holdings):
    """Idempotently upsert a securities snapshot for a login.

    :param kefiya_login: Kefiya Login name
    :param holdings: list of dicts with keys isin, security_name, quantity,
        price, market_value, currency, valuation_date, securities_account
    :return: dict with created / updated / closed counts and one entry per
        depot in ``accounts``
    """
    login = frappe.get_doc("Kefiya Login", kefiya_login)
    company = login.company
    now = now_datetime()

    created = updated = 0
    # Je Depot: was in dieser Momentaufnahme steht. Gebraucht fuer die
    # Aufstellung in der Rueckgabe und fuer die verkauften Positionen.
    je_depot = {}

    for item in holdings or []:
        isin = item.get("isin")
        valuation_date = item.get("valuation_date")
        securities_account = item.get("securities_account")
        if not isin or not valuation_date or not securities_account:
            # without a stable identity / depot we cannot store it -- skip
            continue

        try:
            account = get_or_create_securities_account(
                securities_account, company, kefiya_login
            )
            # only set the Currency link when it resolves to a real Currency,
            # otherwise a non-ISO value_symbol would abort the row.
            currency = (item.get("currency") or "").strip().upper()
            if currency and not frappe.db.exists("Currency", currency):
                currency = None
            values = {
                "kefiya_login": kefiya_login,
                "securities_account": account,
                "company": company,
                "valuation_date": getdate(valuation_date),
                "isin": isin,
                "security_name": item.get("security_name"),
                "currency": currency,
                "quantity": flt(item.get("quantity")),
                "price": flt(item.get("price")),
                "market_value": flt(item.get("market_value")),
                "fetched_on": now,
            }

            if _upsert_holding(values):
                created += 1
            else:
                updated += 1

            stand = je_depot.setdefault(account, {
                "valuation_date": values["valuation_date"],
                "isins": set(), "positions": 0, "market_value_total": 0.0,
            })
            stand["isins"].add(str(isin).strip().upper())
            stand["positions"] += 1
            stand["market_value_total"] += values["market_value"]
            # Meldet die Bank mehrere Bewertungstage in einem Lauf, gilt der
            # juengste als der Stand dieses Depots.
            if values["valuation_date"] > stand["valuation_date"]:
                stand["valuation_date"] = values["valuation_date"]
        except Exception:
            # one malformed holding must not drop the whole snapshot
            frappe.log_error(
                title="Kefiya security holding upsert failed",
                message="{0}\n\n{1}".format(isin, frappe.get_traceback()),
            )

    closed = 0
    for account, stand in je_depot.items():
        closed += _close_vanished_positions(
            kefiya_login, company, account, stand, now)

    return {
        "created": created,
        "updated": updated,
        "closed": closed,
        "accounts": [
            {
                "securities_account": account,
                "positions": stand["positions"],
                "market_value_total": stand["market_value_total"],
            }
            for account, stand in sorted(je_depot.items())
        ],
    }


def _upsert_holding(values):
    """Write one snapshot row. True when it was new, False when it existed.

    Die Identitaet ist (Depot, ISIN, Bewertungstag) -- derselbe Tag noch
    einmal abgerufen aktualisiert, statt eine zweite Zeile anzulegen.
    """
    key = compute_holding_key(
        values["securities_account"], values["isin"], values["valuation_date"])
    existing = frappe.db.get_value(DOCTYPE, {"reference_key": key}, "name")
    if existing:
        doc = frappe.get_doc(DOCTYPE, existing)
        doc.update(values)
        doc.save(ignore_permissions=True)
        return False
    doc = frappe.get_doc(dict(doctype=DOCTYPE, reference_key=key, **values))
    doc.insert(ignore_permissions=True)
    return True


def _close_vanished_positions(kefiya_login, company, account, stand, now):
    """Verkaufte Papiere mit Menge 0 fortschreiben.

    Ein Papier, das die Bank nicht mehr meldet, verschwindet sonst wortlos
    aus der Liste: der letzte Stand bleibt als Historie stehen, und nichts
    sagt, dass die Position aufgeloest wurde. Wer den Bestand von gestern
    neben den von heute legt, sieht eine Zeile fehlen und weiss nicht, ob
    sie verkauft wurde oder ob der Abruf unvollstaendig war.

    Also bekommt jede verschwundene ISIN einen Stand am heutigen
    Bewertungstag mit Menge 0. Alle drei Zahlen stehen auf 0, auch der
    Kurs: was nicht mehr im Depot liegt, hat fuer dieses Depot keinen Kurs,
    und ein stehengelassener Kurs liesse sich als aktueller lesen.

    Verglichen wird gegen den juengsten FRUEHEREN Bewertungstag dieses
    Depots, nicht gegen alles, was je da war -- sonst wuerde jedes einmal
    verkaufte Papier bei jedem Abruf erneut nullgestellt.

    Nie ein Grund zu scheitern: die Momentaufnahme selbst ist schon
    geschrieben.
    """
    try:
        vorher_tag = frappe.db.get_value(
            DOCTYPE,
            {"securities_account": account,
             "valuation_date": ("<", stand["valuation_date"])},
            "valuation_date",
            order_by="valuation_date desc")
        if not vorher_tag:
            return 0

        vorherige = frappe.get_all(
            DOCTYPE,
            filters={"securities_account": account,
                     "valuation_date": getdate(vorher_tag)},
            fields=["isin", "security_name", "currency", "quantity"],
            limit_page_length=0)

        bekannt = {}
        for zeile in vorherige:
            if flt(zeile.get("quantity")) == 0:
                # Schon nullgestellt -- kein zweites Mal.
                continue
            bekannt[str(zeile.get("isin") or "").strip().upper()] = zeile

        verschwunden = securities_depot.vanished_positions(
            bekannt.keys(), stand["isins"])

        geschlossen = 0
        for isin in verschwunden:
            zeile = bekannt.get(isin) or {}
            _upsert_holding({
                "kefiya_login": kefiya_login,
                "securities_account": account,
                "company": company,
                "valuation_date": stand["valuation_date"],
                "isin": zeile.get("isin") or isin,
                "security_name": zeile.get("security_name"),
                "currency": zeile.get("currency"),
                "quantity": 0.0,
                "price": 0.0,
                "market_value": 0.0,
                "fetched_on": now,
            })
            geschlossen += 1
        return geschlossen
    except Exception:
        frappe.log_error(
            title="Kefiya: closing sold securities positions failed",
            message="{0}\n\n{1}".format(account, frappe.get_traceback()),
        )
        return 0
