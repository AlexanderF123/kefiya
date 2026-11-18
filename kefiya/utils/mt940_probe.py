# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Eine Probebuchung, an der sich MESSEN laesst, ob die Reparatur wirkt.

Der Verwendungszweck-Fix (``verwendungszweck.py``, eingebaut von
``mt940_compat.py``) hatte fuenf Tests fuer seine Installation, und alle fuenf
lasen den Quelltext als Text: steht der Aufruf vor dem Parsen, steht
``DEFAULT_PROCESSORS`` im Abschnitt. Gruen hiess damit "die Zeile steht da",
nicht "es wirkt".

Am 14.11.2026 kostete genau das einen halben Tag Suche: der Fix stand seit
sechs Wochen im Code, war auf der Instanz deployt, wurde auf dem gelaufenen
Abrufweg erreicht, die Bibliothek fuehrte die erwartete Funktion in der
erwarteten Kette -- und die Verwendungszwecke klebten weiter zusammen.
Nachweisen liess sich das nur an den Daten, nicht an der Testsuite.

Dieses Modul schickt deshalb eine erfundene Buchung wirklich durch den Parser
und sieht nach, was herauskommt. Zwei Eigenschaften machen es dafuer
brauchbar:

* **ohne frappe** -- die Testsuite kann es ohne Bench ausfuehren, und genau
  dort soll der Fehler auffallen;
* **ohne mt940 auf Modulebene** -- es laesst sich auch dort importieren, wo
  die Bibliothek fehlt; dann meldet :func:`die_reparatur_wirkt` schlicht
  False statt den Import des Aufrufers zu sprengen.

Die Daten sind erfunden. Die Bankleitzahlen 99999999 und 88888888 sind in
Deutschland nicht vergeben, die IBAN traegt eine gueltige Pruefsumme, und die
Namen gehoeren niemandem.
"""

#: Zwei Buchungen in einem Auszug, und sie pruefen gegenlaeufige Dinge.
#:
#: Die erste traegt Zeilen der Bank: drei Teilfelder, jedes deutlich kuerzer
#: als die volle Feldbreite, also drei Zeilen und kein Umbruch mitten im Wort.
#: Sie muessen mit Leerzeichen zusammenkommen.
#:
#: Die zweite traegt vom Zahler geschriebenen SEPA-Text hinter ``SVWZ+``, hart
#: umbrochen an der Feldgrenze. Sie darf KEINE Leerzeichen bekommen -- sonst
#: zerfaellt der Text in Bruchstuecke. Eine Reparatur, die nur die erste Zeile
#: besteht, ist keine.
PROBE = (
    ":20:KEFIYAPROBE\n"
    ":25:99999999/1234567890\n"
    ":28C:00000/001\n"
    ":60F:C261112EUR1000,00\n"
    ":61:2611121112CR850,00NMSCNONREF\n"
    ":86:166?00DAUERAUFTRAG?10931?20Miete 11/26?21Zahlung?22unter Vorbehalt"
    "?30BANKDEFFXXX?31DE26888888882345678901?32MUSTERFRAU ERIKA\n"
    ":61:2611121112CR640,00NMSCNONREF\n"
    ":86:166?00UEBERWEISUNG?10932?20SVWZ+MIETE UND BETRIEBSKOST"
    "?21ENPAUSCHALE B"
    "?22UERO LUTHERST?23RASSE?30BANKDEFFXXX?31DE26888888882345678901"
    "?32MUSTERMANN ERIK\n"
    ":62F:C261112EUR2490,00\n"
)

#: So sieht die erste Buchung aus, solange die Reparatur fehlt.
GEKLEBT = "Miete 11/26Zahlungunter Vorbehalt"

#: Und so, wenn sie wirkt.
GETRENNT = "Miete 11/26 Zahlung unter Vorbehalt"

#: Die zweite Buchung sieht in beiden Faellen gleich aus. Das ist der Sinn:
#: getaggter Text wird nicht angefasst.
SEPA = "MIETE UND BETRIEBSKOSTENPAUSCHALE BUERO LUTHERSTRASSE"


def zwecke():
    """Die Verwendungszwecke der Probebuchungen, so wie der Parser sie liefert.

    :return: Liste der Zwecke in der Reihenfolge des Auszugs
    :raises: was immer die Bibliothek wirft -- der Aufrufer entscheidet
    """
    from mt940 import models

    transactions = models.Transactions()
    transactions.parse(PROBE)
    return [(t.data or {}).get("purpose") or "" for t in transactions]


def die_reparatur_wirkt():
    """Wirkt die Reparatur in diesem Prozess, hier und jetzt?

    Keine Vermutung ueber Bibliotheksfassungen, keine Textsuche im Quelltext:
    eine Buchung hinein, der Zweck heraus, verglichen.

    :return: True, wenn Bankzeilen getrennt und SEPA-Text zusammen ankommen
    """
    try:
        gefunden = zwecke()
    except Exception:
        return False
    if len(gefunden) < 2:
        return False
    return gefunden[0] == GETRENNT and gefunden[1] == SEPA


def was_der_parser_liefert():
    """Dasselbe als lesbarer Satz, fuer das Fehlerprotokoll.

    :return: eine Zeile, die beschreibt, was herauskam
    """
    try:
        gefunden = zwecke()
    except Exception as fehler:
        return "Die Probebuchung liess sich nicht parsen: " + str(fehler)[:200]
    if len(gefunden) < 2:
        return ("Die Probebuchung ergab nur " + str(len(gefunden))
                + " Buchung(en).")
    return (
        "Bankzeilen: " + repr(gefunden[0])
        + " (erwartet " + repr(GETRENNT) + "); "
        "SEPA-Text: " + repr(gefunden[1]) + " (erwartet " + repr(SEPA) + ")"
    )
