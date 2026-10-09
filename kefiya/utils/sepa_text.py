# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Text, den die Bank in einer pain.001 tragen kann -- schon bei der Erfassung.

WOZU. Am 08. und 09.10.2026 lehnte die Sparkasse Heidelberg denselben
Auftrag dreimal ab, jedes Mal erst nach der Freigabe in der Banking-App::

    9050 Die Nachricht enthaelt Fehler.
    9010 Der Auftrag wurde nicht ausgefuehrt.

``9050`` beanstandet die NACHRICHT, nicht die Auftragsdaten -- das waere
9210. Die Nachricht war gueltiges ISO-XML; ``sepa.export(validate=True)``
hatte sie gegen das Schema geprueft und durchgelassen. ``Max140Text`` laesst
jedes Unicode-Zeichen zu, die Regeln der Deutschen Kreditwirtschaft nicht.
Das unterscheidende Zeichen war ein Eurozeichen.

KORRIGIERT, NICHT ABGELEHNT. Die erste Fassung dieses Moduls lehnte den
Auftrag ab und nannte den Vorschlag in der Meldung -- aus der Haltung, dass
aus einem Zeichen, das jemand freigegeben hat, nicht stillschweigend ein
anderes wird. Der Nutzer hat anders entschieden: korrigiert wird
automatisch, und zwar bei der Erfassung.

Das ist die Stelle, an der es auch hingehoert. Korrigiert wird, WAEHREND der
Auftrag noch ein Entwurf ist und der Text vor den Augen dessen steht, der
ihn freigibt -- nicht zwischen Freigabe und Bank. Was geaendert wurde, wird
beim Speichern gemeldet; stillschweigend ist hier nichts.

DIE REGEL. Erlaubt ist der Zeichensatz der DK:

    a-z A-Z 0-9 und  / - ? : ( ) . , ' +  und das Leerzeichen

Alles andere wird ersetzt. Wofuer es einen Namen gibt, bekommt den Namen --
"ue" fuer "ue", "EUR" fuer das Eurozeichen; was keinen hat, wird ein
Leerzeichen, so wie gewuenscht. Mehrfache Leerzeichen fallen danach
zusammen, damit aus einem geloeschten Zeichen keine Luecke bleibt.

WAS DIE MESSUNG DAZU SAGT. Von 14 Auftraegen dieser Instanz trugen 13
Umlaute oder ein scharfes s, und alle 13 hat die Bank ausgefuehrt -- die
Umlaute MUESSEN also nicht weg. Sie werden trotzdem umgeschrieben, weil es
so gewuenscht ist und weil es dem DK-Zeichensatz entspricht. Nur das
Eurozeichen musste weg; es liegt bei U+20AC und damit ausserhalb von
Latin-1.

EIN PUNKT ZUM EMPFAENGERNAMEN. Die Bank prueft ihn gegen den Namen des
Kontoinhabers (Verification of Payee). "Mueller" gegen "Mueller" ist eine
Annaeherung, keine Gleichheit -- die Bank kann daraufhin eine Bestaetigung
verlangen. Das tut sie auch sonst, und fints_vop beantwortet es; siehe
payee_check, das Umlaute aus genau diesem Grund NICHT zusammenfaltet.

