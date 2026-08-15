# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""What kind of account this is -- and what that means for its balance.

Not everything a bank shows under "accounts" is an account you can pay from,
and the single number the bank reports for it does not always mean the same
thing. Two entries of one customer make the point:

    Sofie KG Aval VB Kpf ...750    -1.409.672,26
    Sofie KG Aval VB Kpf ...769      -100.000,00

Those are Avale -- guarantee lines. The number is the line, not money on an
account. Nothing was ever booked there, nothing can be paid from there, and
counting a balance backwards over bookings that do not exist produces a column
of numbers that look like statements of fact and are not. The same holds for a
loan: the balance moves on the bank's schedule, not through a statement.

Cooperative shares are a third case, and a different one again. The two

    Dr. Alexander Finkeissen ...310    Geschaeftsanteile
    Maxi ...112                        Geschaeftsanteile

do hold an amount that is really there -- but it is held, not available, and it
is not the sum of any bookings either. So the amount is worth storing and worth
showing, and it has no business in a total of what can be paid out today.

So each login says what it is, and three questions are answered from that:

    keeps_a_running_balance()  -- may the balance be counted back over the
                                  bookings and written onto them?
    reports_a_credit_line()    -- is the number the bank states a line rather
                                  than a balance?
    counts_towards_liquidity() -- may it be added into a total of money that
                                  can be spent?

An account whose kind nobody has set counts as a payment account, which is what
every login was treated as before this existed: the classification can only
take things out of the balance logic, never silently put something new in.
"""

import frappe

# The values are stored in the database, so they are English like every other
# stored value in this app. What the user reads is the translation: the German
# wording lives in locale/de.po, next to the rest of it. A German value here
# would be data that changes meaning with the site language.
GIRO = "Current Account"
SAVINGS = "Savings"
CREDIT_CARD = "Credit Card"
LOAN = "Loan"
GUARANTEE = "Guarantee / Credit Line"
SHARES = "Cooperative Shares"
SECURITIES = "Securities Account"

KINDS = (GIRO, SAVINGS, CREDIT_CARD, LOAN, GUARANTEE, SHARES, SECURITIES)

#: Accounts whose balance is the sum of their bookings. Only for these does
#: counting backwards from today's balance describe anything real.
PAYMENT_KINDS = (GIRO, SAVINGS, CREDIT_CARD)

#: Accounts where the reported amount is a granted line, not money held.
CREDIT_LINE_KINDS = (GUARANTEE,)

#: Accounts a SEPA transfer can START from. Narrower than PAYMENT_KINDS,
#: because a credit card is a payment account that cannot originate one: the
#: card pays merchants, the settlement account pays the card.
#:
#: What made this necessary: the payer dropdown offered loans, guarantees and
#: securities accounts. Three filters were meant to prevent that -- the
#: Bank Account's account_type, a link to a Property Loan, and the bank's own
#: HIUPD capability list -- and all three missed, because account_type is not
#: maintained on those records, the loan link is not either, and HIUPD is
#: never fetched for an account nobody fetches. The kind was right on every
#: one of them the whole time; nothing asked.
TRANSFER_SOURCE_KINDS = (GIRO, SAVINGS)


def kind_of(kefiya_login):
    """The account kind of a login, defaulting to a payment account.

    :param kefiya_login: name of a Kefiya Login, or a document with the field
    :return: one of KINDS
    """
    if not kefiya_login:
        return GIRO

    value = None
    if isinstance(kefiya_login, str):
        # A field that has not been installed yet must not fail a fetch.
        if frappe.get_meta("Kefiya Login").has_field("account_kind"):
            value = frappe.db.get_value(
                "Kefiya Login", kefiya_login, "account_kind")
    else:
        value = getattr(kefiya_login, "account_kind", None)

    return value if value in KINDS else GIRO


def keeps_a_running_balance(kefiya_login):
    """May the balance be counted back over the bookings of this account?

    :return: True for a payment account, False for loan/guarantee/securities
    """
    return kind_of(kefiya_login) in PAYMENT_KINDS


def reports_a_credit_line(kefiya_login):
    """Does the number the bank states describe a line rather than a balance?"""
    return kind_of(kefiya_login) in CREDIT_LINE_KINDS


def counts_towards_liquidity(kefiya_login):
    """May this account's amount be added into a total of available money?

    A guarantee line is not money; a loan is not money that is there; and a
    cooperative share is money that is there and cannot be spent. All three
    belong in an overview, none of them belongs in its sum.
    """
    return kind_of(kefiya_login) in PAYMENT_KINDS


def can_send_transfers(kefiya_login):
    """May a SEPA transfer start from this account?

    The one question the payer dropdown has to ask. A loan, a guarantee, a
    share deposit and a securities account cannot send money; a credit card
    cannot either -- it is paid, it does not pay.
    """
    return kind_of(kefiya_login) in TRANSFER_SOURCE_KINDS


@frappe.whitelist()
def transfer_sources():
    """Every Kefiya Login a transfer may be entered against.

    The canonical answer, so a page does not have to reimplement it -- and so
    a page that asks gets the same list the app itself would use.

    get_list, not get_all: these are offered for selection, and an access the
    caller may not see must not appear in a dropdown.

    :return: [{"login", "bank_account", "company", "kind"}]
    """
    if not frappe.get_meta("Kefiya Login").has_field("account_kind"):
        # Before the field exists every login is a payment account, which is
        # what kind_of() answers anyway. Say so rather than return nothing.
        rows = frappe.get_list(
            "Kefiya Login", filters={"bank_account": ["is", "set"]},
            fields=["name", "bank_account", "company"], limit_page_length=0)
        return [{"login": r["name"], "bank_account": r["bank_account"],
                 "company": r.get("company"), "kind": GIRO} for r in rows]

    rows = frappe.get_list(
        "Kefiya Login",
        filters={"bank_account": ["is", "set"],
                 "account_kind": ["in", list(TRANSFER_SOURCE_KINDS)]},
        fields=["name", "bank_account", "company", "account_kind"],
        limit_page_length=0)

    # A disabled Bank Account is still a Bank Account; it is just not one an
    # order should be entered against.
    disabled = {r["name"] for r in frappe.get_all(
        "Bank Account", filters={"disabled": 1}, fields=["name"],
        limit_page_length=0)}

    return [{"login": r["name"], "bank_account": r["bank_account"],
             "company": r.get("company"), "kind": r.get("account_kind")}
            for r in rows if r["bank_account"] not in disabled]
