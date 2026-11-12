# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""German amounts, as the DKB formats write them (phamos-eu/kefiya#62).

In the original these cases test format_amount_iso. Here the reading lives
in statement_formats.parse_amount, and the DKB profiles declare
decimal_comma; the cases are the same.
"""

import unittest

from kefiya.utils.statement_formats import parse_amount


def german(amount):
    return parse_amount(amount, decimal_comma=True)


class TestIsoAmount(unittest.TestCase):
    def test_amount_without_comma_is_whole_euros(self):
        # Used to be read as cents: "1234" as 12.34
        self.assertEqual(german("1234"), 1234.0)
        self.assertEqual(german("-1234"), -1234.0)

    def test_dot_is_a_thousands_separator(self):
        # Used to be read as 15.00
        self.assertEqual(german("1.500"), 1500.0)

    def test_short_amount(self):
        # Used to fail
        self.assertEqual(german("-7"), -7.0)

    def test_decimals_as_before(self):
        self.assertEqual(german("12,50"), 12.5)
        self.assertEqual(german("12,5"), 12.5)
        self.assertEqual(german('"-1.234,56"'), -1234.56)

    def test_ambiguous_amount_is_refused(self):
        # "12.50" is no German amount: refuse it instead of booking 1250.00
        for amount in ("12.50", "1.23", "1.2345", "12,", "", "abc"):
            with self.subTest(amount=amount):
                self.assertIsNone(german(amount))


if __name__ == "__main__":
    unittest.main()
