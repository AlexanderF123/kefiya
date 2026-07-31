# -*- coding: utf-8 -*-
# Copyright (c) 2019, jHetzer and contributors
# For license information, please see license.txt

from __future__ import unicode_literals

import contextlib
import frappe
import json
import mt940

from dateutil.relativedelta import relativedelta
from fints.client import FinTS3PinTanClient, FinTSClientMode, NeedTANResponse, NeedRetryResponse

from frappe import _
from frappe.utils import now_datetime, cint
from frappe.utils.file_manager import (
    save_file,
    get_file,
    get_content_hash,
)
from .import_bank_transaction import (
    ImportBankTransaction,
    resolve_incremental_from_date,
)
from .auto_reconcile import run_after_import
from .assign_payment_controller import AssignmentController

class InitFailedException(Exception):
    pass

class TanInteractionRequired(InitFailedException):
    pass


#: How many of the bank's IBANs an "account not found" message lists before it
#: switches to a count. Enough to identify the access, short enough to read.
OFFERED_IBAN_PREVIEW = 10


#: Key under which the active fetch session lives on ``frappe.local``. Request
#: scoped by construction: frappe.local is rebuilt for every request and every
#: background job, so a session can never outlive the work it belongs to.
_SESSION_KEY = "kefiya_fints_session"


def _active_session():
    return getattr(frappe.local, _SESSION_KEY, None)


def _access_key(kefiya_login):
    """Identify the bank access (online-banking contract) of a login.

    Two logins with the same BLZ and the same FinTS login are the same access
    mapped to two accounts -- the bank sees one contract, and one dialog can
    serve both. The BLZ alone is not enough: two separate contracts at the same
    bank must never share a dialog.
    """
    blz = kefiya_login.blz
    fints_login = kefiya_login.fints_login
    if not (blz and fints_login):
        return None
    return (str(blz), str(fints_login))


def _is_unsupported_operation(exc):
    """True for "this bank does not offer that segment".

    Decided from the stored BPD without ever touching the dialog, so it leaves
    the connection perfectly usable -- and it is the common case here, twelve
    in a single collective run. Every other failure may have left the dialog
    broken or parked.
    """
    try:
        from fints.exceptions import FinTSUnsupportedOperation
    except Exception:
        return False
    return isinstance(exc, FinTSUnsupportedOperation)


def _retire_connection(session, conn):
    """Drop a connection from the session after a command failed on it.

    With a dialog per command, a broken dialog died with the command that broke
    it. In a shared session every later command inherits it, so one failure
    would take down the rest of the login -- or, in a group fetch, the rest of
    the bank access. Retiring it means the next controller opens a fresh dialog
    and pays one handshake, which is what would have happened anyway before.

    A paused dialog is deliberately left alone: a TAN request parks it for the
    user to release later, and ending it would throw that away. It is still
    removed from the session, because nothing may send on a paused dialog.
    """
    for access, registered in list(session.get("connections", {}).items()):
        if registered is conn:
            session["connections"].pop(access, None)

    if conn in session.get("open", []):
        session["open"].remove(conn)

    dialog = getattr(conn, "_standing_dialog", None)
    if dialog is not None and getattr(dialog, "paused", False):
        return

    try:
        conn.__exit__(None, None, None)
    except Exception:
        frappe.logger("kefiya").exception(
            "Kefiya: closing a failed FinTS dialog failed")


@contextlib.contextmanager
def fints_session():
    """Hold one FinTS dialog open across everything done inside.

    Without this, a single "fetch everything" for one login builds five
    controllers -- transactions, balance, standing orders, statements, credit
    card -- and each opens its own dialog: HKIDN/HKVVB, authentication, the one
    command that actually carries data, HKEND. The handshake costs several
    round trips, the data costs one, and that ratio is the whole reason a
    collective fetch of 48 accounts takes twelve minutes.

    Inside a session, controllers of the same bank access share one client and
    one open dialog, so the handshake is paid once instead of once per command
    -- and, for a caller that wraps several logins of the same access, once per
    access instead of once per account.

    Nesting is allowed and simply joins the outer session, so wrapping
    fetch_all() is enough for a single login and wrapping a whole group is
    enough for a bank access.

    Outside a session nothing changes: every dialog is opened and closed
    exactly as before.
    """
    if _active_session() is not None:
        yield
        return

    setattr(frappe.local, _SESSION_KEY, {"connections": {}, "open": []})
    try:
        yield
    finally:
        session = _active_session() or {"open": []}
        setattr(frappe.local, _SESSION_KEY, None)
        # Close every dialog this session opened. Guarded per connection: the
        # session ends on the error path too, and a bank that dropped the
        # connection must not turn into a second exception on the way out.
        for conn in session.get("open", []):
            try:
                conn.__exit__(None, None, None)
            except Exception:
                frappe.logger("kefiya").exception(
                    "Kefiya: closing a shared FinTS dialog failed")


def _mask_iban(value):
    """Shorten an IBAN for diagnostic output.

    Error messages end up in the Error Log, which is broadly readable. Keeping
    the country code and the last four digits is enough to tell the accounts of
    one login apart without writing full account numbers into the log.
    """
    if not value:
        return "<no IBAN>"
    value = str(value)
    if len(value) <= 6:
        return value
    return "{0}***{1}".format(value[:2], value[-4:])