Ohne frappe, aus demselben Grund wie fints_response: die Regel entscheidet
mit, ob eine Zahlung herausgeht, und eine Regel, die nur gegen eine echte
Bank laeuft, laeuft nie.
"""

#: Der Zeichensatz der Deutschen Kreditwirtschaft fuer pain.001-Texte.
ERLAUBT = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "/-?:().,'+ "
)

#: Zeichen, fuer die es einen Namen gibt, den die Bank tragen kann. Laenger
#: als ein Zeichen sein zu duerfen ist der Punkt: "ue" ist die Antwort auf
#: "ue", nicht "u".
ERSATZ = {
    "ä": "ae", "ö": "oe", "ü": "ue",
    "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
    "ß": "ss",
    "á": "a", "à": "a", "â": "a", "å": "a", "ã": "a",
    "é": "e", "è": "e", "ê": "e", "ë": "e",
    "í": "i", "ì": "i", "î": "i", "ï": "i",
    "ó": "o", "ò": "o", "ô": "o", "õ": "o", "ø": "o",
    "ú": "u", "ù": "u", "û": "u",
    "ý": "y", "ÿ": "y",
    "ç": "c", "ñ": "n",
    "Á": "A", "À": "A", "Â": "A", "Å": "A", "Ã": "A",
    "É": "E", "È": "E", "Ê": "E", "Ë": "E",
    "Í": "I", "Ì": "I", "Î": "I", "Ï": "I",
    "Ó": "O", "Ò": "O", "Ô": "O", "Õ": "O", "Ø": "O",
    "Ú": "U", "Ù": "U", "Û": "U",
    "Ç": "C", "Ñ": "N",
    "æ": "ae", "Æ": "Ae",
    "€": "EUR",   # der Fund vom 09.10.2026
    "£": "GBP",
    "$": "USD",
    "&": "und",
    "%": "Prozent",
    "§": "Par.",
    "–": "-", "—": "-", "−": "-",
    "‘": "'", "’": "'", "‚": "'", "´": "'", "`": "'",
    "“": "'", "”": "'", "„": "'", '"': "'",
    "«": "'", "»": "'",
    "…": "...",
    "°": "Grad",
    "•": "-",
    "½": "1/2", "¼": "1/4", "¾": "3/4",
    "²": "2", "³": "3",
    " ": " ", " ": " ", " ": " ", "​": " ",
}

#: Wie ein Steuerzeichen heisst, wenn eine Meldung es nennen muss. Es
#: unsichtbar in Anfuehrungszeichen zu zeigen hilft niemandem.
STEUERZEICHEN = {
    "\n": "Zeilenumbruch",
    "\r": "Zeilenumbruch",
    "\t": "Tabulator",
}


def _ersetzung(zeichen):
    """Was aus einem Zeichen wird, das nicht erlaubt ist."""
    if zeichen in ERSATZ:
        return ERSATZ[zeichen]
    # Notfalls ein Leerzeichen -- nichts wird einfach weggelassen, denn ein
    # fehlendes Zeichen faellt niemandem auf, eine Luecke schon.
    return " "


def clean(text):
    """Derselbe Text, wie die Bank ihn tragen kann.

    Zweimal angewandt kommt dasselbe heraus wie einmal: der Auftrag wird bei
    jedem Speichern geprueft, und ein Text, der sich dabei jedes Mal weiter
    veraendert, waere nicht mehr der, den jemand freigegeben hat.
    """
    raus = []
    for zeichen in str(text or ""):
        if zeichen in ERLAUBT:
            raus.append(zeichen)
        else:
            raus.append(_ersetzung(zeichen))
    # Aus einem ersetzten Zeichen soll keine Luecke bleiben, und ein
    # Zeilenumbruch hinterlaesst sonst zwei Leerzeichen.
    return " ".join("".join(raus).split())


def changed(text):
    """Hat clean() etwas zu tun? Ohne den Text zweimal zu bauen."""
    text = str(text or "")
    return clean(text) != text


def unsendable(text):
    """Die Zeichen in ``text``, die die Bank nicht tragen kann.

    :return: Liste von dicts ``{"char", "name", "replacement"}``, in der
        Reihenfolge ihres ersten Auftretens und ohne Wiederholung.
    """
    gefunden = []
    gesehen = set()
    for zeichen in str(text or ""):
        if zeichen in ERLAUBT or zeichen in gesehen:
            continue
        gesehen.add(zeichen)
        gefunden.append({
            "char": zeichen,
            "name": STEUERZEICHEN.get(zeichen,
                                      "U+{0:04X}".format(ord(zeichen))),
            "replacement": _ersetzung(zeichen),
        })
    return gefunden


def complaint(text):
    """Was geaendert wurde, in einem Satz; leer, wenn nichts.

    Nennt die Zeichen beim Namen und das, was an ihre Stelle tritt. Ein
    Nutzer, der "9050 Die Nachricht enthaelt Fehler" liest, erfaehrt daraus
    nichts; "das Eurozeichen wurde EUR" ist eine Auskunft.
    """
    teile = []
    for eintrag in unsendable(text):
        sichtbar = (eintrag["char"] if eintrag["char"].strip()
                    else eintrag["name"])
        ersatz = eintrag["replacement"]
        teile.append("{0} -> {1}".format(
            sichtbar, ersatz if ersatz.strip() else "Leerzeichen"))
    return ", ".join(teile)

