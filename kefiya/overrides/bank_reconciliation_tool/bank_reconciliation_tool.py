# custom_app/custom_app/overrides.py

import frappe
import json
from erpnext import get_default_cost_center
from erpnext.setup.utils import get_exchange_rate
from frappe.utils import flt
from frappe import _
from erpnext.accounts.doctype.bank_reconciliation_tool.bank_reconciliation_tool import (
    reconcile_vouchers,
)

from kefiya.utils.camt_statement import rate_between


def bank_rate_of(bank_transaction_name):
    """The exchange rate the bank's statement stated for this booking.

    :return: {"from", "to", "rate"} or None -- None also where the custom
        fields are not migrated yet, so this never stands in the way of a
        Journal Entry.
    """
    if not frappe.get_meta("Bank Transaction").has_field("kefiya_fx_rate"):
        return None
    row = frappe.db.get_value(
        "Bank Transaction", bank_transaction_name,
        ["kefiya_fx_from", "kefiya_fx_to", "kefiya_fx_rate"], as_dict=True)
    if not row or not row.kefiya_fx_rate:
        return None
    return {"from": row.kefiya_fx_from, "to": row.kefiya_fx_to,
            "rate": row.kefiya_fx_rate}


def exchange_rate_for(bank_fx, from_currency, to_currency, posting_date):
    """The bank's rate where it is about these two currencies, else ERPNext's.

    A statement in CHF that converted an incoming EUR payment states the
    rate the bank actually applied; that is the rate the money moved at, and
    it is preferred to the system's rate of the day. Any other pair is not
    what the bank said anything about.
    """
    return (rate_between(bank_fx, from_currency, to_currency)
            or get_exchange_rate(from_currency, to_currency, posting_date))