class FinTSController:
    def __init__(self, kefiya_login_docname:str, interactive:bool=False, tan_mode:str=None, tan_medium:str=None, tan:str=...):
        self.kefiya_login = frappe.get_doc("Kefiya Login", kefiya_login_docname)

        # If this is load during a user interaction, verify its permissions (ignore for scheduled background tasks)
        if interactive and interactive["enabled"]:
            frappe.has_permission(ptype="write", doc=self.kefiya_login, throw=True)

        self.name = self.kefiya_login.name
        self.interactive = FinTSInteractive(interactive)

        self.__init_fints_connection()

        # If state is new and did not setup tan requirements, init tan mode (and probably ask user for mode and medium).
        if self.__init_tan_mode(tan_mode, tan_medium, tan) is False:
            raise TanInteractionRequired()

        # If there is an open TAN request, try to fulfill it.
        #
        # Not while a dialog of this access is already standing: resume_dialog()
        # refuses to run inside one, and it would be pointless anyway -- an open
        # dialog means the access is authenticated, so this login's parked
        # challenge is a leftover from an earlier attempt and has nothing left
        # to unlock.
        if self.kefiya_login.stored_tan_blob \
                and not self.fints_connection._standing_dialog:
            with self.fints_connection.resume_dialog(self.kefiya_login.stored_dialog_blob):
                tan_request = NeedRetryResponse.from_data(self.kefiya_login.stored_tan_blob)

                # this decoupled setting is missing everywhere, so decoupled requests (like pushTAN 2.0) cannot be handled without this
                tan_request.decoupled = self.kefiya_login.stored_tan_state_decoupled
                self.fints_connection.init_tan_response = self.fints_connection.send_tan(tan_request, tan)

                # on failure update status and skip
                if self.is_tan_required_and_requested(self.fints_connection.init_tan_response):
                    raise TanInteractionRequired()

                # on success clear stored tan state
                self.__persist_fints_state()

        # After successful login/tan verification fetch available accounts if not already present
        if self.__fetch_fints_accounts() is False:
            raise InitFailedException()

        # Afterwards the controller/connection is ready to go for further operations
        if self.kefiya_login.failed_connection:
            self.kefiya_login.failed_connection = 0
            self.kefiya_login.save()

        self.interactive.show_progress_realtime(
           _("Connection established"), 100, reload=False
        )

    def __init_fints_connection(self):
        """Private: Initialise new fints connection.

        :return: None
        """
        if hasattr(self, "fints_connection"):
            return

        # Inside a fetch session, the logins of one bank access share a single
        # client -- and with it the dialog that client_session() keeps open. A
        # second login of the same access then costs one command instead of a
        # full handshake. Strictly keyed on (BLZ, FinTS login): routing a
        # login's requests through another contract's credentials would read
        # the wrong accounts, so anything else gets its own connection.
        session = _active_session()
        access = _access_key(self.kefiya_login) if session else None
        if access and access in session["connections"]:
            self.fints_connection = session["connections"][access]
            return

        # "TAN once per bank": before opening a brand-new dialog (which would
        # trigger a fresh SCA/TAN), try to reuse an already-authenticated FinTS
        # session from a sibling login of the same bank (same blz + fints_login).
        self._seed_client_state_from_sibling()

        self.interactive.show_progress_realtime(
            _("Initialise connection"), 10, reload=False
        )

        try:
            self.fints_connection = FinTS3PinTanClient(
                self.kefiya_login.blz,
                self.kefiya_login.fints_login,
                self.kefiya_login.get_password("fints_password"),
                self.kefiya_login.fints_url,
                product_id=self.kefiya_login.get_password("product_id"),
                mode=FinTSClientMode.INTERACTIVE,
                from_data=self.kefiya_login.stored_client_blob,
            )
        except Exception as e:
            frappe.throw(
                _("Could not conntect to fints server with error<br>{0}").format(e)
            )

        # Offer it to the rest of the session, so the next login of this access
        # joins this client instead of opening its own.
        if access:
            session["connections"][access] = self.fints_connection

    @contextlib.contextmanager
    def client_session(self):
        """Open a FinTS dialog, join the open one, or leave it open.

        Three cases. A dialog is already standing on this client: join it, and
        leave closing to whoever opened it. A fetch session is active: open the
        dialog and hand it to the session, which keeps it open for every
        further command and closes it at the end. Neither: open and close it
        here, exactly as before this existed.

        Every read below used to open the client directly, and
        FinTS3PinTanClient refuses to be entered twice ("Cannot double
        __enter__"). One dialog per command means an HKIDN/HKVVB round trip
        plus authentication plus an HKEND for every single command -- which is
        where nearly all the time of a fetch goes. The data itself is one
        message; the handshake around it is four.

        Joining an already-open dialog lets a caller wrap a whole login, or a
        whole bank access, in one dialog and pay that cost once. Nothing
        changes for callers that do not: with no standing dialog this behaves
        exactly as before.

        Deliberately not used by the money paths (submit_sepa_transfer,
        submit_sepa_debit). Those park the dialog on a TAN request, and
        freezing a dialog that a surrounding fetch is still using would break
        it.
        """
        conn = self.fints_connection
        session = _active_session()

        if conn._standing_dialog:
            # Joining a dialog somebody else opened. Inside a session that is
            # the normal case -- every command after the first lands here, and
            # so does every login of the access after the first -- so a failure
            # has to retire the connection exactly as the opener below does.
            # Without that, a TAN request parks the dialog and leaves it
            # registered, and the next command sends on a frozen dialog:
            # "Cannot send() on a paused dialog", for every remaining account
            # of that bank.
            #
            # With no session the dialog belongs to a surrounding `with conn:`
            # that will clean up after itself. Retiring it here would close a
            # dialog still in use.
            if session is None:
                yield conn
                return

            try:
                yield conn
            except Exception as exc:
                if not _is_unsupported_operation(exc):
                    _retire_connection(session, conn)
                raise
            return

        if session is None:
            with conn:
                yield conn
            return

        try:
            conn.__enter__()
        except Exception:
            # A dialog whose init failed -- wrong credentials, bank in
            # maintenance -- leaves _standing_dialog set but never opened.
            # python-fints then reads that as "a dialog is standing", so the
            # next login of this access would join a dialog that is dead, and
            # every command on it would fail. One bad handshake would take the
            # whole access down for the rest of the run. Take it out of the
            # session so the next controller starts clean.
            _retire_connection(session, conn)
            raise

        session["open"].append(conn)
        try:
            yield conn
        except Exception as exc:
            # Anything but an unsupported segment may have left the dialog
            # broken or parked, and every later command in this session would
            # inherit it.
            if not _is_unsupported_operation(exc):
                _retire_connection(session, conn)
            raise

    def _refuse_inside_fetch_session(self):
        """Refuse to move money through a dialog a fetch is sharing.

        A transfer or direct debit parks the dialog on the TAN request
        (pause_dialog). The read paths avoid that by construction: a parked
        dialog is retired from the session so nothing sends on it again. The
        money paths cannot be retired the same way, because parking is their
        SUCCESS case -- they return "tan_required" rather than raising -- so the
        session would keep handing a frozen dialog to every later command.

        Nothing does this today: fetching and transferring are separate
        requests. But since a controller built inside a session adopts the
        shared client, it became possible, and a corrupted collective fetch is
        a far worse outcome than a refused order.
        """
        if _active_session() is not None:
            frappe.throw(_(
                "A SEPA order cannot be sent while a bank fetch is running."
                " Wait for the fetch to finish and send it again."
            ))

    @contextlib.contextmanager
    def trusted_client_context(self):
        """
        Opens the fints client context (will most likely generate a new fints dialog) and checks if a TAN is requested.
        If so, it will be requested from the user and the context body will be skipped.
        """
        with self.client_session():
            if self.is_tan_required_and_requested(self.fints_connection.init_tan_response):
                raise TanInteractionRequired()

            yield self.fints_connection

    def is_tan_required_and_requested(self, response) -> bool:
        """Checks the given response, if a TAN is required. If so, it is requested from the user.
        :param response: The response object from the FinTS server
        :return: True if a TAN is required (and requested), False otherwise
        """
        if isinstance(response, NeedTANResponse):
            self.ask_for_tan(response)
            return True

        return False

    def __persist_fints_state(self, tan_state=None, clear:bool=False):
        """Persist the current client/dialog state to the database.
        :param tan_state: An additional TAN state to persist if given.
        :param clear: Reset all the stored states
        :return: None
        """
        self.kefiya_login.stored_client_blob = self.fints_connection.deconstruct(including_private=True)

        if tan_state and isinstance(tan_state, NeedTANResponse):
            self.kefiya_login.stored_tan_blob = tan_state.get_data()
            self.kefiya_login.stored_tan_state_decoupled = tan_state.decoupled
            self.kefiya_login.stored_dialog_blob = self.fints_connection.pause_dialog()
        else:
            self.kefiya_login.stored_tan_blob = None
            self.kefiya_login.stored_tan_state_decoupled = None
            self.kefiya_login.stored_dialog_blob = None

        self.kefiya_login.save()

        # A clean, TAN-free authenticated state was just persisted -> share it
        # with the sibling logins of the same bank so a single TAN unlocks every
        # account ("TAN once per bank"). Never propagate a state that still
        # carries a pending TAN challenge.
        if not (tan_state and isinstance(tan_state, NeedTANResponse)):
            self._propagate_client_state_to_siblings()

    def _sibling_login_filters(self):
        """Filters selecting the OTHER Kefiya Logins that share this login's
        bank credentials (same BLZ + FinTS login) -- i.e. the same online-banking
        access, just mapped to different bank accounts. Returns None when this
        login has no usable credentials yet."""
        blz = self.kefiya_login.blz
        fints_login = self.kefiya_login.fints_login
        if not (blz and fints_login):
            return None
        return {
            "name": ("!=", self.kefiya_login.name),
            "blz": blz,
            "fints_login": fints_login,
        }

    def _seed_client_state_from_sibling(self):
        """If this login has no stored FinTS client state, borrow the freshest
        one from a sibling login of the same bank so a single TAN authorises
        every account of that bank. The encrypted blob is portable because it is
        sealed with the site key, not a per-record salt. In-memory only; it is
        persisted on the next successful __persist_fints_state(). Best-effort --
        on any problem we simply fall back to the normal (per-login) TAN flow."""
        try:
            if self.kefiya_login.stored_client_state:
                return
            filters = self._sibling_login_filters()
            if not filters:
                return
            filters["stored_client_state"] = ("is", "set")
            rows = frappe.get_all(
                "Kefiya Login",
                filters=filters,
                fields=["stored_client_state"],
                order_by="client_state_updated desc",
                limit=1,
            )
            if rows and rows[0].stored_client_state:
                self.kefiya_login.stored_client_state = rows[0].stored_client_state
        except Exception:
            frappe.log_error(
                title="Kefiya: seed client state from sibling failed",
                message=frappe.get_traceback(),
            )

    def _propagate_client_state_to_siblings(self):
        """Share this login's freshly authenticated FinTS client state with the
        sibling logins of the same bank that have no state yet (or an older one),
        so one TAN unlocks every account. Best-effort; never raises."""
        try:
            filters = self._sibling_login_filters()
            state = self.kefiya_login.stored_client_state
            mine = self.kefiya_login.client_state_updated
            if not (filters and state):
                return
            siblings = frappe.get_all(
                "Kefiya Login",
                filters=filters,
                fields=["name", "stored_client_state", "client_state_updated",
                        "stored_tan_state", "stored_dialog_state"],
            )
            for s in siblings:
                # Never pull the client state out from under a parked
                # challenge. A paused dialog belongs to the client state it was
                # frozen with -- message counters, dialog id, signature
                # counter -- so replacing that state leaves the user releasing
                # the payment in their banking app while the resumed dialog no
                # longer fits its client, and the release fails.
                #
                # This went unnoticed until the challenge started surviving at
                # all: before that it was destroyed by the unpacking bug long
                # before a sibling could overwrite anything. The parallel fetch
                # makes it near-certain, because the siblings of one access now
                # run seconds apart.
                if s.stored_tan_state or s.stored_dialog_state:
                    continue

                # keep a sibling's own session if it is at least as fresh
                if s.stored_client_state and mine and s.client_state_updated and s.client_state_updated >= mine:
                    continue
                frappe.db.set_value(
                    "Kefiya Login",
                    s.name,
                    {"stored_client_state": state, "client_state_updated": mine},
                    update_modified=False,
                )
        except Exception:
            frappe.log_error(
                title="Kefiya: propagate client state to siblings failed",
                message=frappe.get_traceback(),
            )

    def __init_tan_mode(self, tan_mode:str=None, tan_medium:str=None, tan:str=...) -> bool:
        """
        Initializes the TAN mode to use. If there are multiple TAN mechanisms available, the user is asked to choose one (if no choise is permitted).

        :param tan_mode: The name of the TAN mechanism to use (choice was already made, if permitted)
        :param tan_medium: The name of the TAN medium (on several devices, ...) to use (choice was already made, if permitted)
        :return bool: Indicates if initialization was complete or should be stopped (because user interaction is required)
        """
        if not self.fints_connection.get_current_tan_mechanism():
            self.interactive.show_progress_realtime(
                _("Initialise TAN settings"), 20, reload=False
            )

            self.fints_connection.fetch_tan_mechanisms()

            mechanisms = self.fints_connection.get_tan_mechanisms().items()

            if len(mechanisms) == 0:
                frappe.throw(_("No TAN mechanisms available"))

            mechanism_names = ["{p.security_function}: {p.name}".format(p=m[1]) for m in mechanisms]

            # If there is only one tan mechanism available, use it without asking
            if len(mechanisms) == 1:
                tan_mode = mechanism_names[0]

            if tan_mode and tan_mode in mechanism_names:
                # set tan mechanism
                selected_mode = list(mechanisms)[mechanism_names.index(tan_mode)]
                self.fints_connection.set_tan_mechanism(selected_mode[0])
            else:
                # request tan mechanism from user
                self.interactive.request_tan_mechanism(mechanism_names)
                return False

        # discover tan medium handling
        if self.fints_connection.selected_tan_medium is None and self.fints_connection.is_tan_media_required():
            m = self.fints_connection.get_tan_media() # this request can already trigger another TAN request, which is not cool, but for other banks this makes more sense hopefully
            medium_names = None

            if len(m[1]) == 1:
                self.fints_connection.set_tan_medium(m[1][0])
            elif len(m[1]) == 0:
                # This is a workaround for when the dialog already contains return code 3955.
                # This occurs with e.g. Sparkasse Heidelberg, which apparently does not require us to choose a
                # medium for pushTAN but is totally fine with keeping "" as a TAN medium.
                self.fints_connection.selected_tan_medium = ""
            elif tan_medium and tan_medium in [mm.tan_medium_name for mm in m[1]]:
                self.fints_connection.set_tan_medium(next(mm for mm in m[1] if mm.tan_medium_name == tan_medium))
            else:
                # Multiple tan media available. Prompt user
                medium_names = []
                for mm in m[1]:
                    medium_names.append("Medium {p.tan_medium_name}: Phone no. {p.mobile_number_masked}, Last used {p.last_use}".format(p=mm))

                self.interactive.request_tan_mechanism([tan_mode], medium_names)
                return False

            # if the request already claimed a tan, persist state and ask for tan
            if self.fints_connection.init_tan_response and self.fints_connection._standing_dialog:
                # (Only!) If the tan request opened a dialog, which can be paused for later (continue after user-interaction)
                # If not, it needs to be skipped (leads to multiple requests on the phone, but there is now option to persist the state, and it works)
                self.ask_for_tan(self.fints_connection.init_tan_response, possible_tan_modes=[tan_mode], possible_tan_mediums=medium_names)
                return False

        return True

    def ask_for_tan(self, response, *, decoupled=None, possible_tan_modes=None, possible_tan_mediums=None):
        if response:
            self.__persist_fints_state(response)

        if response.decoupled if decoupled is None else decoupled:
            self.interactive.request_mfa_confirmation(possible_tan_modes=possible_tan_modes, possible_tan_mediums=possible_tan_mediums)
        else:
            self.interactive.request_tan(possible_tan_modes=possible_tan_modes, possible_tan_mediums=possible_tan_mediums)

    def __fetch_fints_accounts(self) -> bool:
        """Fetch FinTS Accounts.

        :return: True on success. False or an exception otherwise.
        """
        if hasattr(self, 'fints_accounts'):
            return True

        if self.kefiya_login.iban_list:
            cached_accounts = json.loads(self.kefiya_login.iban_list)
            if cached_accounts and isinstance(cached_accounts[0], dict):
                self.fints_accounts = [frappe._dict(acc) for acc in cached_accounts]
                return True

        try:
            with self.trusted_client_context() as client:
                self.interactive.show_progress_realtime(
                    _("Loading accounts"), 30, reload=False
                )

                accounts_response = client.get_sepa_accounts()
                if self.is_tan_required_and_requested(accounts_response):
                    return False

                self.fints_accounts = accounts_response
                self.kefiya_login.iban_list = json.dumps(
                    [a.iban for a in self.fints_accounts if getattr(a, "iban", None)]
                )

                # Reading the accounts is part of the first initialization. So after this was successful, the
                # client state can be persisted for future use.
                self.__persist_fints_state()

                self.interactive.show_progress_realtime(
                    _("Loading accounts completed"), 100, reload=True
                )
                return True

        except TanInteractionRequired:
            raise
        except Exception as e:
            frappe.throw(_(
                "Could not load sepa accounts with error:<br>{0}"
            ).format(e))

        return False

    def __get_fints_account_by_key(self, key, value):
        if not value:
            return None

        for acc in self.fints_accounts:
            if isinstance(acc, dict):
                if acc.get(key) == value:
                    return acc
            else:
                try:
                    if getattr(acc, key) == value:
                        return acc
                except AttributeError:
                    frappe.throw(_(
                        "SEPA account object has no key '{0}'"
                    ).format(key))

        # Account can be None
        return None


    @staticmethod
    def get_kefiya_import_file_content(kefiya_import):
        """Get Kefiya Import json file content as json.

        :param kefiya_import: kefiya_import doc
        :type kefiya_import: kefiya_import doc
        :return: Transaction from file as json object list
        """
        if kefiya_import.file_url:
            content = get_file(kefiya_import.file_url)[1]
            # Check content hash for file manipulations
            if kefiya_import.file_hash == get_content_hash(content):
                return json.loads(
                    content,
                    strict=False
                )
            else:
                raise ValueError('File hash does not match')
        else:
            return []

    def get_fints_connection(self):
        """Get the FinTS Connection object.

        :return: FinTS3PinTanClient
        """
        return self.fints_connection

    def get_fints_accounts(self):
        """Get FinTS Accounts.

        :return: List of SEPAAccount objects.
        """
        return self.fints_accounts

    def get_fints_account_by_iban(self, iban):
        """Get FinTS account by iban number.

        :param iban: bank iban number
        :type iban: str
        :return: SEPAAccount
        """
        return self.__get_fints_account_by_key("iban", iban)

    def _get_transactions_raw(self, account, start_date, end_date,
                              include_pending=False):
        """python-fints' ``get_transactions()``, but keeping a TAN challenge.

        The library unpacks the camt result into (booked, pending) and therefore
        dies with "cannot unpack non-iterable NeedTANResponse object" as soon as
        the bank answers the statement request with a TAN challenge instead of
        the data -- and the challenge object dies with it. Without it neither a
        TAN nor a decoupled confirmation can ever be completed, so the login is
        stuck for good.

        Mirroring the library internals here is the same approach
        ``get_fints_balance`` already takes for HKSAL, for the same reason: the
        public method throws information away that we need. Should a future
        library version rename those internals, we fall back to the public call
        and are no worse off than before.

        :return: the transaction list, or the NeedTANResponse to act on
        """
        conn = self.fints_connection
        try:
            from fints.camt_parser import camt053_to_dict
            from fints.exceptions import FinTSUnsupportedOperation
            from fints.models import Transaction
            from fints.segments.statement import (
                HKCAZ1, HKKAZ5, HKKAZ6, HKKAZ7)

            get_dialog = conn._get_dialog
            find_command = conn._find_highest_supported_command
            fetch_mt940 = conn._get_transactions_mt940
            fetch_xml = conn._get_transactions_xml
        except (AttributeError, ImportError):
            return conn.get_transactions(
                account, start_date, end_date, include_pending)

        with get_dialog() as dialog:
            try:
                hkkaz = find_command(HKKAZ5, HKKAZ6, HKKAZ7)
                # MT940 banks return the challenge instead of the statements;
                # it is passed through untouched for the caller to handle.
                return fetch_mt940(
                    dialog, hkkaz, account, start_date, end_date,
                    include_pending)
            except FinTSUnsupportedOperation:
                hkcaz = find_command(HKCAZ1)
                result = fetch_xml(
                    dialog, hkcaz, account, start_date, end_date)
                if isinstance(result, NeedRetryResponse):
                    return result
                streams = [x for x in result[0] if x]
                if include_pending:
                    # python-fints appends seg.statement_pending unfiltered, so
                    # a bank that sends no pending block yields [None] -- which
                    # is truthy. camt053_to_dict(None) then dies on the parser,
                    # the shared dialog is retired, and every later command of
                    # that login fails with "could not fetch BPD". One missing
                    # optional field took out holdings and statements too.
                    streams += [x for x in (result[1] or []) if x]
                return [
                    Transaction(txn)
                    for stream in streams
                    for txn in camt053_to_dict(stream)
                ]

    def _get_transactions_checked(self, account, start_date, end_date):
        """Fetch transactions, turning a mid-fetch TAN request into a TAN flow.

        When the bank's strong authentication has expired -- PSD2 requires it
        every 90 days -- it answers the statement request with a challenge
        instead of the data. Parking that challenge (exactly as the dialog-level
        TAN handling does) is what lets the user finish the authentication and
        fetch again.

        Which prompt is correct depends on the bank: a decoupled login
        (pushTAN 2.0, as the Volksbank uses) is released in the banking app and
        never produces a code to type in, so asking for "the TAN" there sends
        the user looking for something that does not exist.
        """
        response = self._get_transactions_raw(account, start_date, end_date)

        if not isinstance(response, NeedTANResponse):
            return response

        decoupled = bool(getattr(response, "decoupled", False))

        # Park the challenge and publish the matching prompt. Guarded: the
        # scheduler runs with no UI attached, and this error path must not fail
        # on its own -- the TanInteractionRequired below has to reach the caller
        # either way.
        try:
            self.ask_for_tan(response, decoupled=decoupled)
        except Exception:
            frappe.log_error(
                title="Kefiya: parking mid-fetch TAN failed",
                message=frappe.get_traceback(),
                reference_doctype="Kefiya Login",
                reference_name=self.kefiya_login.name,
            )

        if decoupled:
            raise TanInteractionRequired(_(
                "{0}: the bank is waiting for the release in your banking app."
                " Confirm it there and fetch again -- this login uses a"
                " decoupled procedure and issues no TAN to type in."
            ).format(self.kefiya_login.name))

        raise TanInteractionRequired(_(
            "{0}: the bank requires a TAN before transactions can be read."
            " Enter the TAN in the prompt and fetch again."
        ).format(self.kefiya_login.name))

    def _require_fints_account(self, iban=None):
        """Resolve the login's FinTS account, or fail with a usable message.

        python-fints dereferences ``account.iban`` unguarded, so handing it a
        None surfaces as a bare "'NoneType' object has no attribute 'iban'"
        with no hint at which login is misconfigured. That applies to every
        operation below -- balance, holdings, statements, credit card, and the
        money-moving transfer and debit paths alike -- so resolve centrally
        rather than guarding each call site. Typical cause: an account that
        carries no IBAN at all (credit cards), which cannot be addressed this
        way at all.

        :param iban: IBAN to look up; defaults to the login's account IBAN
        :return: the matching SEPAAccount (never None)
        """
        if iban is None:
            iban = self.kefiya_login.account_iban

        account = self.get_fints_account_by_iban(iban)
        if account is not None:
            return account

        # `fints_accounts` is only set once __fetch_fints_accounts() succeeded;
        # read it defensively, since this is the error path and must not raise
        # an AttributeError of its own while reporting another failure.
        offered = []
        for acc in (getattr(self, "fints_accounts", None) or []):
            value = acc.get("iban") if isinstance(acc, dict) \
                else getattr(acc, "iban", None)
            offered.append(_mask_iban(value))

        # A collective bank access can offer dozens of accounts; printing all
        # forty of them turns one misconfigured login into an unreadable wall of
        # text in the Error Log. Enough to recognise the access, not more.
        shown = offered[:OFFERED_IBAN_PREVIEW]
        rest = len(offered) - len(shown)
        if rest > 0:
            shown.append(_("and {0} more").format(rest))

        frappe.throw(_(
            "No FinTS account matching IBAN {0} for login {1}. "
            "The bank offered: {2}. Accounts without an IBAN "
            "(e.g. credit cards) cannot be fetched this way."
        ).format(
            _mask_iban(iban),
            self.kefiya_login.name,
            ", ".join(shown) or "<none>",
        ))

    def get_fints_account_by_nr(self, account_nr):
        """Get FinTS account by account number.

        :param account_nr: bank account number
        :type account_nr: str
        :return: SEPAAccount
        """
        return self.__get_fints_account_by_key(
            "accountnumber",
            account_nr
        )

    def get_fints_transactions(self, start_date=None, end_date=None):
        """Get FinTS transactions.

        The fetch window is limited to the login's allowed_sync_days_in_past
        (default 90). Also only transaction from atleast one day ago can be
        fetched

        :param start_date: Date to start the fetch
        :param end_date: Date to end the fetch
        :type start_date: date
        :type end_date: date
        :return: Transaction as json object list
        """
        allowed_days = cint(self.kefiya_login.allowed_sync_days_in_past) or 90

        if start_date is None:
            start_date = now_datetime().date() - relativedelta(days=allowed_days)

        if end_date is None:
            end_date = now_datetime().date() - relativedelta(days=1)

        if (now_datetime().date() - start_date).days > allowed_days:
            raise NotImplementedError(
                _("Start date is more than the allowed {0} days in the past").format(
                    allowed_days
                )
            )

        with self.client_session():
            account = self._require_fints_account()
            return json.loads(
                json.dumps(
                    self._get_transactions_checked(
                        account,
                        start_date,
                        end_date
                    ),
                    cls=mt940.JSONEncoder
                )
            )

    def get_fints_pending_transactions(self, start_date=None, end_date=None):
        """Fetch the entries the bank shows as pending (vorgemerkte Umsaetze).

        The bank delivers them in the same MT940/camt message as the booked
        ones, in a separate field, and python-fints only returns them when
        asked -- ``include_pending``. The booked fetch deliberately leaves it
        off: a pending entry is not a booking and must not reach the ledger.

        This asks for both and returns the difference, because the library has
        no "pending only" call. Cheap: it is one more command on a dialog that
        is already open, not a second handshake.

        :return: list of entries the bank has not booked yet
        """
        allowed_days = cint(self.kefiya_login.allowed_sync_days_in_past) or 90
        if start_date is None:
            start_date = now_datetime().date() - relativedelta(days=allowed_days)
        if end_date is None:
            end_date = now_datetime().date()

        with self.client_session():
            account = self._require_fints_account()

            # Through _get_transactions_raw, not the library's public call:
            # that one dies on the camt unpacking as soon as the bank answers
            # with a TAN challenge, which is the bug this app already fixed
            # once. No reason to reintroduce it here.
            booked = self._get_transactions_raw(
                account, start_date, end_date, include_pending=False)
            both = self._get_transactions_raw(
                account, start_date, end_date, include_pending=True)

        if isinstance(booked, NeedRetryResponse) \
                or isinstance(both, NeedRetryResponse):
            # A TAN request here is not worth interrupting the fetch for: the
            # booked transactions are the point, and they already went through.
            return []

        booked_keys = {self._pending_key(t) for t in (booked or [])}
        return [t for t in (both or [])
                if self._pending_key(t) not in booked_keys]

    @staticmethod
    def _pending_key(entry):
        """Identify an entry well enough to tell booked from pending apart."""
        data = entry if isinstance(entry, dict) else getattr(entry, "data", None)
        if not isinstance(data, dict):
            try:
                data = dict(entry)
            except Exception:
                return repr(entry)
        return "|".join(str(data.get(k, "")) for k in
                        ("date", "amount", "purpose", "applicant_name"))

    def get_fints_holdings(self):
        """Fetch securities holdings (Depot / Wertpapiere) for the account.

        :return: list of plain dicts (isin, security_name, quantity, price,
            market_value, currency, valuation_date, securities_account)
        """
        with self.client_session():
            account = self._require_fints_account()
            holdings = self.fints_connection.get_holdings(account)
            result = []
            for h in holdings or []:
                result.append({
                    "isin": getattr(h, "isin", None),
                    "security_name": getattr(h, "name", None),
                    "quantity": getattr(h, "pieces", None),
                    "price": getattr(h, "market_value", None),
                    "market_value": getattr(h, "total_value", None),
                    "currency": getattr(h, "value_symbol", None),
                    "valuation_date": getattr(h, "valuation_date", None),
                    "securities_account": self.kefiya_login.account_iban,
                })
            return result

    @staticmethod
    def _amount_from(amount_field):
        """Read the numeric value of an HISAL Amount1 field group (or None)."""
        if not amount_field:
            return None
        try:
            return amount_field.amount
        except Exception:
            return None

    def get_fints_balance(self):
        """Fetch the current account balance INCLUDING the credit line
        (Kreditlinie) and the available amount.

        python-fints' high-level ``get_balance()`` only surfaces the booked
        balance; the credit line and available amount live on the HISAL response
        segment (fields ``line_of_credit`` / ``available_amount``). We therefore
        send HKSAL ourselves -- mirroring python-fints' own ``get_balance``
        internals -- and read those extra fields. TAN handling is delegated to
        the client's ``_send_with_possible_retry`` just like a statement fetch.

        :return: list of dicts, one per HISAL segment:
            {iban, currency, balance, balance_date, line_of_credit,
             available_amount}
        """
        from fints.segments.saldo import HKSAL5, HKSAL6, HKSAL7

        conn = self.fints_connection
        iban = self.kefiya_login.account_iban

        def _extract(command_seg, response):
            rows = []
            for hisal in response.response_segments(command_seg, "HISAL"):
                balance = None
                # The booked balance carries the date it refers to. Without it
                # a running balance on the bookings has no anchor: "the balance
                # after this transaction" is only true if we know which
                # transactions the bank had already counted.
                balance_date = None
                try:
                    booked = hisal.balance_booked.as_mt940_Balance()
                    balance = booked.amount.amount
                    balance_date = getattr(booked, "date", None)
                except Exception:
                    balance = None
                rows.append({
                    "iban": iban,
                    "currency": getattr(hisal, "currency", None),
                    "balance": balance,
                    "balance_date": balance_date,
                    "line_of_credit": self._amount_from(
                        getattr(hisal, "line_of_credit", None)),
                    "available_amount": self._amount_from(
                        getattr(hisal, "available_amount", None)),
                })
            return rows

        with self.client_session():
            account = self._require_fints_account(iban)
            with conn._get_dialog() as dialog:
                hksal = conn._find_highest_supported_command(
                    HKSAL5, HKSAL6, HKSAL7)
                seg = hksal(
                    account=hksal._fields["account"].type.from_sepa_account(
                        account),
                    all_accounts=False,
                )
                return conn._send_with_possible_retry(dialog, seg, _extract)

    def get_fints_information(self):
        """Bank + account capabilities, limits and supported operations
        (FinTS get_information). Returns a nested dict."""
        with self.client_session():
            return self.fints_connection.get_information()

    def get_fints_scheduled_debits(self, multiple=False):
        """Standing orders / scheduled debits (Dauerauftraege /
        Termin-Ueberweisungen) for the login's account."""
        with self.client_session():
            account = self._require_fints_account()
            return self.fints_connection.get_scheduled_debits(account, multiple)

    def get_fints_statements(self):
        """List available electronic account statements
        (elektronische Kontoauszuege / Dokumente)."""
        with self.client_session():
            account = self._require_fints_account()
            return self.fints_connection.get_statements(account)

    def get_fints_statement(self, number=None, year=None, file_format=None):
        """Fetch one specific electronic account statement document (HIEKA).

        May return binary content (e.g. PDF); the caller decides how to store it.
        """
        with self.client_session():
            account = self._require_fints_account()
            return self.fints_connection.get_statement(
                account, number, year, file_format)

    def get_fints_credit_card_transactions(self, credit_card_number=None,
                                           start_date=None, end_date=None):
        """Credit card transactions (Kreditkartenumsaetze) for the account."""
        with self.client_session():
            account = self._require_fints_account()
            return self.fints_connection.get_credit_card_transactions(
                account, credit_card_number, start_date, end_date)

    def get_fints_transactions_xml(self, start_date=None, end_date=None):
        """Fetch transactions as camt XML (richer than MT940: full structured
        remittance info / references). Returns the raw camt document streams."""
        allowed_days = cint(self.kefiya_login.allowed_sync_days_in_past) or 90
        if start_date is None:
            start_date = now_datetime().date() - relativedelta(days=allowed_days)
        if end_date is None:
            end_date = now_datetime().date() - relativedelta(days=1)
        with self.client_session():
            account = self._require_fints_account()
            return self.fints_connection.get_transactions_xml(
                account, start_date, end_date)

    def get_fints_status_protocol(self):
        """Bank status protocol messages (Statusprotokoll / diagnostics)."""
        with self.client_session():
            return self.fints_connection.get_status_protocol()

    def get_fints_communication_endpoints(self):
        """Available bank communication endpoints (diagnostics)."""
        with self.client_session():
            return self.fints_connection.get_communication_endpoints()

    def submit_sepa_debit(self, pain008_xml):
        """Collect a SEPA direct debit (Lastschrift, pain.008) via FinTS.

        Mirrors submit_sepa_transfer: requires a TAN, never pulls money without
        the user's TAN. The caller must supply a valid pain.008 message backed by
        a SEPA mandate. INTENTIONALLY NOT whitelisted -- money collection must be
        driven by a guarded flow (explicit confirmation + write permission +
        mandate check), analogous to submit_payment_request_via_fints. VoP
        (Verification of Payee) mismatches must be resolved by a human, never
        auto-approved.
        """
        self._refuse_inside_fetch_session()

        with self.fints_connection:
            account = self._require_fints_account()
            response = self.fints_connection.sepa_debit(account, pain008_xml)
            if self.is_tan_required_and_requested(response):
                return {
                    "status": "tan_required",
                    "docname": self.kefiya_login.name,
                }
            frappe.log_error(
                title="Kefiya SEPA debit completed without TAN challenge",
                message="login={0}: the bank did not request a TAN".format(
                    self.kefiya_login.name
                ),
            )
            return {"status": "submitted"}

    def _vop_mismatch(self, response):
        """Return VoP (Verification of Payee) result details if the bank flagged
        a payee name/IBAN mismatch on this response, else None.

        Defensive: python-fints versions without VoP support have no
        NeedVOPResponse class, so this is a safe no-op there and the transfer
        proceeds exactly as before.
        """
        try:
            from fints.client import NeedVOPResponse
        except Exception:
            return None
        if isinstance(response, NeedVOPResponse):
            try:
                return _to_jsonable(getattr(response, "vop_result", None))
            except Exception:
                return {"vop": "mismatch"}
        return None

    def _persist_vop_state(self, response, vop_result, payment_reference=None):
        """Park a Verification-of-Payee challenge for later human release.

        NeedVOPResponse is a NeedRetryResponse, so it survives a round trip
        through the database exactly like a pending TAN: store the challenge
        plus the paused dialog, and the reviewer can resume and approve it in
        a later request.
        """
        self.kefiya_login.stored_vop_blob = response.get_data()
        self.kefiya_login.stored_vop_dialog_blob = \
            self.fints_connection.pause_dialog()
        self.kefiya_login.vop_reference = payment_reference
        try:
            self.kefiya_login.vop_result = json.dumps(vop_result)[:2000]
        except Exception:
            self.kefiya_login.vop_result = str(vop_result)[:2000]
        self.kefiya_login.save()

    def approve_pending_vop(self, instant_payment=False):
        """Release a parked VoP mismatch after a human reviewed the payee.

        This is the deliberate counterpart to refusing the transfer in
        submit_sepa_transfer: the bank could not confirm that payee name and
        IBAN belong together, a reviewer checked it against the invoice, and
        only now is the order approved. Callers must gate this on an explicit
        confirmation -- it is the step that lets the money leave.

        :return: {"status": "submitted" | "tan_required" | "error", ...}
        """
        blob = self.kefiya_login.stored_vop_blob
        dialog_blob = self.kefiya_login.stored_vop_dialog_blob
        if not (blob and dialog_blob):
            return {
                "status": "error",
                "message": _("No pending Verification of Payee for this login."),
            }

        self._refuse_inside_fetch_session()

        with self.fints_connection.resume_dialog(dialog_blob):
            challenge = NeedRetryResponse.from_data(blob)
            response = self.fints_connection.approve_vop_response(challenge)

            # The challenge is spent either way -- approved orders must never be
            # replayable, and a failure needs a fresh transfer, not a retry of a
            # stale dialog.
            self.kefiya_login.clear_vop_state()
            self.kefiya_login.save()

            if self.is_tan_required_and_requested(response):
                return {
                    "status": "tan_required",
                    "docname": self.kefiya_login.name,
                }

            frappe.log_error(
                title="Kefiya SEPA transfer approved via VoP without TAN",
                message="login={0}: the bank did not request a TAN after the "
                        "Verification-of-Payee approval".format(
                            self.kefiya_login.name),
            )
            return {"status": "submitted"}

    def submit_sepa_transfer(self, pain_xml, instant_payment=False,
                             payment_reference=None, multiple=False,
                             control_sum=None):
        """Submit a SEPA credit transfer (pain.001 XML) via FinTS.

        Requires a TAN: if the bank asks for one, the request is persisted and
        the UI is prompted (the user later calls send_transfer_tan). Never sends
        money without the user's TAN.

        :param pain_xml: pain.001 credit-transfer message
        :param instant_payment: if truthy, send as SEPA Instant / real-time
            credit transfer (Echtzeitueberweisung, FinTS HKIPZ) instead of a
            regular transfer (HKCCS). The debtor bank + account must support
            instant payments, otherwise the bank rejects the order.
        :param multiple: send as a collective order (HKCCM) -- one order
            carrying many payments, authorised by a single TAN. Without this a
            payment run needs one TAN per payment.
        :param control_sum: total of all payments, which the bank checks a
            collective order against. Required by the standard whenever
            ``multiple`` is set.
        :return: {"status": "submitted" | "tan_required", ...}
        """
        instant_payment = bool(cint(instant_payment))
        multiple = bool(cint(multiple))
        if multiple and control_sum is None:
            frappe.throw(_(
                "A collective transfer requires a control sum."
            ))

        kwargs = {"instant_payment": instant_payment}
        if multiple:
            # Only pass these for a collective order: banks reject a control
            # sum on a single transfer.
            kwargs["multiple"] = True
            kwargs["control_sum"] = control_sum

        self._refuse_inside_fetch_session()

        with self.fints_connection:
            account = self._require_fints_account()
            response = self.fints_connection.sepa_transfer(
                account, pain_xml, **kwargs)
            vop = self._vop_mismatch(response)
            if vop is not None:
                # Verification of Payee mismatch: the bank could not confirm the
                # payee name matches the IBAN. NEVER auto-approve this -- money is
                # not sent; a Sachbearbeiter must review/correct the payee name.
                # Park the challenge so a reviewer can release it deliberately
                # via approve_pending_vop(); without this the transfer is a dead
                # end and has to be started over.
                self._persist_vop_state(response, vop, payment_reference)
                return {
                    "status": "vop_mismatch",
                    "docname": self.kefiya_login.name,
                    "vop_result": vop,
                }
            if self.is_tan_required_and_requested(response):
                return {
                    "status": "tan_required",
                    "docname": self.kefiya_login.name,
                }
            # The bank accepted the order without asking for a TAN. For a credit
            # transfer this is unexpected under PSD2 -- record it loudly so a
            # transfer that moved money without strong auth is never silent.
            frappe.log_error(
                title="Kefiya SEPA transfer completed without TAN challenge",
                message="login={0}: the bank did not request a TAN".format(
                    self.kefiya_login.name
                ),
            )
            return {"status": "submitted"}

    def import_fints_transactions(self, kefiya_import):
        """Create payment entries by FinTS transactions.

        :param kefiya_import: kefiya_import doc name
        :type kefiya_import: str
        :return: List of max 10 transactions and all new payment entries
        """
        try:
            self.interactive.show_progress_realtime(
                _("Start transaction import"), 40, reload=False
            )
            curr_doc = frappe.get_doc("Kefiya Import", kefiya_import)
            new_bank_transactions = None

            # Incremental fetch: when no start date was entered, begin at the
            # date of the most recently imported transaction for this account
            # (clamped to the FinTS 90-day window) and fetch up to today.
            if not curr_doc.from_date:
                curr_doc.from_date = resolve_incremental_from_date(
                    self.kefiya_login.bank_account,
                    self.kefiya_login.allowed_sync_days_in_past,
                )
                curr_doc.to_date = now_datetime().date()

            tansactions = self.get_fints_transactions(
                curr_doc.from_date,
                curr_doc.to_date
            )

            # normalise: some banks (e.g. Atruvia/VR) return a list of
            # statements (list of lists); others (Finanz Informatik) return a
            # flat list of transaction dicts. Flatten one nesting level so the
            # downstream code (start/end date, old_kefiya_import) always sees a
            # flat list of transactions.
            flat_transactions = []
            for statement in tansactions:
                if isinstance(statement, list):
                    flat_transactions.extend(statement)
                else:
                    flat_transactions.append(statement)
            tansactions = flat_transactions
            
            if(len(tansactions) == 0):
                frappe.msgprint(_("No transaction found"))
            else:
                try:
                    save_file(
                        kefiya_import + ".json",
                        json.dumps(
                            tansactions, ensure_ascii=False
                        ).replace(",", ",\n").encode('utf8'),
                        'Kefiya Import',
                        kefiya_import,
                        folder='Home/Attachments/FinTS',
                        decode=False,
                        is_private=1,
                        df=None
                    )
                except Exception as e:
                    frappe.throw(_("Failed to attach file"), e)

                curr_doc.start_date = tansactions[0]["date"]
                curr_doc.end_date = tansactions[-1]["date"]

                importer = ImportBankTransaction(self.kefiya_login, self.interactive)
                # Banks differ in transaction format: Atruvia/VR deliver CAMT
                # (ISO 20022, recognisable by the CreditDebitIndicator field),
                # Finanz Informatik (Sparkasse, LBBW) deliver MT940. Route each
                # set to the matching parser.
                if tansactions and isinstance(tansactions[0], dict) and "CreditDebitIndicator" in tansactions[0]:
                    importer.kefiya_import(tansactions)
                else:
                    importer.old_kefiya_import(tansactions)

                if len(importer.bank_transactions) == 0:
                    frappe.msgprint(_("No new payments found"))
                else:
                    # Save payment entries
                    frappe.db.commit()

                    frappe.msgprint(_(
                        "Found a total of '{0}' payments"
                    ).format(
                        len(importer.bank_transactions)
                    ))
                new_bank_transactions = importer.bank_transactions

            curr_doc.submit()
            self.interactive.show_progress_realtime(
                _("Bank Transaction import completed"), 100, reload=False
            )

            # Make the import durable before reconciliation runs, so a rollback
            # inside reconciliation can never revert the submitted import.
            frappe.db.commit()

            # Optional automatic reconciliation of the freshly imported window
            # (guarded so it can never break the import).
            try:
                run_after_import(
                    self.kefiya_login.name, curr_doc.from_date, curr_doc.to_date
                )
            except Exception:
                frappe.log_error(
                    title="Kefiya auto-reconcile entrypoint failed",
                    message=frappe.get_traceback(),
                )

            # auto_assignment = AssignmentController().auto_assign_payments()
            return {
                "transactions": tansactions,
                "payments": new_bank_transactions,
                # "assignment": auto_assignment
            }
        except TanInteractionRequired:
            # Not a parsing error: the bank wants the session authenticated
            # first. Wrapping it in a ValidationError hid that from every
            # caller -- fetch_all's "tan_required" branch never matched, so the
            # request failed and Frappe rolled back the challenge that had just
            # been parked on the login. The user then confirmed a release in
            # the banking app that no longer had anything to release. Let it
            # through unchanged.
            raise
        except Exception as e:
            frappe.throw(_(
                "Error parsing transactions<br>{0}"
            ).format(str(e)), frappe.get_traceback())


