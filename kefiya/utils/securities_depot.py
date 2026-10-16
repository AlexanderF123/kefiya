# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Welches Konto der Bank ein Depot ist -- und was die Bank dazu sagt.

Ohne frappe und ohne python-fints, aus demselben Grund wie fints_response und
sepa_text: hier wird entschieden, an WELCHES Konto HKWPD geht, und eine Regel,
die nur gegen eine echte Bank zu pruefen ist, prueft niemand.

DER FEHLER, DER DAS NOETIG MACHT. Der Depotbestand wurde fuer das Konto des
Logins abgefragt -- also fuer das Giro- oder Tagesgeldkonto, an dem der Zugang
haengt::

    account = self._require_fints_account()        # das Konto des LOGINS
    holdings = self.fints_connection.get_holdings(account)
    ...
    "securities_account": self.kefiya_login.account_iban

Die Bank erlaubt HKWPD fuer ein Girokonto nicht. Sie lehnte ab, python-fints
machte daraus seinen BPD-Satz, _optional_fetch las das korrekt als "bietet die
Bank hier nicht an" -- und `holdings` blieb still auf {created: 0, updated: 0}
stehen. Kein Error Log, kein einziger Datensatz, monatelang.

DIE FALLE BEIM ZUORDNEN, und sie ist keine theoretische: bei mindestens einer
Bank traegt das Depot DIESELBE Nummer wie das Girokonto desselben Kunden (das
Giro hat sie in der IBAN). Wer nur auf die Nummer vergleicht, fragt wieder das
Giro und bekommt wieder nichts.

