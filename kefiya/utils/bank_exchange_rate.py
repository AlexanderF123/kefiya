# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""The bank's exchange rate on a Payment Entry made from a Bank Transaction.

Pure: no frappe. The override that builds the Payment Entry asks this module
which amounts and rates to set, so the arithmetic can be checked without a
site.

Where the statement stated the rate the bank applied (camt.053 ``CcyXchg``,
stored on the Bank Transaction as kefiya_fx_*), that is the rate the money
actually moved at. ERPNext would otherwise take its own rate of the posting
day, and the difference between the two becomes an exchange gain or loss
that never happened.

Only where ONE rate decides everything. A Payment Entry converts between up
to three currencies: the bank account's, the party account's and the
company's. With two distinct currencies among them, the bank's single rate
fixes every conversion and the base amounts of both sides agree by
construction. With three, the bank's rate would sit next to two system rates
whose cross rate is not the bank's -- the entry would not balance, or would
balance on a difference nobody can explain. Then nothing is changed and
ERPNext's own rates apply.
"""

from kefiya.utils.camt_statement import rate_between

#: The Payment Entry fields this module decides.
FIELDS = ("paid_amount", "received_amount", "source_exchange_rate",
          "target_exchange_rate")


def _rate(fx, from_currency, to_currency):
    if from_currency == to_currency:
        return 1.0
    return rate_between(fx, from_currency, to_currency)


def payment_entry_values(payment_type, bank_amount, bank_currency,
                         party_currency, company_currency, fx):
    """Amounts and rates of a Payment Entry at the bank's rate, or None.

    :param payment_type: "Receive" (money into the bank account) or "Pay"
    :param bank_amount: the Bank Transaction's amount, in bank_currency
    :param fx: {"from", "to", "rate"} as stored on the Bank Transaction
    :return: dict over FIELDS, or None where the bank's rate does not decide
        the entry on its own (see the module docstring)
    """
    if payment_type not in ("Receive", "Pay"):
        return None
    currencies = {bank_currency, party_currency, company_currency}
    if None in currencies or "" in currencies or len(currencies) != 2:
        # One currency: nothing to convert. Three: see above.
        return None

    bank_to_party = _rate(fx, bank_currency, party_currency)
    bank_to_company = _rate(fx, bank_currency, company_currency)
    party_to_company = _rate(fx, party_currency, company_currency)
    if not (bank_to_party and bank_to_company and party_to_company):
        # The bank's rate is about another pair of currencies.
        return None

    bank_amount = abs(float(bank_amount or 0))
    in_party_currency = bank_amount * bank_to_party

    if payment_type == "Receive":
        # From the party account, into the bank account.
        return {"paid_amount": in_party_currency,
                "received_amount": bank_amount,
                "source_exchange_rate": party_to_company,
                "target_exchange_rate": bank_to_company}
    return {"paid_amount": bank_amount,
            "received_amount": in_party_currency,
            "source_exchange_rate": bank_to_company,
            "target_exchange_rate": party_to_company}