class FinTSInteractive:
    def __init__(self, configuration):
        if not configuration:
            self.docname = None
            self.enabled = False
        else:
            self.docname = configuration["docname"]
            self.enabled = configuration["enabled"]
        self.progress = 0

    def set_interactive_mode(self, enable):
        """Turn on/off interactive mode.

        :param enable: Turn on/off interactive mode
        :type enable: bool
        :return: None
        """
        self.enabled = enable

    def get_interactive_mode(self):
        """Get interactive mode.

        :return: bool
        """
        return self.enabled

    def show_progress_realtime(self, message, progress, reload=False):
        """Show a progressbar on client side.

        :param message: Message to display under the bar
        :param progress: 0 - 100
        :param reload: Reload the doc form, , defaults to False
        :type message: str
        :type progress: int
        :type reload: bool, optional
        :return: None
        """
        if self.enabled:
            frappe.publish_realtime(
                "fints_progressbar", {
                    "progress": progress,
                    "docname": self.docname,
                    "message": message,
                    "reload": reload
                }, user=frappe.session.user)

    def request_tan_mechanism(self, possible_tan_modes=None, possible_tan_mediums=None):
        """Request tan mechanism from user.

        :param possible_tan_modes: List of tan mechanisms
        :type mechanisms: list
        :return: None
        """
        self.request_tan_prompt(possible_tan_modes, possible_tan_mediums)

    def request_tan(self, possible_tan_modes=None, possible_tan_mediums=None):
        """Request a TAN from user

        :return: None
        """
        self.request_tan_prompt(possible_tan_modes, possible_tan_mediums, request_tan=True)

    def request_mfa_confirmation(self, possible_tan_modes=None, possible_tan_mediums=None):
        """Request a solved MFA challenge from the user

        :return: None
        """
        self.request_tan_prompt(possible_tan_modes, possible_tan_mediums, request_mfa_confirmation=True)

    def request_tan_prompt(self, possible_tan_modes, possible_tan_mediums=None, *, request_tan=False, request_mfa_confirmation=False):
        """Request tan mechanism from user.

        :param possible_tan_modes: List of tan mechanisms
        :type mechanisms: list
        :return: None
        """
        if self.enabled:
            params = {
                        "docname": self.docname,
                        "possible_tan_modes": possible_tan_modes,
                        "possible_tan_mediums": possible_tan_mediums,
                    }

            if request_tan:
                params["tan_required"] = True

            elif request_mfa_confirmation:
                params["mfa_required"] = True

            frappe.publish_realtime("fints_tan_interaction_required", params, user=frappe.session.user)


