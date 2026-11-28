# -*- coding: utf-8 -*-
# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""Ein Konto, das die Bank in HIUPD mehrfach nennt -- ohne frappe.

Die Sparkasse nennt manche Konten eines Zugangs mehr als einmal: einmal
mit allem, was der Zugang dort darf, und einmal mit einer kurzen Liste
(Saldo und ein paar DK-Segmente). kefiya schrieb jeden Eintrag nacheinander
auf das Konto, und der letzte gewann. Am 26.11.2026 war das die kurze
Liste: vier Minuten nachdem vom Geschaeftskonto eine Ueberweisung
hinausgegangen war, hiess es "Die Bank erlaubt 'Ueberweisung' auf dem Konto
nicht", am 27. stimmte die Liste wieder -- je nach Reihenfolge.

Ein Geschaeftsvorfall, den einer der Eintraege erlaubt, ist erlaubt. Die
Bank wuerde einen Auftrag, den der Zugang nicht darf, ohnehin ablehnen;
die Liste soll nur verhindern, dass einer gesendet wird, der sicher
scheitert -- und nicht einen sperren, der durchgeht.
"""


def merged(segment_lists):
    """Die Segmente aller Eintraege eines Kontos, zu einem zusammengefasst.

    :param segment_lists: je Eintrag ein Dict {Segment: Angaben}, wie
        account_capabilities.read_from_connection es liefert
    :return: ein Dict mit jedem Segment, das irgendein Eintrag nennt. Wo
        mehrere dasselbe Segment nennen, gelten die Angaben des ersten;
        was dort fehlt (None), fuellt ein spaeterer.
    """
    out = {}
    for segments in segment_lists or []:
        for code, info in (segments or {}).items():
            info = dict(info or {})
            if code not in out:
                out[code] = info
                continue
            for key, value in info.items():
                if out[code].get(key) is None and value is not None:
                    out[code][key] = value
    return out
