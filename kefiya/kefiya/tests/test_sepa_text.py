# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Ein Eurozeichen hat einen Auftrag dreimal scheitern lassen.

Die Sparkasse Heidelberg lehnte KEF-TRF-2026-00015 am 08. und 09.10.2026
dreimal ab, jedes Mal erst nach der Freigabe in der Banking-App::

    9050 Die Nachricht enthaelt Fehler.
    9010 Der Auftrag wurde nicht ausgefuehrt.

9050 beanstandet die Nachricht, nicht die Auftragsdaten. Die Nachricht war
gueltiges ISO-XML -- sepa.export(validate=True) hatte sie gegen das Schema
geprueft --, denn Max140Text laesst jedes Unicode-Zeichen zu.

Die Messung, auf der die Regel beruht: von 14 Auftraegen dieser Instanz
trugen 13 Zeichen, die die DK-Liste streng genommen nicht kennt ("ue",
"ss"), und alle 13 hat die Bank ausgefuehrt -- zwei davon auf demselben
Konto wie der abgelehnte. Einer trug ein Eurozeichen. Genau der eine wurde
abgelehnt.

Deshalb verbietet dieses Modul keine Umlaute. Das waere eine Vermutung
gegen die eigene Messung.
"""

import pathlib
import unittest

from kefiya.utils import sepa_text

HIER = pathlib.Path(__file__).resolve()
WURZEL = HIER.parents[3]

#: Der Verwendungszweck, der dreimal abgelehnt wurde.
ABGELEHNT = "1 TZ. Kaution abzügl. 400€ für BK25/BK26"

#: Zwei, die dieselbe Bank auf demselben Konto ausgefuehrt hat.
AUSGEFUEHRT = (
    "1. TZ Kaution, abzüglich Mietschulden 24,25,26",
    "Reisekosten BT-0001 Alexander Finkeißen",
)


class TestDasEurozeichen(unittest.TestCase):

    def test_es_wird_gefunden(self):
        treffer = sepa_text.unsendable(ABGELEHNT)
        self.assertEqual([x["char"] for x in treffer], ["€"])

    def test_und_bekommt_einen_namen_den_die_bank_tragen_kann(self):
        self.assertEqual(
            sepa_text.unsendable(ABGELEHNT)[0]["replacement"], "EUR")

    def test_die_beanstandung_nennt_beides(self):
        satz = sepa_text.complaint(ABGELEHNT)
        self.assertIn("€", satz)
        self.assertIn("EUR", satz)

    def test_der_vorschlag_ist_sendbar(self):
        vorschlag = sepa_text.repaired(ABGELEHNT)
        self.assertEqual(sepa_text.unsendable(vorschlag), [])
        self.assertIn("400EUR", vorschlag)


class TestUmlauteBleibenErlaubt(unittest.TestCase):
    """Die Bank hat sie vierzehnmal ausgefuehrt. Sie zu verbieten hiesse,
    gegen die eigene Messung zu entscheiden -- und dem Nutzer dreizehn
    Auftraege zu verbieten, die gelaufen sind."""

    def test_was_durchging_geht_weiter_durch(self):
        for zweck in AUSGEFUEHRT:
            self.assertEqual(sepa_text.unsendable(zweck), [], zweck)
            self.assertEqual(sepa_text.complaint(zweck), "")

    def test_und_der_vorschlag_laesst_sie_stehen(self):
        self.assertEqual(sepa_text.repaired("Finkeißen für Müller"),
                         "Finkeißen für Müller")


class TestSteuerzeichenSindKeinText(unittest.TestCase):
    """Ein Zeilenumbruch im Verwendungszweck ist kein Text, den ein Ustrd
    tragen kann. Eine Bank hat einen einmal geschluckt; das macht ihn nicht
    richtig."""

    def test_ein_zeilenumbruch(self):
        treffer = sepa_text.unsendable("St.-Nr.: 143\nBauleistungssteuer")
        self.assertEqual([x["name"] for x in treffer], ["Zeilenumbruch"])

    def test_er_wird_zum_leerzeichen(self):
        self.assertEqual(sepa_text.repaired("a\nb"), "a b")

    def test_und_die_meldung_nennt_ihn_beim_namen(self):
        """Ein unsichtbares Zeichen in Anfuehrungszeichen zu zeigen hilft
        niemandem."""
        self.assertIn("Zeilenumbruch",
                      sepa_text.complaint("St.-Nr.: 143\nBauleistungssteuer"))


class TestWeitereZeichenAusOfficeTexten(unittest.TestCase):

    def test_halbgeviertstrich(self):
        self.assertEqual(sepa_text.repaired("Miete – Oktober"),
                         "Miete - Oktober")

    def test_typografische_anfuehrungszeichen(self):
        self.assertEqual(sepa_text.repaired("„Miete“"), '"Miete"')

    def test_geschuetztes_leerzeichen(self):
        self.assertEqual(sepa_text.repaired("400 EUR"), "400 EUR")


class TestNichtsGesagtIstNichtsZuBeanstanden(unittest.TestCase):

    def test_leer(self):
        for wert in ("", None):
            self.assertEqual(sepa_text.unsendable(wert), [])
            self.assertEqual(sepa_text.complaint(wert), "")
            self.assertEqual(sepa_text.repaired(wert), "")

    def test_jedes_zeichen_nur_einmal(self):
        treffer = sepa_text.unsendable("1€ 2€ 3€")
        self.assertEqual(len(treffer), 1)


class TestAbgelehntUndNichtUmgeschrieben(unittest.TestCase):
    """Dieselbe Haltung wie beim vergangenen Ausfuehrungsdatum und bei
    refuse_paying_yourself: die Bank lehnt es selbst ab, aber erst nachdem
    eine TAN darauf verbraucht ist -- und aus einem Zeichen, das jemand
    freigegeben hat, wird nicht stillschweigend ein anderes."""

    def setUp(self):
        self.quelle = (WURZEL / "kefiya/kefiya/doctype/kefiya_transfer"
                                "/kefiya_transfer.py").read_text(
            encoding="utf-8")

    def test_geprueft_wird_vor_dem_senden(self):
        anfang = self.quelle.index("def build_pain001_for")
        block = self.quelle[anfang:]
        self.assertIn("sepa_text.complaint(", block)
        self.assertLess(block.index("sepa_text.complaint("),
                        block.index("sepa.add_payment(payment)"))

    def test_und_der_auftrag_wird_abgelehnt(self):
        anfang = self.quelle.index("def build_pain001_for")
        block = self.quelle[anfang:]
        stelle = block.index("sepa_text.complaint(")
        herum = block[stelle:stelle + 900]
        self.assertIn("frappe.throw(", herum)
        self.assertIn("was NOT sent", herum)

    def test_der_vorschlag_steht_in_der_meldung(self):
        anfang = self.quelle.index("def build_pain001_for")
        block = self.quelle[anfang:]
        stelle = block.index("sepa_text.complaint(")
        self.assertIn("sepa_text.repaired(", block[stelle:stelle + 900])

    def test_aber_nichts_wird_still_ersetzt(self):
        """repaired() darf nur in die Meldung, nicht in die Nachricht."""
        anfang = self.quelle.index("payment = {")
        ende = self.quelle.index("sepa.add_payment(payment)")
        self.assertNotIn("sepa_text.repaired", self.quelle[anfang:ende])

    def test_der_empfaengername_wird_mitgeprueft(self):
        anfang = self.quelle.index("def build_pain001_for")
        block = self.quelle[anfang:]
        stelle = block.index("sepa_text.complaint(")
        self.assertIn("recipient_name", block[max(0, stelle - 400):stelle])


class TestDasModulBrauchtKeineBench(unittest.TestCase):

    def test_es_importiert_nichts(self):
        quelle = (WURZEL / "kefiya/utils/sepa_text.py").read_text(
            encoding="utf-8")
        for zeile in quelle.split("\n"):
            self.assertFalse(zeile.startswith(("import ", "from ")), zeile)


if __name__ == "__main__":
    unittest.main()
