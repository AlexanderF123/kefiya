# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Record-level privacy for bank accounts flagged as private.

A Bank Account with ``custom_is_private = 1`` — and every Bank Transaction
that points to it — is visible only to the users in ``ALLOWED_USERS``
(plus ``Administrator``). Both hook layers are required to avoid leaks:

* ``permission_query_conditions`` hides the records in list views, reports,
  exports, link search and REST ``get_list``.
* ``has_permission`` additionally blocks direct access by URL/name
  (Bank Transaction names are sequential and guessable).

Raw ``frappe.db.sql`` bypasses both layers, so SQL-based dashboards must
apply the same exclusion themselves.
"""

import frappe

# Users allowed to see private bank accounts and their transactions.
ALLOWED_USERS = {"alexander@finkeissen.de"}

PRIVATE_FIELD = "custom_is_private"


def is_allowed(user):
    return user == "Administrator" or user in ALLOWED_USERS


def privacy_field_exists():
    """Whether the ``custom_is_private`` column exists on Bank Account.

    Fail open while it does not (fresh install, mid-migrate before
    ``after_migrate`` created the field): without the column no account can
    be flagged private, so nothing can leak — but filtering on the missing
    column would break every Bank Account / Bank Transaction query.
    """
    return frappe.db.has_column("Bank Account", PRIVATE_FIELD)


def bank_account_query_conditions(user):
    if is_allowed(user or frappe.session.user) or not privacy_field_exists():
        return ""
    return f"coalesce(`tabBank Account`.`{PRIVATE_FIELD}`, 0) = 0"


def bank_transaction_query_conditions(user):
    if is_allowed(user or frappe.session.user) or not privacy_field_exists():
        return ""
    return (
        "`tabBank Transaction`.`bank_account` in "
        "(select `name` from `tabBank Account` "
        f"where coalesce(`{PRIVATE_FIELD}`, 0) = 0)"
    )


def bank_account_has_permission(doc, ptype=None, user=None, **kwargs):
    """Return False to deny, None for "no opinion" (normal role permissions
    apply). Never returns True — this hook only ever restricts access."""
    if is_allowed(user or frappe.session.user):
        return None
    if doc.get(PRIVATE_FIELD):
        return False
    return None


def bank_transaction_has_permission(doc, ptype=None, user=None, **kwargs):
    if is_allowed(user or frappe.session.user):
        return None
    bank_account = doc.get("bank_account")
    if not bank_account or not privacy_field_exists():
        return None
    if frappe.db.get_value("Bank Account", bank_account, PRIVATE_FIELD):
        return False
    return None
