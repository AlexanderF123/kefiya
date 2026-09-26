# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Wie oft ein Zugang im Sammelabruf an die Reihe kommt.

Die Volksbank verlangt fuer jeden Auftrag eine Freigabe in ihrer App -- und
der Sammelabruf stellt ihr 30 Zugaenge hintereinander. Vierzehn davon hatten
in 90 Tagen keine einzige Buchung: Geschaeftsanteile, Avale, ein Sparkonto,
ruhende Girokonten. Sie bringen nichts und kosten jedes Mal eine Freigabe.

Gezaehlt am 25.09.2026 auf der Instanz:

    Geschaeftsanteile        3 Zugaenge, 0 Buchungen in 90 Tagen
    Avale                    4 Zugaenge, 2 davon ohne jede Buchung
    Girokonten              24 Zugaenge, 8 davon ohne jede Buchung

Deshalb ein Rhythmus: was sich von Natur aus selten bewegt, wird selten
abgerufen. Die Vorgabe haengt an der Kontoart, die die Bank selbst gemeldet
hat (HIUPD, am Kefiya Login), und laesst sich je Zugang ueberschreiben. Null
heisst "bei jedem Lauf" -- das ist der Stand von vorher, und bei einem
Girokonto bleibt es dabei.

Ausgelassen wird nur der SAMMELabruf. Wer ein Konto von Hand abruft, bekommt
es abgerufen; sonst waere aus einer Schonung eine Sperre geworden.

Ohne frappe und ohne Datum aus der Datenbank: was hier entschieden wird,
muss ohne Bench zu pruefen sein -- wie bei camt_shape und login_siblings.
"""

import datetime

#: Wie oft eine Kontoart hoechstens gebraucht wird, in Tagen. Was hier nicht
#: steht, wird bei jedem Lauf abgerufen -- ein Girokonto bewegt sich taeglich.
#:
#: Die Namen sind die Auswahlwerte von Kefiya Login.account_kind.
DEFAULT_DAYS = {
    "Cooperative Shares": 30,
    "Guarantee / Credit Line": 30,
    "Loan": 30,
    "Securities Account": 7,
}

#: Was "bei jedem Lauf" heisst.
EVERY_RUN = 0


def interval_days(account_kind, setting=None):
    """Der Rhythmus eines Zugangs in Tagen.

    :param account_kind: was die Bank ueber das Konto gesagt hat
    :param setting: was am Zugang eingestellt ist; gesetzt schlaegt es die
        Vorgabe der Kontoart -- auch die 0, mit der jemand ausdruecklich
        "bei jedem Lauf" verlangt. Deshalb entscheidet hier None und nicht
        die Wahrheit des Wertes.
    """
    if setting is not None and str(setting).strip() != "":
        try:
            gewaehlt = int(setting)
        except (TypeError, ValueError):
            gewaehlt = EVERY_RUN
        return max(EVERY_RUN, gewaehlt)
    return DEFAULT_DAYS.get((account_kind or "").strip(), EVERY_RUN)


def _als_zeitpunkt(wert):
    """Was aus der Datenbank kommt, als datetime -- oder None."""
    if wert is None or wert == "":
        return None
    if isinstance(wert, datetime.datetime):
        return wert
    if isinstance(wert, datetime.date):
        return datetime.datetime(wert.year, wert.month, wert.day)
    text = str(wert).strip()
    for form in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text[:26], form)
        except ValueError:
            continue
    return None


def due(last_attempt, interval, now=None):
    """Ist dieser Zugang im Sammelabruf wieder faellig?

    Im Zweifel ja. Ein Zugang, der noch nie abgerufen wurde, ein unlesbares
    Datum, ein Rhythmus von null -- alles das fuehrt zum Abruf. Ausgelassen
    wird nur, was nachweislich noch nicht so lange her ist.
    """
    try:
        tage = int(interval or 0)
    except (TypeError, ValueError):
        return True
    if tage <= EVERY_RUN:
        return True
    zuletzt = _als_zeitpunkt(last_attempt)
    if zuletzt is None:
        return True
    jetzt = now or datetime.datetime.now()
    return (jetzt - zuletzt) >= datetime.timedelta(days=tage)


def due_now(row, now=None):
    """Dieselbe Frage an eine Zeile aus `Kefiya Login`."""
    row = row or {}
    return due(row.get("last_fetch_attempt"),
               interval_days(row.get("account_kind"),
                             row.get("fetch_interval_days")),
               now=now)
