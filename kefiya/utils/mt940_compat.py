# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Two repairs for the mt940 parser: the pending block, and the Verwendungszweck.

The bank puts a date-and-time indication in the pending block of an MT940
statement (tag :13D:), and the timezone offset in it is optional. The mt940
library's own pattern says so::

    (\\+(?P<offset>\\d{4})|)

A regex group that does not participate still lands in the match dictionary --
with the value None. The parser then decides what to do with it by asking
whether the KEY is there, not whether it has a value::

    elif 'offset' in kwargs:
        tzinfo = FixedOffset(kwargs.pop('offset'))

and FixedOffset does ``int(None)``. So every Sparkasse that sends the pending
block without a timezone crashes the parse with

    TypeError: int() argument must be a string, a bytes-like object or a real
    number, not 'NoneType'

which is what four accounts of one collective run reported under "Vorgemerkt".
The booked block parses fine, which is why only the pending fetch was affected.

The shim below makes the None case mean what the optional group says it means:
no timezone given. It cannot change any behaviour that works today -- the only
thing it replaces is an exception. It is installed once, lazily, and is a
no-op on a library version that has fixed this itself.
"""

try:
    import frappe
except ImportError:  # pragma: no cover - ohne Bench gibt es frappe nicht
    # Dieses Modul muss sich ohne Bench importieren lassen. Sonst kann die
    # Testsuite den ECHTEN Einbau nicht aufrufen und prueft stattdessen eine
    # Kopie davon -- und eine Kopie war nie das, was auf der Instanz lief.
    frappe = None

_INSTALLED = False


def ensure_optional_timezone_is_optional():
    """Install the repair once. Safe to call on every parse.

    :return: True when the parser can handle a missing offset afterwards
    """
    global _INSTALLED
    if _INSTALLED:
        return True

    try:
        from mt940 import models
    except Exception:
        return False

    original = models.DateTime.__new__

    def patched(cls, *args, **kwargs):
        # Only the broken case is touched: the key is present and empty.
        if kwargs.get("offset", "unset") is None:
            kwargs.pop("offset")
        return original(cls, *args, **kwargs)

    try:
        # A library that has fixed this itself needs nothing from us -- check
        # rather than assume, so this quietly retires when it becomes moot.
        models.DateTime(year="26", month="07", day="31", hour="09",
                        minute="00", offset=None)
        _INSTALLED = True
        return True
    except TypeError:
        pass
    except Exception:
        return False

    try:
        models.DateTime.__new__ = patched
        models.DateTime(year="26", month="07", day="31", hour="09",
                        minute="00", offset=None)
    except Exception:
        models.DateTime.__new__ = original
        if frappe is not None:
            frappe.log_error(
                title="Kefiya: could not repair the MT940 date parser",
                message=frappe.get_traceback(),
            )
        return False

    _INSTALLED = True
    return True


_SPACES_INSTALLED = False
#: Einmal je Prozess meckern, nicht bei jedem Abruf. Ohne das schriebe ein
#: Zwanzig-Minuten-Scheduler jede Nacht siebzig gleiche Fehlermeldungen.
_SPACES_COMPLAINED = False


def _beschwerde(grund):
    """Sagt laut, dass die Reparatur nicht greift -- einmal je Prozess.

    Frueher ging das als ``logger().info()`` in eine Datei auf dem Bench. Die
    liest niemand, und am 14.11.2026 war sie von aussen gar nicht erreichbar:
    die Frage "warum klebt der Zweck immer noch" liess sich einen halben Tag
    lang nicht beantworten, obwohl der Code die Antwort kannte. Deshalb ins
    Error Log -- das steht in jeder Oberflaeche und in jeder Schnittstelle.
    """
    global _SPACES_COMPLAINED
    if _SPACES_COMPLAINED:
        return
    _SPACES_COMPLAINED = True
    try:
        from kefiya.utils import mt940_probe
        befund = mt940_probe.was_der_parser_liefert()
    except Exception as fehler:
        befund = "Die Probebuchung lief nicht: " + str(fehler)[:200]
    try:
        frappe.log_error(
            title="Kefiya: Verwendungszweck klebt weiter zusammen",
            message=(
                grund + "\n\n" + befund + "\n\n"
                "Folge: die Teilfelder ?20-?29 des Feldes :86: kommen ohne "
                "Trenner an, auf jedem Rechnungsabschluss und bei jedem "
                "mehrzeiligen Verwendungszweck. Siehe mt940_compat und "
                "verwendungszweck."
            ),
        )
    except Exception:
        pass


def ensure_the_purpose_keeps_its_spaces():
    """Install the Verwendungszweck repair once. Safe to call on every parse.

    Die Teilfelder ``?20`` bis ``?29`` des Feldes :86: setzt die Bibliothek in
    ``_join_result()`` zusammen::

        value = ' '.join(result.get(key, [])) if space else ''.join(...)

    und ``fints.utils.mt940_to_array()`` baut ``Transactions()`` ohne
    Argumente, also mit ``space=False``. Deshalb steht auf jedem
    Rechnungsabschluss dieser Instanz::

        RechnungKosten SRZDauerrechnungsnummer.20250908-BW035-00038612361

    Der Schalter ``space`` gilt fuer den ganzen Lauf, die richtige Antwort
    aber je Buchung: Zeilen der Bank brauchen den Trenner, hart umbrochener
    SEPA-Text darf ihn nicht bekommen. Welcher Fall vorliegt, entscheidet
    verwendungszweck.mit_leerzeichen() an den DK-Schluesselwoertern.

    Angesetzt wird am Eintrag in ``Transactions.DEFAULT_PROCESSORS``, nicht am
    Modulnamen: der Eintrag ist eine direkte Referenz auf die Funktion, und
    jede neue ``Transactions``-Instanz teilt sich dieselbe Liste. Ein Ersatz
    von ``processors.transaction_details_post_processor`` wuerde deshalb
    nichts bewirken -- nachgesehen auf der Instanz, nicht angenommen.

    :return: True, wenn der Verwendungszweck danach seine Leerzeichen behaelt
    """
    global _SPACES_INSTALLED
    if _SPACES_INSTALLED:
        return True

    try:
        from mt940 import models, processors

        from kefiya.utils import verwendungszweck
    except Exception:
        return False

    try:
        kette = models.Transactions.DEFAULT_PROCESSORS["post_transaction_details"]
    except Exception:
        return False

    original = processors.transaction_details_post_processor

    def je_buchung(transactions, tag, tag_dict, result, space=False):
        # Der rohe :86:-Inhalt dieser einen Buchung. Faellt er aus, bleibt es
        # beim Verhalten der Bibliothek -- ein Verwendungszweck ohne
        # Leerzeichen ist schlechter lesbar, ein abgebrochener Abruf ist
        # schlimmer.
        try:
            roh = tag_dict.get("transaction_details") or ""
            space = verwendungszweck.mit_leerzeichen(str(roh))
        except Exception:
            pass
        return original(transactions, tag, tag_dict, result, space=space)

    # Eine Bibliotheksfassung, die das von sich aus richtig macht, braucht von
    # uns nichts.
    from kefiya.utils import mt940_probe
    if mt940_probe.die_reparatur_wirkt():
        _SPACES_INSTALLED = True
        return True

    ersetzt = 0
    try:
        for index, vorhanden in enumerate(list(kette)):
            if vorhanden is original:
                kette[index] = je_buchung
                ersetzt += 1
    except Exception:
        _beschwerde(
            "Der Eintrag in DEFAULT_PROCESSORS liess sich nicht "
            "ersetzen.")
        return False

    if not ersetzt:
        _beschwerde(
            "In DEFAULT_PROCESSORS['post_transaction_details'] steht die "
            "Funktion transaction_details_post_processor nicht (mehr). Diese "
            "Bibliotheksfassung haelt ihre Kette anders.")
        return False

    # Gemessen, nicht angenommen: eine erfundene Buchung durch den Parser, und
    # nachgesehen, was herauskommt. Dass der Eintrag ersetzt wurde, heisst
    # noch nicht, dass der Zweck danach Leerzeichen hat -- genau diese Luecke
    # hat am 14.11.2026 einen halben Tag gekostet.
    if not mt940_probe.die_reparatur_wirkt():
        _beschwerde(
            "Der Eintrag wurde ersetzt, aber der Parser liefert den "
            "Verwendungszweck trotzdem ohne Trenner.")
        return False

    _SPACES_INSTALLED = True
    return True
