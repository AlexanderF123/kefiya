# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Eine pain.001 ohne BIC des Zahlers, so wie die deutschen Banken sie
lesen.

Ohne frappe, aus demselben Grund wie fints_response und duplicate_rule: das
hier entscheidet ueber den Inhalt einer Zahlungsdatei, und eine Regel, die
nur gegen eine Bank zu pruefen ist, prueft niemand.

Warum es das gibt. Das Bankkonto der Brilu KG traegt keine BIC, und sepaxml
2.7.0 schreibt dann::

    <DbtrAgt><FinInstnId /></DbtrAgt>

Das besteht die ISO-Schemapruefung -- im ISO-Schema ist in FinInstnId alles
optional -- und es ist nicht das, was die Deutsche Kreditwirtschaft
vorschreibt. Deren pain.001.001.03 verlangt fuer das Institut des Zahlers
entweder eine BIC oder, bei IBAN-only::

    <DbtrAgt><FinInstnId><Othr><Id>NOTPROVIDED</Id></Othr></FinInstnId></DbtrAgt>

Die Sparkasse nahm den Auftrag an, prueften den Empfaenger, bat um die
Freigabe in der App -- und nach der Freigabe kam "9010 Der Auftrag wurde
nicht ausgefuehrt", viermal in Folge, an zwei Tagen. Angenommen wird die
Datei beim Eingang; verarbeitet wird sie bei der Ausfuehrung, und dort
gilt das DK-Schema. Kein Auftrag ist je ueber diesen Weg hinausgekommen:
im System steht keine einzige Ueberweisung auf "Gesendet".
"""

import re

NOT_PROVIDED = "NOTPROVIDED"

#: Das leere Institut des Zahlers, wie sepaxml es ohne BIC schreibt -- in
#: beiden Schreibweisen, die ein Serializer dafuer hat.
_LEER = re.compile(r"<DbtrAgt>\s*(?:<FinInstnId\s*/>|<FinInstnId>\s*</FinInstnId>)\s*</DbtrAgt>")

_IBAN_ONLY = ("<DbtrAgt><FinInstnId><Othr><Id>" + NOT_PROVIDED
              + "</Id></Othr></FinInstnId></DbtrAgt>")


def debtor_agent_not_provided(xml):
    """Ein leeres Institut des Zahlers wird zu NOTPROVIDED.

    Nur das leere. Eine BIC bleibt, was sie ist, und eine Datei, in der das
    Element gar nicht vorkommt, bleibt unangetastet -- diese Funktion sagt
    nichts ueber die Datei, sie behebt genau eine Luecke.

    :param xml: die pain.001 als Text
    :return: die pain.001 als Text
    """
    if not xml:
        return xml
    return _LEER.sub(_IBAN_ONLY, xml)


def debtor_agent_is_empty(xml):
    """Sagt die Datei ueber das Institut des Zahlers nichts?"""
    return bool(xml) and _LEER.search(xml) is not None
