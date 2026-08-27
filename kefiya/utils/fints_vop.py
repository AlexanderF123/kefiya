# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""The one branch python-fints 5.0.0b1 is missing for Verification of Payee.

The Volksbank answers an instant transfer with::

    3040  Es liegen weitere Informationen vor.  (['staticscrollref'])
    3945  Freigabe ohne VOP-Bestaetigung nicht moeglich.

It checked the payee and now wants that check confirmed before it will release
the order. The library sends the check (HKVPP) and reads the answer, but only
turns it into something an application can act on when the check came back
not-applicable, no-match or close-match::

    if vop_result.result in ('RVNA', 'RVNM', 'RVMC'):
        return NeedVOPResponse(...)

A check that SUCCEEDED and still asks to be confirmed falls straight through.
The library's own docstring names that case and calls it "seems related to
something not implemented right now". The order stops there, and nothing
downstream can pick it up: approve_vop_response needs the HIVPP segment AND
the command segment that was sent, and both are local to the method above.

So this subclasses that one method and adds that one branch. Everything else
is the library's, line for line, including the parts that look redundant.

WHY THIS CANNOT SEND TWICE, which is the only question that matters here:

    3945 means the bank did NOT release the order. The added branch turns a
    refusal into a parked challenge -- kefiya answers that with
    vop_pending = 1 and marks nothing as sent. The money moves only when a
    person then approves the payee deliberately, which is the whole point of
    Verification of Payee and the reason it is not automated.

The version guard is not decoration. This mirrors a private method of a beta
library; if that library's shape moves under us, falling back to its own
implementation is strictly better than running a stale copy against a bank.
"""

# frappe is imported where it is used, not here. The rule below -- did the
# bank refuse to release the order without the payee check being confirmed --
# decides what happens to a payment, and it has no business needing a site to
# be exercised. The same reason duplicate_rule and fints_response stand apart
# from the code that queries for them.

#: The release this copy was taken from. Any other one gets the library's own
#: method, unchanged -- a stale copy of a payment path is worse than a missing
#: feature.
KNOWN_GOOD = "5.0.0b1"

#: The bank checked the payee and wants the check confirmed before releasing.
CONFIRMATION_DEMANDED = "3945"


def installed_version():
    """The python-fints release actually installed, or None."""
    try:
        from importlib.metadata import version

        return version("fints")
    except Exception:
        return None


def _pieces():
    """Everything the copied method touches, or None if the shape has moved."""
    try:
        from fints.client import (FinTS3PinTanClient, NeedTANResponse,
                                  NeedVOPResponse)
        # PSRD1 sits in segments.auth, not in formals. Guessing formals from
        # the way client.py uses the bare name cost nothing only because the
        # check below was run against the installed library before shipping:
        # the import would have failed, _pieces() would have answered None,
        # and the branch would have been dead code that reported itself as
        # installed.
        from fints.segments.auth import HIVPP1, HKVPP1, PSRD1
    except Exception:
        return None

    needed = ("_find_vop_format_for_segment", "_need_twostep_tan_for_segment",
              "_get_tan_segment", "is_challenge_structured",
              "_send_pay_with_possible_retry")
    for name in needed:
        if not hasattr(FinTS3PinTanClient, name):
            return None

    return {"base": FinTS3PinTanClient, "NeedTANResponse": NeedTANResponse,
            "NeedVOPResponse": NeedVOPResponse, "PSRD1": PSRD1,
            "HKVPP1": HKVPP1, "HIVPP1": HIVPP1}


def demands_confirmation(response, tan_seg):
    """Did the bank say it will not release this without the confirmation?

    Its own function so the rule can be read and tested without a bank.
    Defensive: a response this cannot read answers False, and the order takes
    exactly the path it took before this module existed.
    """
    try:
        for resp in response.responses(tan_seg):
            if str(getattr(resp, "code", "")) == CONFIRMATION_DEMANDED:
                return True
    except Exception:
        return False
    return False


def client_class():
    """The client class to build a bank connection with.

    The subclass where this is the library it was written against and every
    piece it needs is where it expects it; the library's own class otherwise.
    Never raises -- a bank connection must not fail over an optional branch.
    """
    parts = _pieces()
    if parts is None:
        _note("python-fints does not have the pieces this needs where it"
              " expects them")
        return None

    if installed_version() != KNOWN_GOOD:
        _note("python-fints {0} is installed, not {1}".format(
            installed_version(), KNOWN_GOOD))
        return parts["base"]

    try:
        return _build(parts)
    except Exception:
        import frappe

        frappe.log_error(
            title="Kefiya: could not build the VoP-aware client",
            message=frappe.get_traceback())
        return parts["base"]


def _note(why):
    """Say once, in the Error Log, that transfers lose the added branch."""
    import frappe

    frappe.log_error(
        title="Kefiya: sending without the VoP confirmation branch",
        message=(
            "{0}.\n\nA transfer to a bank that answers 3945 will stop with"
            " 'not sent' until this is looked at. Nothing else is affected."
        ).format(why))


def _build(parts):
    base = parts["base"]
    NeedTANResponse = parts["NeedTANResponse"]
    NeedVOPResponse = parts["NeedVOPResponse"]
    PSRD1 = parts["PSRD1"]
    HKVPP1 = parts["HKVPP1"]
    HIVPP1 = parts["HIVPP1"]

    class VopAwarePinTanClient(base):
        """A client that can also be told "confirm the payee first"."""

        def _send_pay_with_possible_retry(self, dialog, command_seg,
                                          resume_func):
            vop_seg = []
            vop_standard = self._find_vop_format_for_segment(command_seg)
            if vop_standard:
                vop_seg = [HKVPP1(supported_reports=PSRD1(psrd=[vop_standard]))]

            with dialog:
                if self._need_twostep_tan_for_segment(command_seg):
                    tan_seg = self._get_tan_segment(command_seg, '4')
                    segments = vop_seg + [command_seg, tan_seg]

                    response = dialog.send(*segments)

                    if vop_standard:
                        hivpp = response.find_segment_first(HIVPP1, throw=True)
                        vop_result = hivpp.vop_single_result
                        # Not applicable, no match, close match -- the
                        # library's own three, unchanged.
                        #
                        # The fourth case is this class's whole reason for
                        # existing: the check went through and the bank still
                        # wants it confirmed. Same parked challenge, so the
                        # same deliberate approval releases it.
                        if (vop_result.result in ('RVNA', 'RVNM', 'RVMC')
                                or demands_confirmation(response, tan_seg)):
                            return NeedVOPResponse(
                                vop_result=hivpp,
                                command_seg=command_seg,
                                resume_method=resume_func,
                            )
                    else:
                        hivpp = None

                    for resp in response.responses(tan_seg):
                        if resp.code in ('0030', '3955'):
                            return NeedTANResponse(
                                command_seg,
                                response.find_segment_first('HITAN'),
                                resume_func,
                                self.is_challenge_structured(),
                                resp.code == '3955',
                                hivpp,
                            )
                        if resp.code.startswith('9'):
                            raise Exception(
                                "Error response: {!r}".format(response))
                else:
                    response = dialog.send(command_seg)

                return resume_func(command_seg, response)

    return VopAwarePinTanClient