@frappe.whitelist()
def custom_create_journal_entry_bts(
    bank_transaction_name,
    reference_number=None,
    reference_date=None,
    posting_date=None,
    entry_type=None,
    second_account=None,
    account=None,
    mode_of_payment=None,
    party_type=None,
    party=None,
    allow_edit=None,
):
    # Permission gate: creates and submits a Journal Entry against a Bank
    # Transaction, so it needs write rights on that transaction rather than
    # being callable by any logged-in user.
    frappe.has_permission(
        "Bank Transaction", ptype="write",
        doc=bank_transaction_name, throw=True)
    # Create a new journal entry based on the bank transaction
    bank_transaction = frappe.db.get_values(
        "Bank Transaction",
        bank_transaction_name,
        fieldname=["name", "deposit", "withdrawal", "bank_account", "currency"],
        as_dict=True,
    )[0]
    bank_fx = bank_rate_of(bank_transaction_name)
    company_account = frappe.get_value("Bank Account", bank_transaction.bank_account, "account")
    account_type = frappe.db.get_value("Account", second_account, "account_type")
    if account_type in ["Receivable", "Payable"]:
        if not (party_type and party):
            frappe.throw(
                _("Party Type and Party is required for Receivable / Payable account {0}").format(
                    second_account
                )
            )

    company = frappe.get_value("Account", company_account, "company")
    company_default_currency = frappe.get_cached_value("Company", company, "default_currency")
    company_account_currency = frappe.get_cached_value("Account", company_account, "account_currency")
    second_account_currency = frappe.get_cached_value("Account", second_account, "account_currency")

    # determine if multi-currency Journal or not
    is_multi_currency = (
        True
        if company_default_currency != company_account_currency
        or company_default_currency != second_account_currency
        or company_default_currency != bank_transaction.currency
        else False
    )

    accounts = []
    second_account_dict = {
        "account": second_account,
        "account_currency": second_account_currency,
        "credit_in_account_currency": bank_transaction.deposit,
        "debit_in_account_currency": bank_transaction.withdrawal,
        "party_type": party_type,
        "party": party,
        "cost_center": get_default_cost_center(company),
    }


    reverse_second_account_dict = {
        "account": second_account,
        "account_currency": second_account_currency,
        "credit_in_account_currency": bank_transaction.withdrawal,
        "debit_in_account_currency": bank_transaction.deposit,
        "party_type": party_type,
        "party": party,
        "cost_center": get_default_cost_center(company),
    }

    company_account_dict = {
        "account": company_account,
        "account_currency": company_account_currency,
        "bank_account": bank_transaction.bank_account,
        "credit_in_account_currency": bank_transaction.withdrawal,
        "debit_in_account_currency": bank_transaction.deposit,
        "cost_center": get_default_cost_center(company),
    }

    # convert transaction amount to company currency
    if is_multi_currency:
        exc_rate = exchange_rate_for(
            bank_fx, bank_transaction.currency, company_default_currency,
            posting_date)
        if not exc_rate:
            frappe.throw('Set the transaction exchange rate.')
        withdrawal_in_company_currency = flt(exc_rate * abs(bank_transaction.withdrawal))
        deposit_in_company_currency = flt(exc_rate * abs(bank_transaction.deposit))
    else:
        withdrawal_in_company_currency = bank_transaction.withdrawal
        deposit_in_company_currency = bank_transaction.deposit

    # if second account is of foreign currency, convert and set debit and credit fields.
    if second_account_currency != company_default_currency:
        exc_rate = exchange_rate_for(
            bank_fx, second_account_currency, company_default_currency,
            posting_date)
        second_account_dict.update(
            {
                "exchange_rate": exc_rate,
                "credit": deposit_in_company_currency,
                "debit": withdrawal_in_company_currency,
                "credit_in_account_currency": flt(deposit_in_company_currency / exc_rate) or 0,
                "debit_in_account_currency": flt(withdrawal_in_company_currency / exc_rate) or 0,
            }
        )

        reverse_second_account_dict.update(
            {
                "exchange_rate": exc_rate,
                "credit": withdrawal_in_company_currency,
                "debit": deposit_in_company_currency,
                "credit_in_account_currency": flt(withdrawal_in_company_currency / exc_rate) or 0,
                "debit_in_account_currency": flt(deposit_in_company_currency / exc_rate) or 0,
            }
        )
    else:
        second_account_dict.update(
            {
                "exchange_rate": 1,
                "credit": deposit_in_company_currency,
                "debit": withdrawal_in_company_currency,
                "credit_in_account_currency": deposit_in_company_currency,
                "debit_in_account_currency": withdrawal_in_company_currency,
            }
        )

        reverse_second_account_dict.update(
            {
                "exchange_rate": 1,
                "credit": withdrawal_in_company_currency,
                "debit": deposit_in_company_currency,
                "credit_in_account_currency": withdrawal_in_company_currency,
                "debit_in_account_currency": deposit_in_company_currency,
            }
        )

    # if company account is of foreign currency, convert and set debit and credit fields.
    if company_account_currency != company_default_currency:
        exc_rate = exchange_rate_for(
            bank_fx, company_account_currency, company_default_currency,
            posting_date)
        company_account_dict.update(
            {
                "exchange_rate": exc_rate,
                "credit": withdrawal_in_company_currency,
                "debit": deposit_in_company_currency,
            }
        )
    else:
        company_account_dict.update(
            {
                "exchange_rate": 1,
                "credit": withdrawal_in_company_currency,
                "debit": deposit_in_company_currency,
                "credit_in_account_currency": withdrawal_in_company_currency,
                "debit_in_account_currency": deposit_in_company_currency,
            }
        )

    additional_account = account
    if additional_account:
        additional_account_currency = frappe.get_cached_value("Account", additional_account, "account_currency")
        additional_account_dict = {
            "account": additional_account,
            "account_currency": additional_account_currency,
            "credit_in_account_currency": bank_transaction.deposit,
            "debit_in_account_currency": bank_transaction.withdrawal,
            "cost_center": get_default_cost_center(company),
        }
    
    accounts.append(additional_account_dict)
    accounts.append(reverse_second_account_dict)

    accounts.append(second_account_dict)
    accounts.append(company_account_dict)

    journal_entry_dict = {
        "voucher_type": entry_type,
        "company": company,
        "posting_date": posting_date,
        "cheque_date": reference_date,
        "cheque_no": reference_number,
        "mode_of_payment": mode_of_payment,
    }
    if is_multi_currency:
        journal_entry_dict.update({"multi_currency": True})

    journal_entry = frappe.new_doc("Journal Entry")
    journal_entry.update(journal_entry_dict)
    journal_entry.set("accounts", accounts)

    if allow_edit:
        return journal_entry

    journal_entry.insert()
    journal_entry.submit()

    if bank_transaction.deposit > 0.0:
        paid_amount = bank_transaction.deposit
    else:
        paid_amount = bank_transaction.withdrawal

    vouchers = json.dumps(
        [
            {
                "payment_doctype": "Journal Entry",
                "payment_name": journal_entry.name,
                "amount": paid_amount,
            }
        ]
    )

    return reconcile_vouchers(bank_transaction_name, vouchers)