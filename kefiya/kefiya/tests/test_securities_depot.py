# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Welches Konto der Bank das Depot ist -- und was sie dazu sagt.

Der Depotbestand kam monatelang nicht an, und niemand sah es: HKWPD ging
an das Konto des LOGINS, also an das Girokonto. Die Bank lehnte ab,
_optional_fetch las das korrekt als "bietet die Bank hier nicht an", und
`holdings` stand still auf {created: 0, updated: 0}. Kein Fehlerprotokoll,
kein einziger Datensatz.

Diese Regeln laufen ohne Bench und ohne python-fints, also werden sie hier
wirklich ausgefuehrt und nicht als Quelltext gelesen.
"""

import pathlib
import unittest

from kefiya.utils import securities_depot as sd

HIER = pathlib.Path(__file__).resolve()
WURZEL = HIER.parents[3]


class Operation:
    """Ein Schluessel aus FinTSOperations, so viel davon wie gebraucht wird."""

    def __init__(self, name, value):
        self.name = name
        self.value = value


HOLDINGS = Operation("GET_HOLDINGS", ("HKWPD",))
BALANCE = Operation("GET_BALANCE", ("HKSAL",))


def konto(number, holdings=None, **rest):
    entry = {"account_number": number}
    if holdings is not None:
        entry["supported_operations"] = {BALANCE: True, HOLDINGS: holdings}
    entry.update(rest)
    return entry


class TestDieNummerWirdVergleichbar(unittest.TestCase):

    def test_fuehrende_nullen_und_zeichen_fallen_weg(self):
        self.assertTrue(sd.same_account_number("0123456700", "123456700"))
        self.assertTrue(sd.same_account_number(" 1234 5670 0 ", "123456700"))
        self.assertTrue(sd.same_account_number("123-456-700", "123456700"))

    def test_verschiedene_nummern_bleiben_verschieden(self):
        self.assertFalse(sd.same_account_number("123456700", "123456701"))

    def test_nichts_ist_kein_treffer(self):
        self.assertFalse(sd.same_account_number("", "123456700"))
        self.assertFalse(sd.same_account_number(None, None))

    def test_eine_null_bleibt_eine_null(self):
        """lstrip('0') allein macht aus '000' eine leere Zeichenkette -- und
        die wuerde dann auf jede leere Nummer passen."""
        self.assertEqual("0", sd.normalize_account_number("000"))
        self.assertTrue(sd.same_account_number("0", "000"))
        self.assertFalse(sd.same_account_number("000", ""))


class TestWasDieBankZumDepotSagt(unittest.TestCase):

    def test_erlaubt_abgelehnt_unbekannt(self):
        self.assertIs(True, sd.holdings_allowed(konto("1", holdings=True)))
        self.assertIs(False, sd.holdings_allowed(konto("1", holdings=False)))
        self.assertIsNone(sd.holdings_allowed(konto("1")))

    def test_schweigen_ist_keine_ablehnung(self):
        """None ist nicht False. Ein Konto, ueber das die Bank nichts gesagt
        hat, wird gefragt -- die Antwort kostet eine Antwort, keinen
        Auftrag. Dieselbe Regel wie in account_capabilities."""
        self.assertIsNone(sd.holdings_allowed(None))
        self.assertIsNone(sd.holdings_allowed({}))
        self.assertIsNone(
            sd.holdings_allowed({"supported_operations": {BALANCE: True}}))

    def test_der_schluessel_wird_auch_am_kuerzel_erkannt(self):
        """Benennt die Bibliothek das Mitglied um, darf nicht still jedes
        Depot als 'nicht erlaubt' gelten."""
        umbenannt = Operation("PORTFOLIO", ("HKWPD",))
        self.assertIs(True, sd.holdings_allowed(
            {"supported_operations": {umbenannt: True}}))

    def test_es_wirft_nie(self):
        class Boeswillig:
            @property
            def name(self):
                raise RuntimeError("nein")

        self.assertIsNone(sd.holdings_allowed({"supported_operations": 5}))
        self.assertIsNone(sd.holdings_allowed("gar kein Eintrag"))
        # Ein Schluessel, der beim Lesen wirft, ist ein Schluessel weniger.
        self.assertIsNone(sd.holdings_allowed(
            {"supported_operations": {Boeswillig(): True}}))


class TestGiroUndDepotWerdenNichtVerwechselt(unittest.TestCase):
    """Die Falle, und sie ist keine theoretische: bei mindestens einer Bank
    traegt das Depot DIESELBE Nummer wie das Girokonto desselben Kunden --
    das Giro hat sie in seiner IBAN stehen. Wer nur auf die Nummer
    vergleicht, fragt wieder das Giro und bekommt wieder nichts."""

    def test_unter_gleichen_nummern_gewinnt_das_depot(self):
        konten = [
            konto("4711", holdings=False, product_name="Girokonto"),
            konto("4711", holdings=True, product_name="Depot"),
        ]
        treffer = sd.find_depot_entry(konten, "4711")
        self.assertEqual("Depot", treffer.get("product_name"))

    def test_auch_wenn_das_giro_zuerst_kommt_und_nichts_sagt(self):
        konten = [konto("4711", product_name="Girokonto"),
                  konto("4711", holdings=True, product_name="Depot")]
        self.assertEqual(
            "Depot", sd.find_depot_entry(konten, "4711").get("product_name"))

    def test_ohne_eindeutige_auskunft_entscheidet_die_bank(self):
        """Sagt keines der Konten etwas, wird das erste genommen und
        gefragt. Diese Funktion raet nicht."""
        konten = [konto("4711"), konto("4711")]
        self.assertIsNotNone(sd.find_depot_entry(konten, "4711"))

    def test_keine_passende_nummer_heisst_None(self):
        self.assertIsNone(sd.find_depot_entry([konto("4711")], "4712"))
        self.assertIsNone(sd.find_depot_entry([], "4711"))
        self.assertIsNone(sd.find_depot_entry(None, "4711"))


class TestVerkaufteWerdenBenannt(unittest.TestCase):

    def test_was_fehlt_gilt_als_verkauft(self):
        self.assertEqual(
            ["DE0000000001"],
            sd.vanished_positions(["DE0000000001", "DE0000000002"],
                                  ["DE0000000002"]))

    def test_schreibweise_und_leeres_zaehlen_nicht_mit(self):
        self.assertEqual(
            [], sd.vanished_positions([" de0000000002 ", "", None],
                                      ["DE0000000002"]))

    def test_neue_papiere_sind_nicht_verschwunden(self):
        self.assertEqual(
            [], sd.vanished_positions([], ["DE0000000003"]))

    def test_die_reihenfolge_ist_festgelegt(self):
        """Zwei Laeufe muessen dieselbe ergeben, sonst sieht jede Ablage
        anders aus."""
        self.assertEqual(
            ["DE0000000001", "DE0000000002"],
            sd.vanished_positions(["DE0000000002", "DE0000000001"], []))


class TestDieBicDesZugangs(unittest.TestCase):
    """python-fints liest das Laenderkennzeichen des Depots aus der BIC
    (``acc.bic[4:6]``), auch wo das Depot selbst keine hat."""

    class Konto:
        def __init__(self, bic):
            self.bic = bic

    def test_sie_wird_gefunden(self):
        self.assertEqual("ABCDDEFFXXX",
                         sd.bic_of([self.Konto("ABCDDEFFXXX")]))
        self.assertEqual("ABCDDEFF", sd.bic_of([{"bic": "ABCDDEFF"}]))

    def test_zu_kurze_werden_uebergangen(self):
        """Eine BIC unter sechs Zeichen wuerde in der Bibliothek still zu
        einer leeren Zeichenkette und dort zu einem KeyError."""
        self.assertEqual(
            "ABCDDEFF",
            sd.bic_of([self.Konto("ABCD"), self.Konto("ABCDDEFF")]))
        self.assertIsNone(sd.bic_of([self.Konto("ABCD")]))

    def test_ohne_konten_ist_sie_None(self):
        self.assertIsNone(sd.bic_of([]))
        self.assertIsNone(sd.bic_of(None))
        self.assertIsNone(sd.bic_of([self.Konto(None)]))


class TestDasModulBrauchtKeineBench(unittest.TestCase):
    """Sonst liefe keiner der Tests darueber, und die Regel, die entscheidet
    WELCHES Konto gefragt wird, waere wieder nur gegen eine echte Bank zu
    pruefen."""

    def test_es_importiert_nichts(self):
        quelle = (WURZEL / "kefiya/utils/securities_depot.py").read_text(
            encoding="utf-8")
        for zeile in quelle.split("\n"):
            self.assertFalse(zeile.startswith(("import ", "from ")), zeile)


if __name__ == "__main__":
    unittest.main()
