# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Das Institut des Zahlers in einer pain.001 ohne BIC.

sepaxml 2.7.0 schreibt ohne BIC ein leeres <FinInstnId/>. Das ISO-Schema
laesst das durch, das Schema der Deutschen Kreditwirtschaft nicht: dort
steht BIC oder Othr/Id NOTPROVIDED. Die Sparkasse nahm den Auftrag an und
lehnte ihn bei der Ausfuehrung ab -- "9010 Der Auftrag wurde nicht
ausgefuehrt", nach der Freigabe in der App, viermal.

Die Regel laeuft hier ohne Bench. Dass build_pain001 sie aufruft, steht im
Quelltext und wird als Quelltext geprueft.
"""

import os
import unittest

from kefiya.utils.pain_iban_only import (NOT_PROVIDED, debtor_agent_is_empty,
                                         debtor_agent_not_provided)

HIER = os.path.dirname(os.path.abspath(__file__))
WURZEL = os.path.dirname(os.path.dirname(HIER))

OHNE_BIC = ('<PmtInf><Dbtr><Nm>Brilu</Nm></Dbtr><DbtrAcct><Id><IBAN>DE27</IBAN>'
            '</Id></DbtrAcct><DbtrAgt><FinInstnId /></DbtrAgt><ChrgBr>SLEV'
            '</ChrgBr></PmtInf>')
MIT_BIC = ('<DbtrAgt><FinInstnId><BIC>SOLADES1HDB</BIC></FinInstnId>'
           '</DbtrAgt>')
IBAN_ONLY = ('<DbtrAgt><FinInstnId><Othr><Id>NOTPROVIDED</Id></Othr>'
             '</FinInstnId></DbtrAgt>')


class TestDasLeereInstitutWirdBenannt(unittest.TestCase):

    def test_leer_wird_notprovided(self):
        aus = debtor_agent_not_provided(OHNE_BIC)
        self.assertIn(IBAN_ONLY, aus)
        self.assertNotIn("<FinInstnId />", aus)
        # Und sonst nichts angefasst.
        self.assertIn("<IBAN>DE27</IBAN>", aus)
        self.assertIn("<ChrgBr>SLEV</ChrgBr>", aus)

    def test_auch_die_lange_schreibweise(self):
        aus = debtor_agent_not_provided(
            "<DbtrAgt><FinInstnId></FinInstnId></DbtrAgt>")
        self.assertEqual(aus, IBAN_ONLY)

    def test_eine_bic_bleibt(self):
        self.assertEqual(debtor_agent_not_provided(MIT_BIC), MIT_BIC)

    def test_notprovided_bleibt(self):
        self.assertEqual(debtor_agent_not_provided(IBAN_ONLY), IBAN_ONLY)

    def test_ohne_element_nichts(self):
        self.assertEqual(debtor_agent_not_provided("<Document/>"),
                         "<Document/>")
        self.assertEqual(debtor_agent_not_provided(""), "")
        self.assertIsNone(debtor_agent_not_provided(None))

    def test_das_wort_ist_das_der_dk(self):
        self.assertEqual(NOT_PROVIDED, "NOTPROVIDED")

    def test_die_frage_danach(self):
        self.assertTrue(debtor_agent_is_empty(OHNE_BIC))
        self.assertFalse(debtor_agent_is_empty(MIT_BIC))
        self.assertFalse(debtor_agent_is_empty(IBAN_ONLY))
        self.assertFalse(debtor_agent_is_empty(""))


class TestBuildPain001RuftEsAuf(unittest.TestCase):

    def test_nach_dem_export_vor_der_rueckgabe(self):
        pfad = os.path.join(WURZEL, "kefiya", "doctype", "kefiya_transfer",
                            "kefiya_transfer.py")
        with open(pfad, encoding="utf-8") as handle:
            quelle = handle.read()
        koerper = quelle[quelle.index("def build_pain001_for("):]
        koerper = koerper[:koerper.index("\ndef ", 10)] \
            if "\ndef " in koerper[10:] else koerper
        self.assertLess(
            koerper.index("sepa.export(validate=True)"),
            koerper.index("pain_iban_only.debtor_agent_not_provided(xml)"))
        self.assertLess(
            koerper.index("pain_iban_only.debtor_agent_not_provided(xml)"),
            koerper.index("return xml, control_sum / 100.0, len(rows)"))
