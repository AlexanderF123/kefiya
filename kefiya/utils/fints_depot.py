# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Wie man eine Bank nach einem Depotbestand fragt -- die Mechanik dazu.

Getrennt von securities_depot, und die Trennung ist die uebliche: dort
stehen die REGELN (welches Konto ist das Depot, laesst die Bank es zu, was
ist verschwunden), hier steht, was dafuer python-fints anfassen muss. Die
Regeln laufen damit ohne Bench und ohne Bibliothek im Test; diese Datei
braucht beides und wird gegen die Bank gemessen.

Getrennt auch von den Controllern, und das ist der eigentliche Grund: es
gibt zwei davon -- fints_controller und fints_controller_legacy -- und sie
sind keine Verwandten. Haette der Depotabruf in einem von beiden gestanden,
muesste er im anderen ein zweites Mal stehen. Zwei Fassungen desselben
Bankzugriffs sind genau die Sorte Doppelung, die auseinanderlaeuft und bei
der man es erst merkt, wenn eine Seite still nichts mehr liefert.

WAS HKWPD BRAUCHT: keine IBAN. HKWPD5 traegt sein Konto als ``Account2``,
HKWPD6 als ``Account3``, und beide lesen daraus nur Kontonummer,
Unterkontomerkmal, Bankleitzahl und zwei Zeichen Laenderkennung aus der
BIC. Ein Depot ohne eigene IBAN ist damit ganz normal adressierbar -- was
der ganze Grund ist, warum das hier ueberhaupt geht.
"""

import frappe
from frappe import _

from kefiya.utils import securities_depot


def account_entries(connection):
    """Die Kontenliste der Bank aus den UPD, oder eine leere.

    Nie ein Grund zu scheitern: ohne Liste wird die Depotnummer genommen,
    wie sie im Wertpapierkonto steht, und die Bank entscheidet.
    """
    try:
        auskunft = connection.get_information() or {}
        return auskunft.get("accounts") or []
    except Exception:
        return []


def sepa_account_for(blz, bic, account_number, entry=None):
    """Ein Konto-Objekt, das ein Depot adressiert -- oder None.

    :param blz: Bankleitzahl des Zugangs
    :param bic: eine BIC dieses Zugangs (siehe securities_depot.bic_of)
    :param account_number: die Depotnummer aus dem Wertpapierkonto
    :param entry: der Eintrag der Bank zu diesem Depot, falls bekannt
    """
    from fints.models import SEPAAccount

    if not bic or len(str(bic)) < 6:
        return None

    nummer = account_number
    unterkonto = None
    iban = None
    bankleitzahl = blz
    if entry:
        nummer = entry.get("account_number") or account_number
        unterkonto = entry.get("subaccount_number")
        iban = entry.get("iban")
        bankleitzahl = getattr(
            entry.get("bank_identifier"), "bank_code", None) or blz

    return SEPAAccount(iban=iban, bic=str(bic), accountnumber=str(nummer),
                       subaccount=unterkonto, blz=bankleitzahl)


def holdings_of(connection, account, securities_account):
    """Eine HKWPD-Abfrage, als einfache Dicts.

    :return: die Positionen, oder None wenn die Bank statt des Bestands
        eine Freigabe verlangt.

    Das None ist kein Schoenheitsfehler: python-fints GIBT bei einer
    TAN-Anforderung ein NeedTANResponse ZURUECK, statt zu werfen, und
    ``for h in antwort or []`` haette daraus ein "NeedTANResponse object is
    not iterable" gemacht -- mitten im Abruf, fuer eine Momentaufnahme, die
    niemanden aufhalten darf. Geparkt wird die Anforderung nicht: eine
    Freigabe, die niemand gibt, haelt nur einen Dialog offen.
    """
    from fints.client import NeedTANResponse

    antwort = connection.get_holdings(account)
    if isinstance(antwort, NeedTANResponse):
        return None

    bestand = []
    for h in antwort or []:
        bestand.append({
            "isin": getattr(h, "isin", None),
            "security_name": getattr(h, "name", None),
            "quantity": getattr(h, "pieces", None),
            "price": getattr(h, "market_value", None),
            "market_value": getattr(h, "total_value", None),
            "currency": getattr(h, "value_symbol", None),
            "valuation_date": getattr(h, "valuation_date", None),
            "securities_account": securities_account,
        })
    return bestand


def fetch_holdings(connection, blz, depots, sepa_accounts):
    """Den Depotbestand holen -- eine Abfrage je Depot, eine Sitzung.

    Der Dialog muss offen sein; alle Abfragen laufen darin, also kostet
    kein weiteres Depot eine zweite Anmeldung oder eine zweite TAN.

    :param connection: die python-fints-Verbindung
    :param blz: Bankleitzahl des Zugangs
    :param depots: Depotnummern, nach denen gefragt werden soll
    :param sepa_accounts: die bekannten Konten des Zugangs (fuer die BIC)
    :return: {"holdings": [Positionen],
              "refused": [{"securities_account", "reason"}]}
    """
    gewuenscht = securities_depot.wanted_depots(depots)
    if not gewuenscht:
        return {"holdings": [], "refused": []}

    konten = account_entries(connection)
    bic = securities_depot.bic_of(sepa_accounts)

    bestand = []
    abgelehnt = []
    for nummer in gewuenscht:
        eintrag = securities_depot.find_depot_entry(konten, nummer)

        # Nur eine AUSDRUECKLICHE Ablehnung zaehlt. Sagt die Bank ueber das
        # Konto nichts, wird gefragt -- die Antwort kostet nichts als eine
        # Antwort, und Schweigen ist keine Ablehnung. Dieselbe Regel, nach
        # der account_capabilities ein ungefragtes Konto durchlaesst.
        if securities_depot.holdings_allowed(eintrag) is False:
            abgelehnt.append({
                "securities_account": nummer,
                "reason": _("the bank does not offer a securities snapshot"
                            " for depot {0}").format(nummer),
            })
            continue

        konto = sepa_account_for(blz, bic, nummer, eintrag)
        if konto is None:
            abgelehnt.append({
                "securities_account": nummer,
                "reason": _("this access reports no BIC, so depot {0} cannot"
                            " be addressed").format(nummer),
            })
            continue

        try:
            antwort = holdings_of(connection, konto, nummer)
        except Exception as exc:
            # Ein Depot, das sich nicht abrufen laesst, darf die anderen
            # nicht mitnehmen. Der Grund reist mit; die Spur steht im
            # Fehlerprotokoll.
            frappe.log_error(
                title="Kefiya: securities snapshot for one depot failed",
                message="{0}\n\n{1}".format(nummer, frappe.get_traceback()))
            abgelehnt.append({
                "securities_account": nummer,
                "reason": _("depot {0} could not be read: {1}").format(
                    nummer, str(exc)[:120]),
            })
            continue

        if antwort is None:
            abgelehnt.append({
                "securities_account": nummer,
                "reason": _("the bank wants a release for depot {0}. Fetch"
                            " this access by hand once.").format(nummer),
            })
            continue
        bestand.extend(antwort)

    return {"holdings": bestand, "refused": abgelehnt}
