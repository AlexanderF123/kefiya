# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Text, den die Bank in einer pain.001 auch tragen kann.

WOZU. Am 08. und 09.10.2026 lehnte die Sparkasse Heidelberg denselben
Auftrag dreimal ab, jedes Mal nach der Freigabe in der App::

    9050 Die Nachricht enthaelt Fehler.
    9010 Der Auftrag wurde nicht ausgefuehrt.

``9050`` beanstandet die NACHRICHT, nicht die Auftragsdaten -- das waere
9210. Die Nachricht war gueltiges ISO-XML; ``sepa.export(validate=True)``
hatte sie gegen das Schema geprueft und durchgelassen. Max140Text laesst
jedes Unicode-Zeichen zu, die Regeln der Deutschen Kreditwirtschaft nicht.

WAS DIE MESSUNG SAGT, und darauf beruht die Regel hier. Von 14 Auftraegen
dieser Instanz trugen 13 Zeichen, die die DK-Liste streng genommen nicht
kennt -- "ue", "ss" --, und alle 13 hat die Bank ausgefuehrt, zwei davon
auf demselben Konto wie der abgelehnte. Einer trug ein Eurozeichen. Genau
der eine wurde abgelehnt.

Umlaute zu verbieten waere also eine Vermutung gegen die eigene Messung.
Verboten wird, was sich im Zeichensatz der Nachricht ueberhaupt nicht
abbilden laesst: das Eurozeichen liegt bei U+20AC und damit ausserhalb von
Latin-1. Dazu Steuerzeichen -- ein Zeilenumbruch ist kein Text, den ein
Verwendungszweck tragen kann, auch wenn eine Bank ihn einmal geschluckt
hat.

WARUM VORHER UND NICHT HINTERHER. Die Bank lehnt es selbst ab -- aber erst,
nachdem der Auftrag gesendet und eine TAN darauf verbraucht ist. Das ist
dieselbe Begruendung, aus der refuse_paying_yourself existiert, und dieselbe
Haltung wie beim vergangenen Ausfuehrungsdatum: abgelehnt, nicht
stillschweigend umgeschrieben. Aus "400EUR" ein "400 EUR" zu machen waere
harmlos; aus einem Zeichen, das jemand geprueft und freigegeben hat, etwas
anderes zu machen, ist es nicht.

Ohne frappe, aus demselben Grund wie fints_response: die Regel entscheidet
mit, ob eine Zahlung herausgeht, und eine Regel, die nur gegen eine echte
Bank laeuft, laeuft nie.
"""

#: Zeichen, fuer die es einen Namen gibt, den die Bank tragen kann. Kurz
#: gehalten: was hier steht, ist dieser Instanz begegnet. Eine Tabelle aller
#: Sonderzeichen waere eine Tabelle, die niemand pflegt.
ERSATZ = {
    "€": "EUR",   # Eurozeichen -- der Fund vom 09.10.2026
    "£": "GBP",
    "–": "-",     # Halbgeviertstrich, kommt aus Office-Texten
    "—": "-",
    "‘": "'",
    "’": "'",
    "‚": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "…": "...",
    " ": " ",     # geschuetztes Leerzeichen
}

#: Wie ein Steuerzeichen heisst, wenn es in einer Meldung auftaucht.
STEUERZEICHEN = {
    "\n": "Zeilenumbruch",
    "\r": "Zeilenumbruch",
    "\t": "Tabulator",
}


def _nicht_abbildbar(zeichen):
    """Laesst sich das Zeichen im Zeichensatz der Nachricht ueberhaupt
    darstellen?

    Latin-1 ist die Grenze, an der die Praxis haengt: Umlaute liegen darin
    und gehen durch, das Eurozeichen liegt bei U+20AC und nicht.
    """
    try:
        zeichen.encode("latin-1")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return True
    return False


def unsendable(text):
    """Die Zeichen in ``text``, die die Bank nicht tragen kann.

    :return: Liste von dicts ``{"char", "name", "replacement"}``, in der
        Reihenfolge ihres ersten Auftretens und ohne Wiederholung. Leer,
        wenn der Text in Ordnung ist.
    """
    gefunden = []
    gesehen = set()
    for zeichen in str(text or ""):
        if zeichen in gesehen:
            continue
        name = STEUERZEICHEN.get(zeichen)
        if name is None:
            if not _nicht_abbildbar(zeichen):
                continue
            name = "U+{0:04X}".format(ord(zeichen))
        gesehen.add(zeichen)
        gefunden.append({"char": zeichen, "name": name,
                         "replacement": ERSATZ.get(zeichen, "")})
    return gefunden


def repaired(text):
    """Derselbe Text mit den Zeichen, die einen Namen haben, ersetzt.

    Wird dem Nutzer VORGESCHLAGEN, nicht fuer ihn eingesetzt. Was keinen
    Ersatz hat, bleibt stehen -- der Vorschlag soll nicht heimlich etwas
    weglassen, sondern zeigen, was gemeint sein koennte.
    """
    raus = []
    for zeichen in str(text or ""):
        if zeichen in ERSATZ:
            raus.append(ERSATZ[zeichen])
        elif zeichen in STEUERZEICHEN:
            raus.append(" ")
        else:
            raus.append(zeichen)
    return "".join(raus)


def complaint(text):
    """Die Beanstandung in einem Satz, oder "" wenn es keine gibt.

    Nennt die Zeichen beim Namen und den Vorschlag dazu. Ein Nutzer, der
    "9050 Die Nachricht enthaelt Fehler" liest, erfaehrt daraus nichts; ein
    Nutzer, der "das Eurozeichen -- schreiben Sie EUR" liest, ist fertig.
    """
    treffer = unsendable(text)
    if not treffer:
        return ""
    teile = []
    for eintrag in treffer:
        if eintrag["replacement"]:
            teile.append("{0} (statt dessen: {1})".format(
                eintrag["char"] if eintrag["char"].strip() else eintrag["name"],
                eintrag["replacement"]))
        else:
            teile.append(eintrag["char"] if eintrag["char"].strip()
                         else eintrag["name"])
    return ", ".join(teile)