def _to_jsonable(value):
    """Best-effort convert a FinTS-lib result into JSON-serialisable data.

    FinTS objects (accounts, statements, standing orders, ...) vary per bank and
    library version and are not always JSON-serialisable; unknown objects are
    stringified so the caller can at least inspect the payload.
    """
    return json.loads(json.dumps(value, default=str))


def _require_login_read(kefiya_login):
    """Ensure the caller may read this Kefiya Login before any bank data is
    fetched. These endpoints expose sensitive account data (balances,
    statements, ...), so a logged-in user must never read a login they cannot
    access. Raises frappe.PermissionError otherwise."""
    frappe.has_permission(
        "Kefiya Login", ptype="read", doc=kefiya_login, throw=True)


@frappe.whitelist()
def get_account_balance(kefiya_login):
    """Fetch the current balance, credit line (Kreditlinie) and available amount
    for a Kefiya Login's account via FinTS (HKSAL).

    Returns a list of dicts (iban, currency, balance, line_of_credit,
    available_amount); persisting/displaying the values is left to the caller.
    Like every FinTS call this may trigger a TAN interaction, which the
    controller handles the same way as a statement fetch.
    """
    _require_login_read(kefiya_login)
    return FinTSController(kefiya_login).get_fints_balance()


@frappe.whitelist()
def get_bank_information(kefiya_login):
    """FinTS get_information: bank name, supported operations, accounts, limits."""
    _require_login_read(kefiya_login)
    return _to_jsonable(FinTSController(kefiya_login).get_fints_information())


