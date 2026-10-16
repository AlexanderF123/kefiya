# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Der Depotbestand wird beim DEPOT geholt, nicht beim Girokonto.

Was war: HKWPD ging an ``self._require_fints_account()`` -- das Konto des
Logins, also das Giro- oder Tagesgeldkonto, an dem der Zugang haengt. Keine
Bank laesst dafuer einen Depotbestand zu. Die Ablehnung las _optional_fetch
korrekt als "bietet die Bank hier nicht an", und ``holdings`` stand still
auf {created: 0, updated: 0}: kein Fehlerprotokoll, kein einziger
Datensatz, monatelang.

Gelesen als Quelltext, weil fints_controller, client und der Zeitplan
frappe am Dateikopf importieren und ausserhalb einer Bench nicht laden. Die
Regeln selbst stehen in securities_depot und werden in
test_securities_depot wirklich ausgefuehrt -- ein gruener Test hier heisst
"die Zeile steht da", nicht "der Code laeuft".
"""

import os
import re
import unittest


def _read(*parts):
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), *parts)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _block(source, header):
    """One def, by indentation."""
    # [ \t]* und nicht \s*: \s trifft auch Zeilenumbrueche, und die Suche
    # begann dann froehlich in einer Leerzeile und mass deren Einrueckung.
    hit = re.search(r"^([ \t]*)def %s\(" % re.escape(header), source, re.M)
    assert hit, header
    indent = len(hit.group(1))
    lines = source[hit.start():].split("\n")
    out = [lines[0]]
    for line in lines[1:]:
        if line.strip() and (len(line) - len(line.lstrip())) <= indent:
            break
        out.append(line)
    return "\n".join(out)


CONTROLLERS = ("utils/fints_controller.py", "utils/fints_controller_legacy.py")


class TestBeideControllerFragenDasDepot(unittest.TestCase):
    """Es gibt zwei Controller, und sie sind keine Verwandten. Stuende der
    Depotabruf in einem, muesste er im anderen ein zweites Mal stehen --
    und auf der TAN-losen Seite faellt es niemandem auf, wenn eine der
    beiden Fassungen still nichts mehr liefert."""

    def test_jeder_nimmt_depotnummern_entgegen(self):
        for pfad in CONTROLLERS:
            quelle = _read(*pfad.split("/"))
            self.assertIn("def get_fints_holdings(self, depots=None):",
                          quelle, pfad)

    def test_und_keiner_baut_die_mechanik_selbst(self):
        for pfad in CONTROLLERS:
            koerper = _block(_read(*pfad.split("/")), "get_fints_holdings")
            self.assertIn("fints_depot.fetch_holdings(", koerper, pfad)
            # Die alte Zeile, die den Depotbestand mit der Giro-IBAN
            # beschriftete, darf nicht zurueckkehren.
            self.assertNotIn(
                '"securities_account": self.kefiya_login.account_iban',
                koerper, pfad)

    def test_ohne_verknuepftes_depot_aendert_sich_nichts(self):
        """Ein Zugang ohne Wertpapierkonto fragt wie vorher sein eigenes
        Konto. Das ist keine Nachlaessigkeit, sondern die Zusage: wer kein
        Depot verknuepft hat, merkt von dieser Aenderung nichts."""
        for pfad in CONTROLLERS:
            koerper = _block(_read(*pfad.split("/")), "get_fints_holdings")
            self.assertIn("if not securities_depot.wanted_depots(depots):",
                          koerper, pfad)
            self.assertIn("fints_depot.holdings_of(", koerper, pfad)

    def test_alle_depots_in_einer_sitzung(self):
        """Eine Sitzung, beliebig viele Depots: keine zweite Anmeldung und
        keine zweite TAN. Die Schleife steht deshalb IN fetch_holdings und
        nicht um den Aufruf herum."""
        koerper = _block(_read("utils", "fints_controller.py"),
                         "get_fints_holdings")
        self.assertIn("with self.client_session():", koerper)
        self.assertLess(koerper.index("with self.client_session():"),
                        koerper.index("fints_depot.fetch_holdings("))
        mechanik = _block(_read("utils", "fints_depot.py"), "fetch_holdings")
        self.assertIn("for nummer in gewuenscht:", mechanik)


class TestDieBankEntscheidetJeDepot(unittest.TestCase):

    def test_nur_eine_ausdrueckliche_ablehnung_zaehlt(self):
        """Schweigen ist keine Ablehnung -- dieselbe Regel, nach der
        account_capabilities ein ungefragtes Konto durchlaesst. Sonst
        wuerde jedes Depot, ueber das die Bank nichts sagt, ungefragt
        uebersprungen."""
        koerper = _block(_read("utils", "fints_depot.py"), "fetch_holdings")
        self.assertIn(
            "if securities_depot.holdings_allowed(eintrag) is False:",
            koerper)

    def test_ein_depot_reisst_die_anderen_nicht_mit(self):
        koerper = _block(_read("utils", "fints_depot.py"), "fetch_holdings")
        self.assertIn("except Exception as exc:", koerper)
        self.assertIn("continue", koerper.split("except Exception as exc:")[1])

    def test_eine_tan_anforderung_wird_nicht_geparkt(self):
        """Eine Freigabe, die niemand gibt, haelt nur einen Dialog offen --
        und der Depotbestand ist eine Momentaufnahme, kein Auftrag."""
        koerper = _block(_read("utils", "fints_depot.py"), "holdings_of")
        self.assertIn("isinstance(antwort, NeedTANResponse)", koerper)
        self.assertIn("return None", koerper)
        # Auf den AUFRUF, nicht auf das Wort: der Docstring darueber
        # erklaert gerade, warum nicht geparkt wird, und ein Test, der
        # "park" sucht, findet die Erklaerung statt des Codes.
        self.assertNotIn("_park_tan_challenge(", koerper)
        self.assertNotIn("ask_for_tan(", koerper)


class TestDerAbrufFindetDieDepots(unittest.TestCase):

    def test_fetch_all_fragt_die_verknuepften_wertpapierkonten(self):
        quelle = _read("utils", "client.py")
        koerper = _block(quelle, "_fetch_holdings")
        self.assertIn("store_holdings(", koerper)
        self.assertIn("summary", koerper)
        self.assertIn("depots_of(kefiya_login)", _block(quelle,
                                                        "store_holdings"))

    def test_die_depots_haengen_am_login(self):
        koerper = _block(_read("utils", "client.py"), "depots_of")
        self.assertIn('"Kefiya Securities Account"', koerper)
        self.assertIn('filters={"kefiya_login": kefiya_login}', koerper)

    def test_eine_ablehnung_ist_kein_fehler(self):
        """Sie gehoert in unsupported, nicht ins Fehlerprotokoll -- sonst
        meldet ein Sammelabruf fuer jedes Konto ohne Depot eine Stoerung."""
        koerper = _block(_read("utils", "client.py"), "store_holdings")
        self.assertIn('summary.setdefault("unsupported", []).append'
                      '("holdings")', koerper)
        self.assertNotIn("log_error", koerper)

    def test_aber_nur_wenn_wirklich_nichts_ankam(self):
        """Kam von einem Depot ein Bestand und von einem anderen nicht,
        waere 'bietet die Bank nicht an' das Gegenteil der Wahrheit."""
        koerper = _block(_read("utils", "client.py"), "store_holdings")
        self.assertIn("if summary is not None and not bestand:", koerper)


class TestDerZeitplanNimmtDasDepotMit(unittest.TestCase):
    """Der Zeitplan holte nur Umsaetze; fetch_all mit Saldo und Depot haengt
    am Knopf. Ein Depotstand, der nur erscheint, wenn jemand drueckt, ist
    kein Depotstand."""

    def setUp(self):
        self.py = _read("kefiya", "doctype", "kefiya_schedule",
                        "kefiya_schedule.py")

    def test_er_laeuft_nach_dem_umsatzabruf(self):
        lauf = _block(self.py, "scheduled_import_fints_payments")
        self.assertIn("_fetch_depot_snapshot(login_name)", lauf)
        self.assertLess(lauf.index("_record_fetch_attempt(login_name)"),
                        lauf.index("_fetch_depot_snapshot(login_name)"))

    def test_erst_nach_dem_commit_der_umsaetze(self):
        """Ein Fehler in der Datenbank macht die laufende Transaktion
        unbrauchbar. Davor liegend haette die Momentaufnahme die soeben
        gebuchten Umsaetze mitnehmen koennen -- genau das, was sie nicht
        darf."""
        lauf = _block(self.py, "scheduled_import_fints_payments")
        self.assertLess(lauf.index("frappe.db.commit()"),
                        lauf.index("_fetch_depot_snapshot(login_name)"))

    def test_und_kostet_die_umsaetze_nichts(self):
        """Die Momentaufnahme ist nachrangig. Was hier schiefgeht, darf die
        soeben gebuchten Umsaetze nicht mitnehmen."""
        koerper = _block(self.py, "_fetch_depot_snapshot")
        self.assertIn("except TanInteractionRequired:", koerper)
        self.assertIn("except Exception:", koerper)
        self.assertLess(koerper.index("except TanInteractionRequired:"),
                        koerper.index("except Exception:"))

    def test_ohne_depot_wird_die_bank_nicht_angefasst(self):
        koerper = _block(self.py, "_fetch_depot_snapshot")
        self.assertIn("if not depots_of(login_name):", koerper)
        self.assertLess(koerper.index("if not depots_of(login_name):"),
                        koerper.index("store_holdings(login_name)"))

    def test_er_waehlt_den_controller_nicht_selbst(self):
        """Welcher Controller gilt, haengt an einer Einstellung. Die Wahl
        steht in client._get_fints_controller und gehoert nicht ein
        zweites Mal in den Zeitplan -- und ein privater Name aus einem
        fremden Modul schon gar nicht."""
        koerper = _block(self.py, "_fetch_depot_snapshot")
        self.assertNotIn("_get_fints_controller", koerper)
        self.assertNotIn("FinTSControllerLegacy", koerper)


class TestVerkauftePositionenVerschwindenNichtWortlos(unittest.TestCase):

    def setUp(self):
        self.py = _read("utils", "securities.py")

    def test_sie_werden_mit_menge_null_fortgeschrieben(self):
        koerper = _block(self.py, "_close_vanished_positions")
        self.assertIn("securities_depot.vanished_positions(", koerper)
        self.assertIn('"quantity": 0.0', koerper)
        self.assertIn('"market_value": 0.0', koerper)

    def test_auch_der_kurs_steht_auf_null(self):
        """Ein stehengelassener Kurs liesse sich als aktueller lesen."""
        koerper = _block(self.py, "_close_vanished_positions")
        self.assertIn('"price": 0.0', koerper)

    def test_verglichen_wird_gegen_den_letzten_stand_davor(self):
        """Nicht gegen alles, was je da war -- sonst wuerde jedes einmal
        verkaufte Papier bei jedem Abruf erneut nullgestellt."""
        koerper = _block(self.py, "_close_vanished_positions")
        self.assertIn('"valuation_date": ("<", stand["valuation_date"])',
                      koerper)
        self.assertIn('order_by="valuation_date desc"', koerper)

    def test_ein_nullstand_wird_nicht_zweimal_geschrieben(self):
        koerper = _block(self.py, "_close_vanished_positions")
        self.assertIn('if flt(zeile.get("quantity")) == 0:', koerper)

    def test_es_wirft_nie(self):
        """Die Momentaufnahme selbst ist zu diesem Zeitpunkt schon
        geschrieben."""
        koerper = _block(self.py, "_close_vanished_positions")
        self.assertIn("except Exception:", koerper)
        self.assertIn("return 0", koerper)

    def test_die_historie_bleibt_die_identitaet(self):
        """Ein Datensatz je Depot, ISIN und Bewertungstag."""
        koerper = _block(self.py, "compute_holding_key")
        self.assertIn("valuation_date", koerper)

    def test_das_ergebnis_nennt_jedes_depot(self):
        koerper = _block(self.py, "refresh_holdings")
        for schluessel in ('"created"', '"updated"', '"closed"', '"accounts"',
                           '"positions"', '"market_value_total"'):
            self.assertIn(schluessel, koerper)


if __name__ == "__main__":
    unittest.main()
