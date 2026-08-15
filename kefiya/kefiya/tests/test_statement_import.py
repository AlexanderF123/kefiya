# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Reading a statement file must not guess.

The reader this replaces skipped seven header rows and then addressed columns
by position. A file with a different layout was not rejected, it was misread --
and the two ways it misread were the expensive ones: an amount read from the
wrong column, and a card charge booked as income because a credit card counts
the other way round from a giro account.
"""

import unittest

from kefiya.utils import statement_import as si


class TestAmountsAreReadNotGuessed(unittest.TestCase):

    def test_german_and_english_notation(self):
        self.assertEqual(si.parse_amount("1.234,56"), 1234.56)
        self.assertEqual(si.parse_amount("1,234.56"), 1234.56)
        self.assertEqual(si.parse_amount("1234.56"), 1234.56)
        self.assertEqual(si.parse_amount("-12,50"), -12.50)

    def test_a_number_without_a_separator_is_that_number(self):
        """The old reader split off the last two digits whenever it found no
        separator, so 1234 euro silently became 12.34."""
        self.assertEqual(si.parse_amount("1234"), 1234.0)
        self.assertEqual(si.parse_amount("7"), 7.0)

    def test_thousands_separators_are_not_decimals(self):
        self.assertEqual(si.parse_amount("1,500"), 1500.0)
        self.assertEqual(si.parse_amount("1.500"), 1500.0)
        self.assertEqual(si.parse_amount("12,50"), 12.50)

    def test_the_trailing_minus_some_exports_use(self):
        self.assertEqual(si.parse_amount("12,50-"), -12.50)

    def test_currency_and_padding_are_ignored(self):
        self.assertEqual(si.parse_amount(' "EUR 1.234,56" '), 1234.56)
        self.assertEqual(si.parse_amount("1\xa0234,56"), 1234.56)

    def test_what_is_not_an_amount_says_so(self):
        for value in (None, "", "   ", "Betrag", "-", "n/a"):
            self.assertIsNone(si.parse_amount(value), value)


class TestDatesAreReadNotGuessed(unittest.TestCase):

    def test_the_formats_these_exports_use(self):
        self.assertEqual(str(si.parse_date("15.08.2026")), "2026-08-15")
        self.assertEqual(str(si.parse_date("2026-08-15")), "2026-08-15")

    def test_an_unreadable_date_is_none_not_today(self):
        """A booking filed under today's date is worse than one reported as
        unreadable -- it lands in the wrong month and reconciles against
        nothing."""
        self.assertIsNone(si.parse_date(""))
        self.assertIsNone(si.parse_date("Datum"))
        self.assertIsNone(si.parse_date("31.02.2026"))


class TestTheHeaderIsFound(unittest.TestCase):

    AMEX = (
        "Ihre Kartenabrechnung\n"
        "Konto: XXXX-123456\n"
        "\n"
        "Datum;Beschreibung;Karteninhaber;Betrag;Referenz\n"
        "01.08.2026;LUFTHANSA;M MUSTER;349,90;AT2601\n"
        "03.08.2026;ZAHLUNG ERHALTEN;M MUSTER;-1.000,00;AT2602\n"
    )

    def test_the_header_is_not_assumed_to_be_the_first_line(self):
        """"Skip seven rows" was a fact about one file, not about statements."""
        name, columns, rows, index = si.read_rows(self.AMEX)
        self.assertEqual(name, "amex")
        self.assertEqual(index, 3)
        self.assertEqual(len(rows), 2)

    def test_columns_are_matched_by_name(self):
        name, columns, _, _ = si.read_rows(self.AMEX)
        self.assertEqual(columns["date"], 0)
        self.assertEqual(columns["amount"], 3)
        self.assertEqual(columns["description"], 1)

    def test_a_column_inserted_in_the_middle_shifts_nothing(self):
        shifted = self.AMEX.replace(
            "Datum;Beschreibung;Karteninhaber;Betrag;Referenz",
            "Datum;Kategorie;Beschreibung;Karteninhaber;Betrag;Referenz"
        ).replace("01.08.2026;LUFTHANSA", "01.08.2026;Reise;LUFTHANSA"
        ).replace("03.08.2026;ZAHLUNG ERHALTEN", "03.08.2026;Zahlung;ZAHLUNG ERHALTEN")
        name, columns, rows, _ = si.read_rows(shifted)
        self.assertEqual(name, "amex")
        self.assertEqual(columns["amount"], 4,
                         "Positional reading would still be pointing at 3.")

    def test_an_unknown_layout_is_reported_not_misread(self):
        name, _, _, _ = si.read_rows("alpha;beta;gamma\n1;2;3\n")
        self.assertIsNone(name)

    def test_a_byte_order_mark_does_not_hide_the_first_column(self):
        """Excel writes one, and read as plain utf-8 the first header cell
        begins with an invisible character that matches nothing."""
        raw = self.AMEX.encode("utf-8-sig")
        name, columns, _, _ = si.read_rows(si.decode(raw))
        self.assertEqual(name, "amex")
        self.assertEqual(columns["date"], 0)

    def test_encodings_these_exports_actually_use(self):
        for encoding in ("utf-8", "cp1252", "iso-8859-1"):
            text = si.decode("Beguenstigter;Betrag".replace(
                "Beguenstigter", "Begünstigter").encode(encoding))
            self.assertIn("nstigter", text, encoding)


class TestAFileMayHoldTwoEncodings(unittest.TestCase):
    """A real export held 887 UTF-8 lines and 1.695 cp1252 lines in one file --
    accesses exported at different times, concatenated, behind a UTF-8 byte
    order mark that describes only the first half."""

    HEADER = "IBAN;Buchungstag;Betrag;Buchungstext;Verwendungszweckzeile 1;Laufende Nummer\n"

    def _mixed(self):
        utf8_line = "DE02120300000000202051;01.04.2026;10,00;GUTSCHRIFT;ÜBERWEISUNG;1\n"
        cp_line = "DE02120300000000202051;02.04.2026;-20,00;LASTSCHRIFT;Bürobedarf;2\n"
        return (b"\xef\xbb\xbf" + self.HEADER.encode("utf-8")
                + utf8_line.encode("utf-8") + cp_line.encode("cp1252"))

    def test_both_halves_come_out_readable(self):
        text = si.decode(self._mixed())
        self.assertIn("ÜBERWEISUNG", text, "the UTF-8 half")
        self.assertIn("Bürobedarf", text, "the cp1252 half")

    def test_neither_half_is_turned_into_mojibake(self):
        """Read wholesale as cp1252 every Ü becomes Ãœ; read wholesale as
        UTF-8 the file does not decode at all."""
        text = si.decode(self._mixed())
        self.assertNotIn("Ã", text)
        self.assertNotIn("�", text)

    def test_the_byte_order_mark_never_reaches_the_first_column(self):
        """Left in place it prefixes the first header cell and that cell then
        matches no column name at all."""
        text = si.decode(self._mixed())
        self.assertTrue(text.startswith("IBAN"), repr(text[:12]))
        name, columns, _, _ = si.read_rows(text)
        self.assertEqual(name, "starmoney")
        self.assertEqual(columns["own_iban"], 0)

    def test_a_plain_utf8_file_is_not_touched_line_by_line(self):
        """The common case must stay one decode, not one per line."""
        text = si.decode("Datum;Betrag\n01.08.2026;1,00\n".encode("utf-8"))
        self.assertEqual(text, "Datum;Betrag\n01.08.2026;1,00\n")


class TestAFileMayCoverManyAccounts(unittest.TestCase):
    """A StarMoney export covers every access the program knows. Its "IBAN"
    column is the account the booking belongs TO -- read as a counterparty
    IBAN, every booking would name its own account as the other side."""

    FILE = (
        "IBAN;Buchungstag;Betrag;Buchungstext;Verwendungszweckzeile 1;Laufende Nummer\n"
        "DE02120300000000202051;01.04.2026;-100,00;LASTSCHRIFT;Strom;11\n"
        "DE89370400440532013000;02.04.2026;250,00;GUTSCHRIFT;Miete;12\n"
    )

    def test_the_own_account_is_read_as_such(self):
        name, columns, rows, _ = si.read_rows(self.FILE)
        self.assertEqual(name, "starmoney")
        entries = [si.to_entry(r, columns, si.PROFILES[name]) for r in rows]
        self.assertEqual(entries[0]["own_iban"], "DE02120300000000202051")
        self.assertIsNone(entries[0]["iban"],
                          "The own IBAN must not double as the counterparty.")

    def test_two_accounts_are_told_apart(self):
        name, columns, rows, _ = si.read_rows(self.FILE)
        entries = [si.to_entry(r, columns, si.PROFILES[name]) for r in rows]
        self.assertNotEqual(entries[0]["own_iban"], entries[1]["own_iban"])

    def test_the_posting_text_and_the_purpose_both_survive(self):
        """One says what the bank called it, the other what the payer wrote."""
        name, columns, rows, _ = si.read_rows(self.FILE)
        entry = si.to_entry(rows[0], columns, si.PROFILES[name])
        self.assertIn("LASTSCHRIFT", entry["description"])
        self.assertIn("Strom", entry["description"])

    def test_the_running_number_becomes_the_reference(self):
        name, columns, rows, _ = si.read_rows(self.FILE)
        entry = si.to_entry(rows[0], columns, si.PROFILES[name])
        self.assertEqual(entry["reference"], "11")

    def test_a_giro_sign_convention_applies(self):
        name, columns, rows, _ = si.read_rows(self.FILE)
        entries = [si.to_entry(r, columns, si.PROFILES[name]) for r in rows]
        self.assertEqual(entries[0]["amount"], -100.0)
        self.assertEqual(entries[1]["amount"], 250.0)


class TestADuplicateIsNotOnlyAKnownReference(unittest.TestCase):
    """The reference hash recognises only what this module wrote. A booking
    the bank delivered by FinTS carries the bank's own reference, so a hash
    comparison sees a stranger and books it again -- which is exactly the case
    when a file fills a gap in an account that is otherwise fetched."""

    def test_the_plan_also_compares_what_a_booking_is(self):
        import inspect
        source = inspect.getsource(si.plan)
        self.assertIn("already_booked(target, entry)", source)

    def test_the_content_check_is_account_day_and_amount(self):
        import inspect
        source = inspect.getsource(si.already_booked)
        for part in ('"bank_account": bank_account', '"date"', "deposit",
                     "withdrawal"):
            self.assertIn(part, source)

    def test_the_side_of_the_booking_is_part_of_the_comparison(self):
        """A payment out and a payment in of the same amount on the same day
        are two bookings, not one."""
        import inspect
        source = inspect.getsource(si.already_booked)
        self.assertIn("if amount > 0", source)


class TestACardCountsTheOtherWayRound(unittest.TestCase):
    """The expensive mistake. On a giro account a positive amount is money
    arriving; on a card statement it is a charge -- money leaving. Read with
    the giro convention, a year of card spending books as income."""

    def _entries(self, text):
        name, columns, rows, _ = si.read_rows(text)
        profile = si.PROFILES[name]
        return [si.to_entry(r, columns, profile) for r in rows]

    def test_a_card_charge_is_money_leaving(self):
        entries = self._entries(TestTheHeaderIsFound.AMEX)
        self.assertEqual(entries[0]["amount"], -349.90,
                         "A flight bought on the card is not income.")

    def test_a_card_payment_received_is_money_arriving(self):
        entries = self._entries(TestTheHeaderIsFound.AMEX)
        self.assertEqual(entries[1]["amount"], 1000.00)

    def test_a_giro_row_keeps_its_sign(self):
        giro = ("Buchungstag;Beguenstigter;Verwendungszweck;IBAN;Betrag\n"
                "01.08.2026;Mieter A;Miete August;DE02120300000000202051;1.200,00\n")
        entries = self._entries(giro)
        self.assertEqual(entries[0]["amount"], 1200.00)

    def test_every_profile_declares_its_convention(self):
        for name, profile in si.PROFILES.items():
            self.assertIn("charges_are_positive", profile, name)
            self.assertIsInstance(profile["charges_are_positive"], bool, name)


class TestARowThatCannotBeReadSaysSo(unittest.TestCase):

    def test_a_missing_amount_is_not_a_zero_booking(self):
        name, columns, rows, _ = si.read_rows(
            TestTheHeaderIsFound.AMEX.replace("349,90", ""))
        self.assertIsNone(si.to_entry(rows[0], columns, si.PROFILES[name]))

    def test_a_missing_date_is_not_today(self):
        name, columns, rows, _ = si.read_rows(
            TestTheHeaderIsFound.AMEX.replace("01.08.2026", ""))
        self.assertIsNone(si.to_entry(rows[0], columns, si.PROFILES[name]))


class TestAFeedFromOutsideIsReadTheSameWay(unittest.TestCase):
    """A card issuer that speaks no FinTS is still reachable -- through a
    licensed account information service, or through a document service that
    already holds the connection. What arrives is a record, not a CSV row, and
    it must not be trusted any further than a row is."""

    AMEX_ROW = {"date": "01.08.2026", "amount": "349,90",
                "description": "LUFTHANSA", "transactionId": "AT2601"}

    def test_a_card_charge_stays_money_leaving(self):
        entry = si.normalise_pushed(self.AMEX_ROW, profile_name="amex")
        self.assertEqual(entry["amount"], -349.90)

    def test_the_same_record_read_as_a_giro_feed_goes_the_other_way(self):
        """Which is exactly why the convention must be stated, not assumed."""
        entry = si.normalise_pushed(self.AMEX_ROW, profile_name="sepa_csv")
        self.assertEqual(entry["amount"], 349.90)

    def test_an_unstated_convention_is_refused_not_guessed(self):
        with self.assertRaises(Exception):
            si.normalise_pushed(self.AMEX_ROW, profile_name=None)

    def test_an_explicit_override_wins(self):
        entry = si.normalise_pushed(self.AMEX_ROW, charges_are_positive=False)
        self.assertEqual(entry["amount"], 349.90)

    def test_the_key_names_these_services_actually_use(self):
        for key in ("bookingDate", "booking_date", "valueDate", "datum"):
            entry = si.normalise_pushed(
                {key: "01.08.2026", "amount": "10,00"}, profile_name="amex")
            self.assertIsNotNone(entry, key)

    def test_the_services_own_id_becomes_the_reference(self):
        """It is what survives a re-download of the same period."""
        entry = si.normalise_pushed(self.AMEX_ROW, profile_name="amex")
        self.assertEqual(entry["reference"], "AT2601")

    def test_a_record_that_cannot_be_read_is_not_a_zero_booking(self):
        self.assertIsNone(si.normalise_pushed(
            {"description": "no date, no amount"}, profile_name="amex"))
        self.assertIsNone(si.normalise_pushed(
            {"date": "01.08.2026"}, profile_name="amex"))


class TestTheEndpointsGuardThemselves(unittest.TestCase):
    """Whitelisted endpoints are callable by any logged-in user, and both of
    these write."""

    def test_ingest_checks_rights_before_it_books(self):
        import inspect
        source = inspect.getsource(si.ingest)
        self.assertIn('frappe.has_permission("Bank Account", ptype="write"',
                      source)
        self.assertIn('"Bank Transaction", ptype="create"', source)
        self.assertLess(
            source.index("has_permission"), source.index("frappe.get_doc({"),
            "The check must come before the first booking, not after it.")

    def test_ingest_writes_nothing_unless_it_was_asked_by_name(self):
        """A bulk write that a misconfigured workflow can trigger by omission
        is one that will eventually be triggered by omission."""
        import inspect
        signature = inspect.signature(si.ingest)
        self.assertEqual(signature.parameters["dry_run"].default, 1)

    def test_nothing_is_submitted_from_a_feed(self):
        """Submitting is an approval, and an unattended feed does not give
        itself one."""
        import inspect
        self.assertNotIn(".submit(", inspect.getsource(si.ingest))

    def test_attaching_a_statement_checks_rights_and_repeats_harmlessly(self):
        import inspect
        source = inspect.getsource(si.attach_statement)
        self.assertIn('frappe.has_permission("Bank Account", ptype="write"',
                      source)
        self.assertIn('"is_private": 1', source)
        self.assertIn('frappe.db.exists("File"', source)


class TestTheSameFileTwiceIsHarmless(unittest.TestCase):
    """The import this replaces had no dedup whatsoever: importing a file a
    second time created every booking a second time."""

    ENTRY = {"date": "2026-08-01", "amount": -349.90,
             "counterparty": "M MUSTER", "description": "LUFTHANSA"}

    def test_the_same_booking_gets_the_same_reference(self):
        self.assertEqual(
            si.reference_number("Card - Amex", dict(self.ENTRY)),
            si.reference_number("Card - Amex", dict(self.ENTRY)))

    def test_a_different_booking_gets_a_different_one(self):
        other = dict(self.ENTRY, amount=-350.0)
        self.assertNotEqual(
            si.reference_number("Card - Amex", self.ENTRY),
            si.reference_number("Card - Amex", other))

    def test_the_same_booking_on_another_account_is_another_booking(self):
        self.assertNotEqual(
            si.reference_number("Card - Amex", self.ENTRY),
            si.reference_number("Girokonto - Genobank eG", self.ENTRY))

    def test_the_banks_own_reference_wins_where_there_is_one(self):
        """It is the only identifier that survives a changed description."""
        a = si.reference_number("Card - Amex", dict(self.ENTRY, reference="AT2601"))
        b = si.reference_number("Card - Amex", dict(
            self.ENTRY, reference="AT2601", description="LUFTHANSA AG FRANKFURT"))
        self.assertEqual(a, b)

    def test_the_reference_does_not_depend_on_the_row_number(self):
        """A file downloaded a week later has the same bookings further down."""
        import inspect
        source = inspect.getsource(si.reference_number)
        for forbidden in ("index", "row_number", "idx"):
            self.assertNotIn(forbidden, source)
