# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""A camt.053 file is read the way the bank meant it.

The accounts here are invented: IBANs with valid check digits on clearing
numbers chosen for being unused, names that belong to nobody. What is real is
the structure -- the elements and their nesting as ISO 20022 defines them for
the message versions named in each test.
"""

import os
import re
import unittest

from kefiya.utils import camt_statement as camt

OWN = "CH8599999000012345678"
OTHER_OWN = "CH8888888000087654321"
PAYER = "DE89999999990001111111"
PAYEE = "DE50777777770007654321"


def _statement(entries, version="08", iban=OWN, currency="CHF",
               extra_statements=""):
    return """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.{v}">
 <BkToCstmrStmt>
  <GrpHdr><MsgId>MSG-1</MsgId><CreDtTm>2026-10-30T06:00:00</CreDtTm></GrpHdr>
  <Stmt>
   <Id>STMT-1</Id>
   <Acct><Id><IBAN>{iban}</IBAN></Id><Ccy>{ccy}</Ccy></Acct>
   {entries}
  </Stmt>
  {extra}
 </BkToCstmrStmt>
</Document>""".format(v=version, iban=iban, ccy=currency, entries=entries,
                      extra=extra_statements).encode("utf-8")


def _entry(amount="100.00", ccy="CHF", ind="CRDT", status="BOOK",
           booked="2026-10-29", value="2026-10-31", ref="REF-1",
           details="", reversal="", v8=True):
    sts = ("<Sts><Cd>{0}</Cd></Sts>" if v8 else "<Sts>{0}</Sts>").format(
        status)
    return """<Ntry>
     <Amt Ccy="{ccy}">{amount}</Amt><CdtDbtInd>{ind}</CdtDbtInd>{rev}
     {sts}
     <BookgDt><Dt>{booked}</Dt></BookgDt><ValDt><Dt>{value}</Dt></ValDt>
     {ref}
     <AddtlNtryInf>Gutschrift</AddtlNtryInf>
     {details}
    </Ntry>""".format(
        ccy=ccy, amount=amount, ind=ind, sts=sts, booked=booked, value=value,
        ref="<AcctSvcRef>{0}</AcctSvcRef>".format(ref) if ref else "",
        details=details,
        rev="<RvslInd>true</RvslInd>" if reversal else "")


def _tx(name="Erika Beispiel", iban=PAYER, side="Dbtr", purpose="Rechnung 1",
        v8=True, qr=None, amount_details=""):
    party = ("<{s}><Pty><Nm>{n}</Nm></Pty></{s}>" if v8
             else "<{s}><Nm>{n}</Nm></{s}>").format(s=side, n=name)
    strd = ("<Strd><CdtrRefInf><Ref>{0}</Ref></CdtrRefInf></Strd>".format(qr)
            if qr else "")
    return """<TxDtls>
       <Refs><EndToEndId>E2E</EndToEndId></Refs>
       {amtdtls}
       <RltdPties>{party}<{s}Acct><Id><IBAN>{iban}</IBAN></Id></{s}Acct>
       </RltdPties>
       <RmtInf><Ustrd>{purpose}</Ustrd>{strd}</RmtInf>
      </TxDtls>""".format(party=party, s=side, iban=iban, purpose=purpose,
                          strd=strd, amtdtls=amount_details)


def _details(*txs):
    return "<NtryDtls>{0}</NtryDtls>".format("".join(txs))


class TestTheFileIsRecognised(unittest.TestCase):

    def test_the_version_is_read_from_the_namespace(self):
        self.assertEqual(camt.message_kind(_statement("")), ("053", "08"))
        self.assertEqual(camt.message_kind(_statement("", version="02")),
                         ("053", "02"))

    def test_a_csv_is_not_camt(self):
        self.assertFalse(camt.looks_like_camt(b"Datum;Betrag\n01.10.2026;5"))

    def test_an_intraday_report_is_not_booked_from(self):
        """camt.052 repeats what the 053 will say; booking both doubles it."""
        raw = _statement("").replace(b"camt.053.001.08", b"camt.052.001.08")
        with self.assertRaises(camt.CamtError):
            camt.read_statement(raw)

    def test_an_unknown_version_is_refused_not_attempted(self):
        with self.assertRaises(camt.CamtError):
            camt.read_statement(_statement("", version="99"))

    def test_every_promised_version_is_accepted(self):
        for version in ("02", "04", "08", "11"):
            entries, notes = camt.read_statement(
                _statement(_entry(), version=version))
            self.assertEqual(len(entries), 1, version)
            self.assertEqual(notes["version"], "camt.053.001." + version)

    def test_a_document_type_definition_is_refused(self):
        """Entity expansion is an attack on the parser, not a statement."""
        raw = _statement(_entry()).replace(
            b"<Document", b'<!DOCTYPE x [<!ENTITY a "aaaa">]><Document', 1)
        with self.assertRaises(camt.CamtError):
            camt.read_statement(raw)

    def test_a_byte_order_mark_does_not_hide_the_document(self):
        entries, _ = camt.read_statement(b"\xef\xbb\xbf" + _statement(
            _entry()))
        self.assertEqual(len(entries), 1)


class TestOnlyWhatTheBankBooked(unittest.TestCase):

    def test_pending_and_information_entries_are_counted_not_read(self):
        entries, notes = camt.read_statement(_statement(
            _entry(ref="A") + _entry(status="PDNG", ref="B")
            + _entry(status="INFO", ref="C")))
        self.assertEqual([e["reference"] for e in entries], ["A"])
        self.assertEqual(notes["pending"], 2)

    def test_the_status_as_plain_text_in_older_versions(self):
        entries, notes = camt.read_statement(_statement(
            _entry(v8=False) + _entry(status="PDNG", ref="B", v8=False),
            version="02"))
        self.assertEqual(len(entries), 1)
        self.assertEqual(notes["pending"], 1)

    def test_the_booking_day_not_the_value_date(self):
        entries, _ = camt.read_statement(_statement(_entry(
            booked="2026-10-29", value="2026-11-02")))
        self.assertEqual(str(entries[0]["date"]), "2026-10-29")

    def test_without_a_booking_day_the_entry_is_unreadable(self):
        raw = _statement(_entry()).replace(
            b"<BookgDt><Dt>2026-10-29</Dt></BookgDt>", b"")
        entries, notes = camt.read_statement(raw)
        self.assertEqual(entries, [])
        self.assertEqual(notes["unreadable"], 1)


class TestTheSignIsTheIndicators(unittest.TestCase):

    def test_credit_is_money_in_debit_is_money_out(self):
        entries, _ = camt.read_statement(_statement(
            _entry(amount="100.00", ind="CRDT", ref="A")
            + _entry(amount="40.50", ind="DBIT", ref="B")))
        self.assertEqual([e["amount"] for e in entries], [100.0, -40.5])

    def test_a_returned_debit_is_money_in(self):
        """For a reversal the indicator already says the reversed way."""
        entries, _ = camt.read_statement(_statement(
            _entry(amount="40.50", ind="CRDT", reversal=True)))
        self.assertEqual(entries[0]["amount"], 40.5)

    def test_an_entry_without_an_indicator_is_unreadable(self):
        raw = _statement(_entry()).replace(b"<CdtDbtInd>CRDT</CdtDbtInd>",
                                           b"")
        entries, notes = camt.read_statement(raw)
        self.assertEqual((entries, notes["unreadable"]), ([], 1))


class TestTheAccountAndTheCurrency(unittest.TestCase):

    def test_the_statement_names_its_own_account(self):
        entries, _ = camt.read_statement(_statement(_entry()))
        self.assertEqual(entries[0]["own_iban"], OWN)

    def test_an_iban_that_fails_its_check_digits_addresses_nothing(self):
        broken = OWN[:-1] + ("9" if OWN[-1] != "9" else "8")
        entries, notes = camt.read_statement(_statement(_entry(), iban=broken))
        self.assertIsNone(entries[0]["own_iban"])
        self.assertEqual(notes["accounts_without_iban"], 1)

    def test_the_currency_travels_with_the_entry(self):
        entries, _ = camt.read_statement(_statement(_entry(ccy="CHF")))
        self.assertEqual(entries[0]["currency"], "CHF")

    def test_an_entry_in_another_currency_than_its_account_is_unreadable(self):
        entries, notes = camt.read_statement(_statement(
            _entry(ccy="USD"), currency="CHF"))
        self.assertEqual((entries, notes["unreadable"]), ([], 1))

    def test_two_accounts_without_iban_are_not_merged_onto_one(self):
        second = """<Stmt><Id>S2</Id>
          <Acct><Id><Othr><Id>ACC-2</Id></Othr></Id><Ccy>CHF</Ccy></Acct>
          {0}</Stmt>""".format(_entry(ref="Z"))
        raw = _statement(_entry(ref="Y"), iban="", extra_statements=second)
        raw = raw.replace(b"<IBAN></IBAN>", b"<Othr><Id>ACC-1</Id></Othr>")
        entries, notes = camt.read_statement(raw)
        self.assertEqual(entries, [])
        self.assertEqual(notes["unaddressable"], 2)


class TestTheBanksReferenceIsTheIdentity(unittest.TestCase):

    def test_the_account_servicer_reference_becomes_the_reference(self):
        entries, _ = camt.read_statement(_statement(_entry(ref="BANK-REF-7")))
        self.assertEqual(entries[0]["reference"], "BANK-REF-7")

    def test_the_same_entry_in_two_overlapping_statements_is_one(self):
        second = """<Stmt><Id>S2</Id>
          <Acct><Id><IBAN>{0}</IBAN></Id><Ccy>CHF</Ccy></Acct>
          {1}{2}</Stmt>""".format(OWN, _entry(ref="R1"), _entry(ref="R2"))
        entries, notes = camt.read_statement(_statement(
            _entry(ref="R1"), extra_statements=second))
        self.assertEqual([e["reference"] for e in entries], ["R1", "R2"])
        self.assertEqual(notes["repeated"], 1)

    def test_entries_without_a_reference_are_not_merged_by_looks(self):
        """Two identical fees are two bookings; see wiederholung."""
        entries, notes = camt.read_statement(_statement(
            _entry(ref="") + _entry(ref="")))
        self.assertEqual(len(entries), 2)
        self.assertEqual(notes["repeated"], 0)

    def test_the_same_reference_on_two_accounts_is_two_bookings(self):
        second = """<Stmt><Id>S2</Id>
          <Acct><Id><IBAN>{0}</IBAN></Id><Ccy>CHF</Ccy></Acct>
          {1}</Stmt>""".format(OTHER_OWN, _entry(ref="R1"))
        entries, _ = camt.read_statement(_statement(
            _entry(ref="R1"), extra_statements=second))
        self.assertEqual([e["own_iban"] for e in entries], [OWN, OTHER_OWN])


class TestTheCounterparty(unittest.TestCase):

    def test_a_credit_names_the_debtor(self):
        entries, _ = camt.read_statement(_statement(_entry(
            details=_details(_tx(name="Erika Beispiel", iban=PAYER)))))
        self.assertEqual(entries[0]["counterparty"], "Erika Beispiel")
        self.assertEqual(entries[0]["iban"], PAYER)

    def test_a_debit_names_the_creditor(self):
        entries, _ = camt.read_statement(_statement(_entry(
            ind="DBIT", details=_details(
                _tx(name="Max Muster", iban=PAYEE, side="Cdtr")))))
        self.assertEqual(entries[0]["counterparty"], "Max Muster")
        self.assertEqual(entries[0]["iban"], PAYEE)

    def test_the_name_without_pty_in_older_versions(self):
        entries, _ = camt.read_statement(_statement(_entry(
            v8=False, details=_details(_tx(name="Erika Beispiel", v8=False))),
            version="04"))
        self.assertEqual(entries[0]["counterparty"], "Erika Beispiel")

    def test_the_qr_reference_survives_into_the_description(self):
        qr = "210000000003139471430009017"
        entries, _ = camt.read_statement(_statement(_entry(
            details=_details(_tx(purpose="Miete", qr=qr)))))
        self.assertIn("Miete", entries[0]["description"])
        self.assertIn(qr, entries[0]["description"])
        self.assertIn("Gutschrift", entries[0]["description"])

    def test_a_batch_entry_stays_one_booking(self):
        """The bank booked one amount; one booking is what it booked."""
        entries, _ = camt.read_statement(_statement(_entry(
            amount="300.00", details=_details(
                _tx(name="Erika Beispiel", purpose="R1"),
                _tx(name="Max Muster", purpose="R2")))))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["amount"], 300.0)
        self.assertEqual(entries[0]["counterparty"], "")
        self.assertIn("Erika Beispiel", entries[0]["description"])
        self.assertIn("Max Muster", entries[0]["description"])


class TestTheBanksExchangeRate(unittest.TestCase):

    def test_with_a_unit_currency_the_rate_is_read_as_stated(self):
        self.assertEqual(camt.normalise_rate("EUR", "CHF", "EUR", "0.94"),
                         {"from": "EUR", "to": "CHF", "rate": 0.94})
        self.assertEqual(camt.normalise_rate("EUR", "CHF", "CHF", "1.06"),
                         {"from": "CHF", "to": "EUR", "rate": 1.06})

    def test_without_a_unit_the_amounts_decide_the_direction(self):
        amounts = {"EUR": 1000.0, "CHF": 940.0}
        self.assertEqual(
            camt.normalise_rate("EUR", "CHF", "", "0.94", amounts),
            {"from": "EUR", "to": "CHF", "rate": 0.94})
        self.assertEqual(
            camt.normalise_rate("EUR", "CHF", "", "1.0638", amounts),
            {"from": "CHF", "to": "EUR", "rate": 1.0638})

    def test_without_a_unit_and_without_amounts_there_is_no_rate(self):
        self.assertIsNone(camt.normalise_rate("EUR", "CHF", "", "0.94"))

    def test_a_rate_that_fits_no_direction_is_no_rate(self):
        self.assertIsNone(camt.normalise_rate(
            "EUR", "CHF", "", "1.50", {"EUR": 1000.0, "CHF": 940.0}))

    def test_nonsense_is_no_rate(self):
        for args in (("EUR", "EUR", "EUR", "1"), ("EUR", "CHF", "EUR", "0"),
                     ("EUR", "CHF", "EUR", "x"), ("", "CHF", "", "1"),
                     ("EUR", "CHF", "USD", "1.1")):
            self.assertIsNone(camt.normalise_rate(*args), args)

    def test_the_rate_is_used_both_ways_and_for_nothing_else(self):
        fx = {"from": "EUR", "to": "CHF", "rate": 0.94}
        self.assertEqual(camt.rate_between(fx, "EUR", "CHF"), 0.94)
        self.assertAlmostEqual(camt.rate_between(fx, "CHF", "EUR"), 1 / 0.94)
        self.assertIsNone(camt.rate_between(fx, "USD", "EUR"))
        self.assertIsNone(camt.rate_between(None, "CHF", "EUR"))

    def test_the_rate_is_read_from_the_entry(self):
        amount_details = """<AmtDtls>
          <InstdAmt><Amt Ccy="EUR">1000.00</Amt>
            <CcyXchg><SrcCcy>EUR</SrcCcy><TrgtCcy>CHF</TrgtCcy>
            <UnitCcy>EUR</UnitCcy><XchgRate>0.94</XchgRate></CcyXchg>
          </InstdAmt>
          <TxAmt><Amt Ccy="CHF">940.00</Amt></TxAmt>
        </AmtDtls>"""
        entries, _ = camt.read_statement(_statement(_entry(
            amount="940.00", details=_details(
                _tx(amount_details=amount_details)))))
        self.assertEqual(entries[0]["fx"],
                         {"from": "EUR", "to": "CHF", "rate": 0.94})

    def test_an_entry_without_a_rate_has_none(self):
        entries, _ = camt.read_statement(_statement(_entry(
            details=_details(_tx()))))
        self.assertIsNone(entries[0]["fx"])


def _source(*parts):
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    with open(os.path.join(root, *parts), encoding="utf-8") as handle:
        return handle.read()


class TestTheFileReachesTheOnePipeline(unittest.TestCase):
    """Read as text: statement_import needs a bench to load."""

    def setUp(self):
        self.text = _source("utils", "statement_import.py")

    def test_camt_is_recognised_before_the_bytes_are_decoded(self):
        reader = self.text[self.text.index("def read_entries"):]
        self.assertLess(reader.index("camt_statement.looks_like_camt(raw)"),
                        reader.index("text = decode(raw)"))

    def test_camt_entries_are_routed_like_every_other_file(self):
        self.assertIn('return _address_entries("camt053", entries,',
                      self.text)

    def test_a_currency_mismatch_is_held_back_before_the_duplicate_check(self):
        walk = self.text[self.text.index("def book_entries"):]
        self.assertLess(walk.index("currency_fits("),
                        walk.index("booking_budget.consume("))

    def test_the_booking_carries_currency_and_bank_rate(self):
        constructor = self.text[self.text.index("def create_booking"):
                                self.text.index("def account_currency_of")]
        for field in ("booking.currency", "booking.kefiya_fx_from",
                      "booking.kefiya_fx_to", "booking.kefiya_fx_rate"):
            self.assertIn(field, constructor)

    def test_still_drafts(self):
        constructor = self.text[self.text.index("def create_booking"):
                                self.text.index("def account_currency_of")]
        self.assertNotIn("submit()", constructor)
        self.assertNotIn('"docstatus": 1', constructor)

    def test_a_bank_format_has_a_label(self):
        """plan() looked MT940 up in PROFILES and raised a KeyError."""
        self.assertIn('FILE_FORMAT_LABELS = {"mt940": "MT940", '
                      '"camt053": "camt.053"}', self.text)
        self.assertNotIn('PROFILES[profile_name]["label"]\n    summary',
                         self.text)


class TestTheJournalEntryUsesTheBanksRate(unittest.TestCase):

    def test_every_conversion_asks_the_bank_first(self):
        text = _source("overrides", "bank_reconciliation_tool",
                       "bank_reconciliation_tool.py")
        body = text[text.index("def custom_create_journal_entry_bts"):]
        self.assertNotIn("get_exchange_rate(", body)
        calls = re.findall(r"exchange_rate_for\(\s*bank_fx,", body)
        self.assertEqual(len(calls),
                         3)

    def test_the_rate_fields_are_installed(self):
        text = _source("setup", "install.py")
        for field in ("kefiya_fx_from", "kefiya_fx_to", "kefiya_fx_rate"):
            self.assertIn('"fieldname": "{0}"'.format(field), text)


class TestTheImportIsLogged(unittest.TestCase):

    def test_the_log_fields_exist_and_are_written(self):
        doctype = _source("kefiya", "doctype", "kefiya_bank_statement_import",
                          "kefiya_bank_statement_import.json")
        controller = _source("kefiya", "doctype",
                             "kefiya_bank_statement_import",
                             "kefiya_bank_statement_import.py")
        for field in ("file_hash", "file_format", "duplicate_records",
                      "skipped_records"):
            self.assertIn('"fieldname": "{0}"'.format(field), doctype)
            self.assertIn('"{0}":'.format(field), controller)


if __name__ == "__main__":
    unittest.main()