@frappe.whitelist()
def get_scheduled_debits(kefiya_login):
    """Standing orders / scheduled debits (Dauerauftraege / Termin-Ueberweisungen)."""
    _require_login_read(kefiya_login)
    return _to_jsonable(
        FinTSController(kefiya_login).get_fints_scheduled_debits())


@frappe.whitelist()
def get_statements(kefiya_login):
    """List of available electronic account statements (Kontoauszuege / Dokumente)."""
    _require_login_read(kefiya_login)
    return _to_jsonable(FinTSController(kefiya_login).get_fints_statements())


@frappe.whitelist()
def get_statement(kefiya_login, number=None, year=None, file_format=None):
    """Fetch one electronic account statement document (HIEKA). May be binary."""
    _require_login_read(kefiya_login)
    return _to_jsonable(
        FinTSController(kefiya_login).get_fints_statement(
            number, year, file_format))


@frappe.whitelist()
def get_credit_card_transactions(kefiya_login, credit_card_number=None):
    """Credit card transactions (Kreditkartenumsaetze)."""
    _require_login_read(kefiya_login)
    return _to_jsonable(
        FinTSController(kefiya_login).get_fints_credit_card_transactions(
            credit_card_number))


@frappe.whitelist()
def get_transactions_camt_xml(kefiya_login, start_date=None, end_date=None):
    """Transactions as camt XML (richer than MT940)."""
    _require_login_read(kefiya_login)
    return _to_jsonable(
        FinTSController(kefiya_login).get_fints_transactions_xml(
            start_date, end_date))


@frappe.whitelist()
def get_status_protocol(kefiya_login):
    """Bank status protocol messages (diagnostics)."""
    _require_login_read(kefiya_login)
    return _to_jsonable(
        FinTSController(kefiya_login).get_fints_status_protocol())


@frappe.whitelist()
def get_communication_endpoints(kefiya_login):
    """Available bank communication endpoints (diagnostics)."""
    _require_login_read(kefiya_login)
    return _to_jsonable(
        FinTSController(kefiya_login).get_fints_communication_endpoints())
