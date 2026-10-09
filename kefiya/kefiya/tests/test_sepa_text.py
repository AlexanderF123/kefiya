# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Ein Eurozeichen hat einen Auftrag dreimal scheitern lassen.

Die Sparkasse Heidelberg lehnte KEF-TRF-2026-00015 am 08. und 09.10.2026
dreimal ab, jedes Mal erst nach der Freigabe in der Banking-App::

    9050 Die Nachricht enthaelt Fehler.
    9010 Der Auftrag wurde nicht ausgefuehrt.

9050 beanstandet die Nachricht, nicht die Auftragsdaten. Die Nachricht war
gueltiges ISO-XML -- sepa.export(validate=True) hatte sie gegen das Schema
geprueft --, denn Max140Text laesst jedes Unicode-Zeichen zu. Die Regeln der
Deutschen Kreditwirtschaft nicht.

Korrigiert wird bei der ERFASSUNG, nicht beim Senden: dort stuende die
Aenderung zwischen Freigabe und Bank. Und gemeldet wird sie -- automatisch
heisst nicht stillschweigend.
"""

import pathlib
import unittest

from kefiya.utils import sepa_text

HIER = pathlib.Path(__file__).resolve()
WURZEL = HIER.parents[3]
TRANSFER = (WURZEL / "kefiya/kefiya/doctype/kefiya_transfer"
                     "/kefiya_transfer.py")

#: Der Verwendungszweck, den die Bank dreimal abgelehnt hat.
ABGELEHNT = "1 TZ. Kaution abzügl. 400€ für BK25/BK26"

#: Echte Texte aus den 14 Auftraegen dieser Instanz. Die Umlaute bleiben
#: stehen -- die Bank hat sie dreizehnmal ausgefuehrt.
GELAUFEN = {
    "Reisekosten BT-0001 Alexander Finkeißen":
        "Reisekosten BT-0001 Alexander Finkeißen",
    "Teilrückzahlung Darlehen AF an Sofienstraße GmbH u Co KG":
        "Teilrückzahlung Darlehen AF an Sofienstraße GmbH u Co KG",
    "1. TZ Kaution, abzüglich Mietschulden 24,25,26":
        "1. TZ Kaution, abzüglich Mietschulden 24,25,26",
    # Der eine mit einem Zeilenumbruch -- die Volksbank hat ihn geschluckt,
    # richtig wird er davon nicht: in 60.000 Buchungen kommt keiner vor.
    "St.-Nr.: 143-123-91024\nBauleistungssteuer\nSeptember 2026":
        "St.-Nr.: 143-123-91024 Bauleistungssteuer September 2026",
}


class TestDasEurozeichen(unittest.TestCase):
    """Null von 60.000 Buchungen -- und der eine Auftrag, der es trug, ist
    der eine, den die Bank abgelehnt hat."""

    def test_es_wird_EUR(self):
        self.assertEqual(
            sepa_text.clean(ABGELEHNT),
            "1 TZ. Kaution abzügl. 400EUR für BK25/BK26")

    def test_und_sonst_bleibt_der_text_wie_er_war(self):
        """Nur das Eurozeichen war das Problem. Die Umlaute im selben Satz
        hat dieselbe Bank auf demselben Konto zweimal ausgefuehrt."""
        self.assertIn("abzügl.", sepa_text.clean(ABGELEHNT))
        self.assertIn("für", sepa_text.clean(ABGELEHNT))

    def test_und_der_text_ist_danach_sendbar(self):
        self.assertEqual(sepa_text.unsendable(sepa_text.clean(ABGELEHNT)), [])

    def test_die_meldung_nennt_es(self):
        self.assertEqual(sepa_text.complaint(ABGELEHNT), "€ -> EUR")


class TestWasDieMessungErlaubt(unittest.TestCase):
    """Beide Richtungen, tausendfach. Ein EINGEHENDER Verwendungszweck ist
    der Zeuge, den niemand herbeigeredet hat: die Bank eines Fremden hat ihn
    durch das Netz geschickt und unsere Bank hat ihn zugestellt."""

    def test_umlaute_und_scharfes_s(self):
        text = "äöüÄÖÜß"
        self.assertEqual(sepa_text.clean(text), text)
        self.assertEqual(sepa_text.unsendable(text), [])

    def test_kaufmanns_und(self):
        """1.136-mal allein in Namen von Gegenseiten."""
        self.assertEqual(sepa_text.clean("Müller & Söhne GmbH"),
                         "Müller & Söhne GmbH")

    def test_prozentzeichen(self):
        self.assertEqual(sepa_text.clean("Mietminderung 15 %"),
                         "Mietminderung 15 %")


class TestWoDerZeugeDuennIst(unittest.TestCase):
    """* = _ > sind aufgetaucht, aber nur in unseren eigenen abgehenden
    Texten und dreizehn-, zwoelf-, zwei-, zweimal. Hier sind die beiden
    Fehler nicht gleich teuer: zu Unrecht durchgelassen kostet einen
    abgelehnten Auftrag nach verbrauchter TAN, zu Unrecht ersetzt einen
    leicht veraenderten Verwendungszweck. Der billigere Fehler gewinnt."""

    def test_sie_werden_ersetzt(self):
        for zeichen in "*=_>":
            self.assertNotIn(zeichen, sepa_text.clean("a" + zeichen + "b"),
                             zeichen)


class TestDieEchtenTexte(unittest.TestCase):
    """Die 14 Auftraege dieser Instanz, Zeichen fuer Zeichen."""

    def test_jeder_wird_was_er_werden_soll(self):
        for vorher, nachher in GELAUFEN.items():
            self.assertEqual(sepa_text.clean(vorher), nachher, vorher)

    def test_und_ist_danach_sendbar(self):
        for vorher in GELAUFEN:
            self.assertEqual(
                sepa_text.unsendable(sepa_text.clean(vorher)), [], vorher)


class TestZweimalIstWieEinmal(unittest.TestCase):
    """Der Auftrag wird bei jedem Speichern geprueft. Ein Text, der sich
    dabei jedes Mal weiter veraendert, waere nach dem dritten Speichern
    nicht mehr der, den jemand freigegeben hat."""

    def test_idempotent(self):
        for text in list(GELAUFEN) + [ABGELEHNT,
                                      "Miete – Oktober „Wohnung“",
                                      "50 % § 535 BGB",
                                      "a\n\n\tb", "   ", ""]:
            einmal = sepa_text.clean(text)
            self.assertEqual(sepa_text.clean(einmal), einmal, repr(text))

    def test_und_changed_sagt_wann_etwas_zu_tun_ist(self):
        self.assertTrue(sepa_text.changed(ABGELEHNT))
        self.assertFalse(sepa_text.changed(sepa_text.clean(ABGELEHNT)))


class TestNotfallsEinLeerzeichen(unittest.TestCase):
    """So gewuenscht: was keinen Namen hat, wird ein Leerzeichen. Nicht
    weggelassen -- ein fehlendes Zeichen faellt niemandem auf, eine Luecke
    schon."""

    def test_ein_zeichen_ohne_namen(self):
        self.assertEqual(sepa_text.clean("Miete ☃ Oktober"),
                         "Miete Oktober")

    def test_steuerzeichen(self):
        self.assertEqual(sepa_text.clean("a\nb\tc\rd"), "a b c d")

    def test_die_meldung_nennt_es_beim_namen(self):
        """Ein unsichtbares Zeichen in Anfuehrungszeichen zu zeigen hilft
        niemandem."""
        self.assertIn("Zeilenumbruch -> Leerzeichen",
                      sepa_text.complaint("a\nb"))

    def test_und_akzente_bekommen_den_buchstaben(self):
        """Naeher am Gemeinten als ein Leerzeichen -- und in 60.000
        Buchungen kommt kein einziger Akzent vor."""
        self.assertEqual(sepa_text.clean("Café Niño"), "Cafe Nino")


class TestKeineLuecken(unittest.TestCase):

    def test_mehrfache_leerzeichen_fallen_zusammen(self):
        self.assertEqual(sepa_text.clean("a  ☃  b"), "a b")

    def test_und_die_raender_werden_glatt(self):
        self.assertEqual(sepa_text.clean("  Miete  "), "Miete")


class TestDerGrundzeichensatz(unittest.TestCase):
    """a-z A-Z 0-9 und / - ? : ( ) . , ' + und das Leerzeichen."""

    def test_was_erlaubt_ist_bleibt_unberuehrt(self):
        text = ("abcdefghijklmnopqrstuvwxyz"
                "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                "0123456789 /-?:().,'+")
        self.assertEqual(sepa_text.clean(text), text)

    def test_und_nichts_davon_wird_beanstandet(self):
        self.assertEqual(sepa_text.unsendable("Rg-Nr. 12/3 (A,B): 4+5 'x'?"),
                         [])

    def test_auch_nicht_mit_umlauten(self):
        self.assertEqual(
            sepa_text.unsendable("Miete für Oktober, Straße 5"), [])


class TestNichtsGesagtIstNichtsZuTun(unittest.TestCase):

    def test_leer(self):
        for wert in ("", None):
            self.assertEqual(sepa_text.clean(wert), "")
            self.assertEqual(sepa_text.unsendable(wert), [])
            self.assertEqual(sepa_text.complaint(wert), "")
            self.assertFalse(sepa_text.changed(wert))

    def test_jedes_zeichen_nur_einmal_in_der_meldung(self):
        self.assertEqual(len(sepa_text.unsendable("1€ 2€ 3€")), 1)


class TestKorrigiertWirdBeiDerErfassung(unittest.TestCase):
    """Nicht beim Senden: dort laege die Aenderung zwischen Freigabe und
    Bank. Im Entwurf steht der Text vor den Augen dessen, der ihn
    freigibt."""

    def setUp(self):
        self.quelle = TRANSFER.read_text(encoding="utf-8")
        self.validate = self.quelle[
            self.quelle.index("    def validate(self):"):
            self.quelle.index("def requested_execution_date")]

    def test_in_validate(self):
        self.assertIn("sepa_text.clean(vorher)", self.validate)

    def test_beide_texte(self):
        self.assertIn('for feld in ("purpose", "recipient_name"):',
                      self.validate)

    def test_vor_dem_kuerzen_auf_140(self):
        """Aus einem Zeichen koennen drei werden ("EUR"); abgeschnitten wird,
        was am Ende zu lang ist, nicht vorher."""
        self.assertLess(self.validate.index("sepa_text.clean(vorher)"),
                        self.validate.index("row.purpose[:140]"))

    def test_und_es_wird_gemeldet(self):
        """Automatisch heisst nicht stillschweigend."""
        self.assertIn("corrections.append(", self.validate)
        self.assertIn("frappe.msgprint(", self.validate)
        self.assertIn("sepa_text.complaint(vorher)", self.validate)


class TestDerSendewegIstNurNochDasNetz(unittest.TestCase):
    """Nach der Korrektur bei der Erfassung kann hier nichts mehr ankommen,
    was die Bank nicht traegt -- es sei denn, etwas hat validate umgangen.
    Dann wird abgelehnt und NICHT still korrigiert: eine Aenderung zwischen
    Freigabe und Bank ist genau die, die niemand mehr liest."""

    def setUp(self):
        quelle = TRANSFER.read_text(encoding="utf-8")
        self.bauen = quelle[quelle.index("def build_pain001_for"):]

    def test_geprueft_wird_vor_dem_senden(self):
        self.assertIn("sepa_text.complaint(", self.bauen)
        self.assertLess(self.bauen.index("sepa_text.complaint("),
                        self.bauen.index("sepa.add_payment(payment)"))

    def test_und_abgelehnt(self):
        stelle = self.bauen.index("sepa_text.complaint(")
        herum = self.bauen[stelle:stelle + 900]
        self.assertIn("frappe.throw(", herum)
        self.assertIn("was NOT sent", herum)

    def test_aber_nichts_wird_hier_korrigiert(self):
        self.assertNotIn("sepa_text.clean", self.bauen)


class TestDasModulBrauchtKeineBench(unittest.TestCase):

    def test_es_importiert_nichts(self):
        quelle = (WURZEL / "kefiya/utils/sepa_text.py").read_text(
            encoding="utf-8")
        for zeile in quelle.split("\n"):
            self.assertFalse(zeile.startswith(("import ", "from ")), zeile)


if __name__ == "__main__":
    unittest.main()