Aufgeloest wird das nicht ueber eine Tabelle von Kontoart-Schluesseln -- die
muesste man raten -- sondern ueber die Auskunft der Bank selbst: unter den
Konten mit derselben Nummer ist das Depot jenes, fuer das die Bank HKWPD
zulaesst. Das steht je Konto in den UPD (HIUPD, "erlaubte
Geschaeftsvorfaelle") und kommt bei python-fints als
``get_information()['accounts'][n]['supported_operations']`` heraus.

WAS HKWPD BRAUCHT, und das ist die gute Nachricht: keine IBAN. HKWPD5 traegt
sein Konto als ``Account2``, HKWPD6 als ``Account3``, und beide lesen aus dem
uebergebenen Konto nur Kontonummer, Unterkontomerkmal, Bankleitzahl und zwei
Zeichen Laenderkennung aus der BIC. Ein Depot ohne IBAN ist damit ganz normal
adressierbar.
"""


def normalize_account_number(value):
    """Eine Konto- oder Depotnummer so, dass zwei Schreibweisen gleich sind.

    Banken schreiben dieselbe Nummer mit Leerzeichen, mit Bindestrichen und
    mit fuehrenden Nullen. Verglichen wird ohne das alles -- aber eine Nummer,
    die NUR aus Nullen besteht, bleibt eine Null und wird nicht zu "".
    """
    gestrafft = "".join(
        zeichen for zeichen in str(value or "") if zeichen.isalnum())
    if not gestrafft:
        return ""
    ohne_nullen = gestrafft.lstrip("0")
    return ohne_nullen or "0"


def wanted_depots(depots):
    """Die brauchbaren Depotnummern aus einer Liste -- leere fallen weg.

    Eine Zeile, weil sie an drei Stellen gebraucht wird: beide Controller
    fragen damit "ist ueberhaupt ein Depot verknuepft", und fetch_holdings
    laeuft darueber. Dreimal dieselbe Verstaendnisfrage, dreimal
    buchstabiert, waere dreimal die Chance, sie verschieden zu beantworten.
    """
    return [str(nummer).strip() for nummer in (depots or [])
            if str(nummer or "").strip()]


def same_account_number(left, right):
    """Meinen die beiden Schreibweisen dieselbe Nummer?"""
    links = normalize_account_number(left)
    return bool(links) and links == normalize_account_number(right)


#: Der Geschaeftsvorfall, um den es geht. Der Name ist der des
#: FinTSOperations-Mitglieds der Bibliothek, das Kuerzel seiner Belegung --
#: geprueft wird beides, damit ein Umbenennen auf einer Seite nicht still
#: dazu fuehrt, dass jedes Depot als "nicht erlaubt" gilt.
HOLDINGS_OPERATION = "GET_HOLDINGS"
HOLDINGS_SEGMENT = "HKWPD"


def holdings_allowed(entry):
    """Laesst die Bank fuer DIESES Konto einen Depotbestand zu?

    :param entry: ein Eintrag aus ``get_information()['accounts']``
    :return: True (die Bank nennt ihn), False (sie nennt ihn nicht),
        None (es gibt keine Auskunft -- dann ist nichts bewiesen)

    None ist nicht False. Ein Konto, ueber das die Bank nichts gesagt hat,
    darf nicht wie ein abgelehntes behandelt werden: dieselbe Regel, die
    account_capabilities "Schweigen ist keine Erlaubnis und keine Ablehnung"
    nennt. Hier faellt sie zugunsten des Versuchs aus -- die Bank sagt dann
    beim Abruf selbst, was sie davon haelt, und das kostet eine Antwort,
    keinen Auftrag.
    """
    try:
        unterstuetzt = (entry or {}).get("supported_operations")
    except Exception:
        return None
    if not unterstuetzt:
        return None

    try:
        eintraege = list(unterstuetzt.items())
    except Exception:
        return None

    for schluessel, erlaubt in eintraege:
        if _is_holdings_operation(schluessel):
            return bool(erlaubt)
    return None


def _is_holdings_operation(schluessel):
    """Ist dieser Schluessel der Depotbestand? Ueber Name ODER Kuerzel.

    Jeder Zugriff einzeln abgesichert, auch das getattr selbst: ``.name``
    kann ein Property sein, und ein Property ist fremder Code, der beim
    Lesen werfen darf. Genau daran scheiterte schon einmal die Frage "hat
    die Bank den Auftrag abgelehnt" -- siehe fints_response._entries_of.
    Ein Schluessel, der sich nicht lesen laesst, ist ein Schluessel
    weniger, kein Abbruch.
    """
    try:
        name = getattr(schluessel, "name", None)
        if name and str(name).upper() == HOLDINGS_OPERATION:
            return True
    except Exception:
        pass

    try:
        belegung = getattr(schluessel, "value", None)
        if belegung and HOLDINGS_SEGMENT in [
                str(code).upper() for code in belegung]:
            return True
    except Exception:
        pass

    try:
        return str(schluessel).upper().endswith(HOLDINGS_OPERATION)
    except Exception:
        return False


def find_depot_entry(accounts, account_number):
    """Der Eintrag der Bank fuer diese Depotnummer, oder None.

    Unter mehreren Konten derselben Nummer gewinnt das, fuer das die Bank
    den Depotbestand zulaesst -- siehe die Falle im Modulkopf. Gibt es kein
    solches, wird der erste Treffer zurueckgegeben: dann entscheidet die
    Bank beim Abruf, nicht diese Funktion.

    :param accounts: ``get_information()['accounts']``
    :param account_number: die Depotnummer aus dem Wertpapierkonto
    :return: der Eintrag oder None
    """
    treffer = []
    for entry in accounts or []:
        try:
            nummer = (entry or {}).get("account_number")
        except Exception:
            continue
        if same_account_number(nummer, account_number):
            treffer.append(entry)

    if not treffer:
        return None
    for entry in treffer:
        if holdings_allowed(entry) is True:
            return entry
    return treffer[0]


def vanished_positions(previous_isins, current_isins):
    """Welche Papiere standen zuletzt im Depot und stehen jetzt nicht mehr?

    Das sind die verkauften. Sie verschwinden sonst wortlos aus der Liste --
    der letzte Datensatz bleibt als historischer Stand stehen, und nichts
    sagt, dass die Position aufgeloest wurde. Der Aufrufer schreibt fuer
    jede davon einen Stand mit Menge 0.

    Vergleich ueber die ISIN in Grossbuchstaben; leere Eintraege zaehlen
    nicht mit. Sortiert, damit zwei Laeufe dieselbe Reihenfolge ergeben.
    """
    vorher = {str(isin).strip().upper()
              for isin in (previous_isins or []) if str(isin or "").strip()}
    jetzt = {str(isin).strip().upper()
             for isin in (current_isins or []) if str(isin or "").strip()}
    return sorted(vorher - jetzt)


def bic_of(accounts):
    """Irgendeine BIC aus einer Kontenliste -- alle teilen die Bank.

    Gebraucht, weil python-fints das Laenderkennzeichen des Depots aus der
    BIC liest (``acc.bic[4:6]``), auch wo das Depot selbst keine hat. Zu
    kurze Werte zaehlen nicht: sie wuerden dort still zu einer leeren
    Zeichenkette und damit zu einem KeyError tief in der Bibliothek.

    :param accounts: Konten der Bibliothek (Objekte mit ``.bic``) oder Dicts
    :return: die BIC oder None
    """
    for konto in accounts or []:
        try:
            bic = konto.get("bic") if isinstance(konto, dict) else getattr(
                konto, "bic", None)
        except Exception:
            continue
        if bic and len(str(bic)) >= 6:
            return str(bic)
    return None
