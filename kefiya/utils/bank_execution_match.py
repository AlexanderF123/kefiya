# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Which withdrawal on the statement is the execution of which order.

Without frappe, so the rule that decides "the bank has paid this" runs in a
test on real-shaped statement lines.

Two kinds of order are left waiting for that answer, and nothing else gives it:

* a dated transfer (Terminueberweisung) that the bank holds until its day --
  kefiya marks it "Scheduled at Bank" when it is handed over and then never
  hears from it again;
* a standing order the BANK keeps -- kefiya does not place its transfers, so
  no transfer of ours ever says it ran.

The only witness is the account statement. What it carries, measured on
11/2026 at a Sparkasse and a Volksbank account:

* the counterparty IBAN and the amount -- always;
* the purpose text -- yes, but glued to bank additions ("...10/2026DATUM
  01.11.2026, 14.28 UHR", "... / DA-3 IBAN: ...");
* the End-To-End ID -- on the RECEIVING side, not reliably on the debit.

So a payment is recognised by amount and IBAN, inside a window around its
date, and the purpose decides between two orders that share both -- two
monthly fees of the same size to the same payee are an ordinary case, not an
exotic one. An End-To-End ID in the text settles it on its own.

When the statement cannot tell two orders apart, nothing is matched. A wrong
"executed" hides an order that is still open; a missing one only leaves it
visible a little longer.
"""

import datetime

#: How far before its date a debit may appear: a bank books a dated order on
#: the banking day before, at the earliest.
DAYS_BEFORE = 3

#: How far after: weekends, a public holiday and a slow booking day.
DAYS_AFTER = 10

#: Leading characters of the purpose that must reappear in the statement.
#: Enough to tell "102 Fee ..." from "206 Fee ...", short enough to survive a
#: bank that cuts the purpose into 27-character lines.
PURPOSE_KEY_LENGTH = 16

#: Amounts are compared in cents; floats from the database are not.
CENT = 0.005


def normalize(text):
    """Letters and digits only, upper case -- what survives every bank."""
    return "".join(ch for ch in str(text or "").upper() if ch.isalnum())


def purpose_key(purpose):
    """The beginning of a purpose, normalised; empty when there is none."""
    return normalize(purpose)[:PURPOSE_KEY_LENGTH]


def as_date(value):
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(str(value)[:10])


def in_window(booked, due):
    """Whether a debit booked on ``booked`` can be the run due on ``due``."""
    booked, due = as_date(booked), as_date(due)
    if not booked or not due:
        return False
    return (due - datetime.timedelta(days=DAYS_BEFORE) <= booked
            <= due + datetime.timedelta(days=DAYS_AFTER))


def statement_text(txn):
    return normalize("{0} {1}".format(txn.get("description") or "",
                                      txn.get("reference_number") or ""))


def same_amount(txn, amount):
    return abs(float(txn.get("withdrawal") or 0) - float(amount or 0)) < CENT


def candidates(payment, txns):
    """Debits that could be this payment, each with how sure that is.

    ``payment``: {"iban", "amount", "purpose", "end_to_end_id", "due"}
    ``txns``: bank transactions as dicts with name, date, withdrawal,
    bank_party_iban, description, reference_number.

    :return: list of (txn, strength), strength 2 = End-To-End ID or purpose
        found in the text, 1 = amount, IBAN and date only.
    """
    found = []
    iban = normalize(payment.get("iban"))
    e2e = normalize(payment.get("end_to_end_id"))
    key = purpose_key(payment.get("purpose"))
    for txn in txns:
        if not same_amount(txn, payment.get("amount")):
            continue
        if not in_window(txn.get("date"), payment.get("due")):
            continue
        text = statement_text(txn)
        if e2e and e2e in text:
            found.append((txn, 2))
            continue
        if not iban or normalize(txn.get("bank_party_iban")) != iban:
            continue
        found.append((txn, 2 if key and key in text else 1))
    return found


def assign(payments, txns, taken=None):
    """Match each payment to at most one debit, no debit to two payments.

    ``payments`` is a list of dicts as for candidates(), each with a "key"
    the caller recognises it by. ``taken`` holds names of transactions that
    already belong to something and must not be handed out again.

    A payment takes a debit that names it (purpose or End-To-End ID). Without
    that, it takes the only debit of its amount and IBAN -- and only if no
    other open payment could claim the same debit. Ties are not broken by
    guessing: the payment stays open.

    :return: {payment key: txn}
    """
    taken = set(taken or ())
    result = {}
    options = {}
    for payment in payments:
        options[payment["key"]] = [
            (txn, strength) for txn, strength in candidates(payment, txns)
            if txn.get("name") not in taken]

    # Strong matches first, so a weak one cannot take a debit that names
    # somebody else.
    for payment in payments:
        strong = [txn for txn, strength in options[payment["key"]]
                  if strength == 2 and txn.get("name") not in taken]
        if strong:
            strong.sort(key=lambda t: (str(t.get("date")), t.get("name")))
            chosen = strong[0]
            result[payment["key"]] = chosen
            taken.add(chosen.get("name"))

    for payment in payments:
        if payment["key"] in result:
            continue
        weak = [txn for txn, strength in options[payment["key"]]
                if txn.get("name") not in taken]
        if len(weak) != 1:
            continue
        chosen = weak[0]
        rivals = [other for other in payments
                  if other["key"] != payment["key"]
                  and other["key"] not in result
                  and any(t.get("name") == chosen.get("name")
                          for t, _s in options[other["key"]])]
        if rivals:
            continue
        result[payment["key"]] = chosen
        taken.add(chosen.get("name"))
    return result


def batch_booking(transfer_name, total, due, txns, taken=None):
    """A collective order booked as one sum: the debit must name the order.

    Without the name a single sum is just an amount, and an amount alone is
    not evidence.
    """
    taken = set(taken or ())
    name = normalize(transfer_name)
    for txn in txns:
        if txn.get("name") in taken:
            continue
        if (name and same_amount(txn, total)
                and in_window(txn.get("date"), due)
                and name in statement_text(txn)):
            return txn
    return None
