# Mietvertraege Schnelluebersicht -- Baumbericht ueber Objekt / Einheit / Vertrag / Zeitraum.
#
# Bildet die gewachsene Excel-Schnelluebersicht ("Soll") auf die Stammdaten in
# ERPNext ab: Haus (Property is_group=1) -> Einheit (Property) -> Mietvertrag
# (Lease, inkl. Vormietern) -> Mietzeitraum (Staffel aus Lease Item.valid_from).
#
# Der Bericht liest nur. Gepflegt werden die Daten ueber die verlinkten Belege
# (Spalten Einheit / Mietvertrag / Mieter sind Drill-down-Links).
#
# Laeuft als DB-Script-Report in der safe_exec-Sandbox: kein import, keine
# Lambda-Ausdruecke, Ergebnis in der Variablen `data`. Der gesamte Rumpf steht
# in einer Funktion -- Zuweisungen auf Modulebene landen in der Sandbox in einem
# eigenen locals-Dict, das die Helferfunktionen nicht sehen wuerden.


def erzeuge_bericht(filters):
    MWST_SATZ = 19.0
    LEERE_VERTRAGSSTATUS = ("Closed", "Account Closed", "Not Materialized")

    filters = filters or {}

    stichtag = frappe.utils.getdate(filters.get("stichtag") or frappe.utils.today())
    f_company = filters.get("company")
    f_haus = filters.get("haus")
    f_einheit = filters.get("einheit")
    f_mieter = filters.get("mieter")
    f_nutzungsart = filters.get("nutzungsart")
    sicht_vertraege = filters.get("vertraege") or "Mit Vormietern"
    sicht_zeitraeume = filters.get("zeitraeume") or "Nur aktueller Zeitraum"
    belegung = filters.get("belegung")
    if not belegung:
        belegung = "Nur Leerstand" if frappe.utils.cint(filters.get("nur_leerstand")) else "Alle"
    bk_jahre = frappe.utils.cint(filters.get("bk_jahre"))
    if bk_jahre < 0:
        bk_jahre = 0
    if bk_jahre > 6:
        bk_jahre = 6

    # BK-Jahre: die abgeschlossenen Abrechnungsjahre vor dem Stichtag, aeltestes zuerst.
    bk_jahre_liste = []
    jahr = stichtag.year - bk_jahre
    while jahr < stichtag.year:
        bk_jahre_liste.append(jahr)
        jahr = jahr + 1

    # ---------------------------------------------------------------- Hilfsmittel

    def kategorie_von(item):
        """Ordnet einen Lease-Item-Artikel einer Spalte der Excel-Uebersicht zu."""
        t = (item or "").lower()
        if "kautionsverzinsung" in t:
            return "k_zins"
        if "kuechenmiete" in t or "küchenmiete" in t:
            return "kueche"
        if "betriebskosten" in t or "nebenkosten" in t or "heizkosten" in t:
            return "bk"
        if "miete" in t or "pacht" in t:
            return "miete"
        return "extras"

    def ist_steuerpflichtig(item):
        """Die Artikelbezeichnung traegt die Steuerkennung ('ohne' / 'zzgl.' / 'mit')."""
        t = (item or "").lower()
        if "ohne mwst" in t:
            return False
        return ("zzgl. mwst" in t) or ("mit mwst" in t) or ("zzgl.mwst" in t)

    def leer_zu_none(wert):
        w = (wert or "").strip()
        return w or None

    def kuerzen(text, laenge):
        t = (text or "").replace("\n", " ").replace("\r", " ").strip()
        if len(t) > laenge:
            return t[:laenge] + "…"
        return t

    def de_datum(wert):
        """Tag.Monat.Jahr -- ohne Abhaengigkeit von Formatierern der Sandbox."""
        if not wert:
            return ""
        d = frappe.utils.getdate(wert)
        return "%02d.%02d.%04d" % (d.day, d.month, d.year)

    def euro(betrag):
        return "%.2f €" % frappe.utils.flt(betrag)

    def datum_oder_none(wert):
        if not wert:
            return None
        return frappe.utils.getdate(wert)

    # --------------------------------------------------------------- Stammdaten

    bedingungen = ["u.is_group = 0"]
    werte = {}
    if f_company:
        bedingungen.append("u.company = %(company)s")
        werte["company"] = f_company
    if f_haus:
        bedingungen.append("u.parent_property = %(haus)s")
        werte["haus"] = f_haus
    if f_einheit:
        bedingungen.append("u.name = %(einheit)s")
        werte["einheit"] = f_einheit
    if f_nutzungsart:
        bedingungen.append("u.custom_type_of_use = %(nutzungsart)s")
        werte["nutzungsart"] = f_nutzungsart

    einheiten = frappe.db.sql(
        "SELECT u.name, u.name1, u.parent_property, u.company, u.status, "
        "  u.custom_type_of_use, u.custom_property_area, u.master_bedroom, u.bedroom, "
        "  u.custom_level_in_the_building, h.name1 AS haus_name "
        "FROM `tabProperty` u "
        "LEFT JOIN `tabProperty` h ON h.name = u.parent_property "
        "WHERE " + " AND ".join(bedingungen) + " "
        "ORDER BY IFNULL(u.parent_property, 'ZZZZ') ASC, u.name ASC",
        werte,
        as_dict=True,
    )

    einheit_namen = []
    for e in einheiten:
        einheit_namen.append(e.name)
    einheit_set = set(einheit_namen)

    vertraege = frappe.db.sql(
        "SELECT name, property, lease_customer, custom_tenants_contract_number, "
        "  start_date, end_date, lease_status, security_deposit, custom_deposit_type, "
        "  custom_rent_increase_type, custom_price_index, custom_total_rental_area, "
        "  custom_special_agreements, custom_move_out_date, company "
        "FROM `tabLease` WHERE docstatus < 2 "
        "ORDER BY property ASC, start_date ASC, name ASC",
        as_dict=True,
    )

    positionen = frappe.db.sql(
        "SELECT parent, lease_item, amount, valid_from FROM `tabLease Item` "
        "ORDER BY parent ASC, valid_from ASC",
        as_dict=True,
    )

    bk_salden = frappe.db.sql(
        "SELECT lease, abrechnungsjahr, saldo FROM `tabBKA Mieter Abrechnung` "
        "WHERE ist_gueltig = 1",
        as_dict=True,
    )

    personenstaende = frappe.db.sql(
        "SELECT parent, personen, gueltig_von, gueltig_bis FROM `tabBKA Personenstand` "
        "ORDER BY parent ASC, gueltig_von ASC",
        as_dict=True,
    )

    # Positionen je Vertrag buendeln.
    pos_je_vertrag = {}
    for p in positionen:
        if p.parent not in pos_je_vertrag:
            pos_je_vertrag[p.parent] = []
        pos_je_vertrag[p.parent].append(p)

    # BK-Salden je Vertrag und Jahr.
    bk_je_vertrag = {}
    for b in bk_salden:
        if b.lease not in bk_je_vertrag:
            bk_je_vertrag[b.lease] = {}
        bk_je_vertrag[b.lease][frappe.utils.cint(b.abrechnungsjahr)] = frappe.utils.flt(b.saldo)

    # Personenstand je Vertrag, gueltig am Stichtag.
    personen_je_vertrag = {}
    for ps in personenstaende:
        von = datum_oder_none(ps.gueltig_von)
        bis = datum_oder_none(ps.gueltig_bis)
        if von and von > stichtag:
            continue
        if bis and bis < stichtag:
            continue
        personen_je_vertrag[ps.parent] = frappe.utils.cint(ps.personen)

    # ------------------------------------------------------- Zeitraeume (Staffeln)

    def zeitraeume_von_vertrag(vertrag):
        """Zerlegt einen Vertrag in Mietzeitraeume anhand der Gueltig-ab-Daten der Positionen.

        Ein Zeitraum beginnt an jedem Datum, an dem sich mindestens eine Position
        aendert, und laeuft bis zum Tag vor dem naechsten Wechsel (der letzte bis zum
        Vertragsende). Positionen haben kein Enddatum -- eine einmal vereinbarte
        Position gilt bis zu ihrer naechsten Fassung fort. Positionen ohne Gueltig-ab
        gelten ab Vertragsbeginn.
        """
        posten = pos_je_vertrag.get(vertrag.name) or []
        if not posten:
            return []

        v_start = datum_oder_none(vertrag.start_date)
        v_ende = datum_oder_none(vertrag.end_date)

        wechsel_alle = []
        for p in posten:
            d = datum_oder_none(p.valid_from) or v_start
            if not d:
                continue
            if v_start and d < v_start:
                d = v_start
            if d not in wechsel_alle:
                wechsel_alle.append(d)
        wechsel_alle = sorted(wechsel_alle)
        if not wechsel_alle:
            return []

        wechsel = []
        for d in wechsel_alle:
            if v_ende and d > v_ende:
                continue
            wechsel.append(d)
        if not wechsel:
            # Altdaten: alle Positionen tragen ein Datum nach Vertragsende.
            wechsel = wechsel_alle

        ergebnis = []
        index = 0
        for beginn in wechsel:
            index = index + 1
            if index < len(wechsel):
                ende = frappe.utils.add_days(wechsel[index], -1)
            else:
                ende = v_ende

            # Fuer jede Artikelart die zum Zeitraumbeginn juengste Fassung.
            aktuell = {}
            for p in posten:
                d = datum_oder_none(p.valid_from) or v_start
                if not d or d > beginn:
                    continue
                aktuell[p.lease_item] = p.amount

            summen = {"miete": 0.0, "kueche": 0.0, "extras": 0.0, "bk": 0.0, "k_zins": 0.0, "mwst": 0.0}
            for artikel in aktuell:
                betrag = frappe.utils.flt(aktuell[artikel])
                feld = kategorie_von(artikel)
                summen[feld] = summen[feld] + betrag
                if ist_steuerpflichtig(artikel):
                    summen["mwst"] = summen["mwst"] + betrag * MWST_SATZ / 100.0

            soll = 0.0
            for feld in summen:
                soll = soll + summen[feld]

            ergebnis.append({
                "von": beginn,
                "bis": datum_oder_none(ende),
                "miete": round(summen["miete"], 2),
                "kueche": round(summen["kueche"], 2),
                "extras": round(summen["extras"], 2),
                "mwst": round(summen["mwst"], 2),
                "k_zins": round(summen["k_zins"], 2),
                "bk": round(summen["bk"], 2),
                "soll": round(soll, 2),
            })
        return ergebnis

    def aktueller_zeitraum(zeitraeume):
        """Der am Stichtag geltende Zeitraum; sonst der letzte vergangene bzw. erste kuenftige."""
        if not zeitraeume:
            return None
        treffer = None
        for z in zeitraeume:
            if z["von"] <= stichtag and (not z["bis"] or z["bis"] >= stichtag):
                treffer = z
        if treffer:
            return treffer
        vergangen = None
        for z in zeitraeume:
            if z["von"] <= stichtag:
                vergangen = z
        if vergangen:
            return vergangen
        return zeitraeume[0]

    def rolle_von_vertrag(vertrag):
        start = datum_oder_none(vertrag.start_date)
        ende = datum_oder_none(vertrag.end_date)
        if (vertrag.lease_status or "") in LEERE_VERTRAGSSTATUS:
            return "Vormieter"
        if start and start > stichtag:
            return "Künftig"
        if ende and ende < stichtag:
            return "Vormieter"
        if not start:
            return "Vormieter"
        return "Aktuell"

    def staffel_text(vertrag, zeitraeume):
        """Kurztext zur Mietanpassung: Art plus naechste vereinbarte Stufe."""
        art = vertrag.custom_rent_increase_type or ""
        if art == "graduated rent":
            text = "Staffel"
        elif art == "index rent":
            text = "Index"
        elif art == "no agreement":
            text = "—"
        else:
            text = art or "—"

        naechster = None
        for z in zeitraeume:
            if z["von"] > stichtag and naechster is None:
                naechster = z
        if naechster:
            aktuell = aktueller_zeitraum(zeitraeume)
            differenz = 0.0
            if aktuell:
                differenz = round(naechster["soll"] - aktuell["soll"], 2)
            vorzeichen = "+" if differenz >= 0 else ""
            text = text + " " + vorzeichen + euro(differenz)
            text = text + " ab " + de_datum(naechster["von"])
        return text

    # ------------------------------------------------------------------- Spalten

    columns = [
        {"fieldname": "bezeichnung", "label": "Objekt / Einheit / Mieter / Zeitraum", "fieldtype": "Data", "width": 300},
        {"fieldname": "rolle", "label": "Rolle", "fieldtype": "Data", "width": 90},
        {"fieldname": "einheit", "label": "Einheit", "fieldtype": "Link", "options": "Property", "width": 110},
        {"fieldname": "vertrag", "label": "Mietvertrag", "fieldtype": "Link", "options": "Lease", "width": 130},
        {"fieldname": "mieter", "label": "Mieter", "fieldtype": "Link", "options": "Customer", "width": 180},
        {"fieldname": "vertragsnr", "label": "Vertrags-Nr.", "fieldtype": "Data", "width": 95},
        {"fieldname": "raeume", "label": "Räume", "fieldtype": "Int", "width": 65},
        {"fieldname": "qm", "label": "m²", "fieldtype": "Float", "precision": 2, "width": 75},
        {"fieldname": "pers", "label": "Pers.", "fieldtype": "Int", "width": 60},
    ]
    for j in bk_jahre_liste:
        columns.append({
            "fieldname": "bk_" + str(j),
            "label": "BK " + str(j),
            "fieldtype": "Currency",
            "options": "EUR",
            "width": 95,
        })
    columns = columns + [
        {"fieldname": "von", "label": "Von", "fieldtype": "Date", "width": 95},
        {"fieldname": "bis", "label": "Bis", "fieldtype": "Date", "width": 95},
        {"fieldname": "miete", "label": "Miete", "fieldtype": "Currency", "options": "EUR", "width": 105},
        {"fieldname": "kueche", "label": "Küche", "fieldtype": "Currency", "options": "EUR", "width": 85},
        {"fieldname": "extras", "label": "Extras/Verw.", "fieldtype": "Currency", "options": "EUR", "width": 100},
        {"fieldname": "mwst", "label": "MwSt.", "fieldtype": "Currency", "options": "EUR", "width": 90},
        {"fieldname": "k_zins", "label": "K-Zins", "fieldtype": "Currency", "options": "EUR", "width": 85},
        {"fieldname": "bk", "label": "BK", "fieldtype": "Currency", "options": "EUR", "width": 90},
        {"fieldname": "soll", "label": "Soll", "fieldtype": "Currency", "options": "EUR", "width": 110},
        {"fieldname": "kaution", "label": "Kaution", "fieldtype": "Currency", "options": "EUR", "width": 100},
        {"fieldname": "kaution_art", "label": "Kautionsart", "fieldtype": "Data", "width": 95},
        {"fieldname": "staffel", "label": "Staffel / Index", "fieldtype": "Data", "width": 170},
        {"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 105},
        {"fieldname": "kommentar", "label": "Kommentar", "fieldtype": "Data", "width": 260},
    ]

    # --------------------------------------------------------- Vertraege je Einheit

    vertraege_je_einheit = {}
    for v in vertraege:
        if v.property not in einheit_set:
            continue
        if f_mieter and v.lease_customer != f_mieter:
            continue
        if v.property not in vertraege_je_einheit:
            vertraege_je_einheit[v.property] = []
        vertraege_je_einheit[v.property].append(v)

    # ------------------------------------------------------------------- Zeilen

    rows = []

    summe_soll = 0.0
    summe_kaution = 0.0
    anzahl_einheiten = 0
    anzahl_vermietet = 0

    haus_reihenfolge = []
    einheiten_je_haus = {}
    haus_titel = {}
    for e in einheiten:
        schluessel = e.parent_property or "—"
        if schluessel not in einheiten_je_haus:
            einheiten_je_haus[schluessel] = []
            haus_reihenfolge.append(schluessel)
            if e.parent_property:
                haus_titel[schluessel] = e.parent_property + " · " + (e.haus_name or "")
            else:
                haus_titel[schluessel] = "Ohne Objektzuordnung"
        einheiten_je_haus[schluessel].append(e)

    for haus in haus_reihenfolge:
        haus_zeilen = []
        haus_qm = 0.0
        haus_soll = 0.0
        haus_kaution = 0.0
        haus_einheiten = 0
        haus_vermietet = 0
        haus_bk = {}

        for e in einheiten_je_haus[haus]:
            e_vertraege = vertraege_je_einheit.get(e.name) or []
            if f_mieter and not e_vertraege:
                # Mit Mieterfilter interessieren nur dessen Einheiten -- alle
                # uebrigen waeren sonst faelschlich Leerstand.
                continue

            # Vertraege aufbereiten (Zeitraeume, Rolle, Kennzahlen am Stichtag).
            aufbereitet = []
            for v in e_vertraege:
                zeitraeume = zeitraeume_von_vertrag(v)
                aufbereitet.append({
                    "vertrag": v,
                    "zeitraeume": zeitraeume,
                    "aktuell": aktueller_zeitraum(zeitraeume),
                    "rolle": rolle_von_vertrag(v),
                })

            laufender = None
            for a in aufbereitet:
                if a["rolle"] == "Aktuell":
                    laufender = a

            # Flaeche: Einheit, sonst laufender Vertrag, sonst juengster Vertrag.
            qm = frappe.utils.flt(e.custom_property_area)
            if not qm and laufender:
                qm = frappe.utils.flt(laufender["vertrag"].custom_total_rental_area)
            if not qm and aufbereitet:
                qm = frappe.utils.flt(aufbereitet[len(aufbereitet) - 1]["vertrag"].custom_total_rental_area)

            raeume = frappe.utils.cint(e.master_bedroom) or frappe.utils.cint(e.bedroom)

            # Zaehlen und summieren vor den Anzeigefiltern: die Quote eines Hauses
            # soll den Bestand beschreiben, nicht den gerade gefilterten Ausschnitt.
            ist_gemeinschaft = e.status == "Common Area (Not for lease)"
            if not ist_gemeinschaft:
                haus_einheiten = haus_einheiten + 1
                haus_qm = haus_qm + qm
            if laufender:
                haus_soll = haus_soll + frappe.utils.flt(laufender["aktuell"] and laufender["aktuell"].get("soll"))
                haus_kaution = haus_kaution + frappe.utils.flt(laufender["vertrag"].security_deposit)
                if not ist_gemeinschaft:
                    haus_vermietet = haus_vermietet + 1

            if belegung == "Nur Leerstand" and laufender:
                continue
            if belegung == "Nur vermietet" and not laufender:
                continue

            # Welche Vertraege werden gezeigt?
            sichtbar = []
            for a in aufbereitet:
                if sicht_vertraege == "Nur aktuelle Verträge" and a["rolle"] == "Vormieter":
                    continue
                if sicht_vertraege == "Nur Vormieter" and a["rolle"] != "Vormieter":
                    continue
                sichtbar.append(a)

            if sicht_vertraege == "Nur Vormieter" and not sichtbar:
                continue

            einheit_zeilen = []
            for a in sichtbar:
                v = a["vertrag"]
                akt = a["aktuell"] or {}
                zeile = {
                    "bezeichnung": v.lease_customer or v.name,
                    "rolle": a["rolle"],
                    "einheit": e.name,
                    "vertrag": v.name,
                    "mieter": v.lease_customer,
                    "vertragsnr": leer_zu_none(v.custom_tenants_contract_number),
                    "qm": frappe.utils.flt(v.custom_total_rental_area) or None,
                    "pers": personen_je_vertrag.get(v.name),
                    "von": datum_oder_none(v.start_date),
                    "bis": datum_oder_none(v.end_date) or datum_oder_none(v.custom_move_out_date),
                    "miete": akt.get("miete"),
                    "kueche": akt.get("kueche"),
                    "extras": akt.get("extras"),
                    "mwst": akt.get("mwst"),
                    "k_zins": akt.get("k_zins"),
                    "bk": akt.get("bk"),
                    "soll": akt.get("soll"),
                    "kaution": frappe.utils.flt(v.security_deposit) or None,
                    "kaution_art": v.custom_deposit_type,
                    "staffel": staffel_text(v, a["zeitraeume"]),
                    "status": v.lease_status,
                    "kommentar": kuerzen(v.custom_special_agreements, 300),
                    "indent": 2,
                }
                salden = bk_je_vertrag.get(v.name) or {}
                for j in bk_jahre_liste:
                    if j in salden:
                        zeile["bk_" + str(j)] = salden[j]
                        haus_bk[j] = frappe.utils.flt(haus_bk.get(j)) + salden[j]
                einheit_zeilen.append(zeile)

                if sicht_zeitraeume != "Ohne Zeitraum-Zeilen":
                    for z in a["zeitraeume"]:
                        if sicht_zeitraeume == "Nur aktueller Zeitraum":
                            if not a["aktuell"] or z["von"] != a["aktuell"]["von"]:
                                continue
                        einheit_zeilen.append({
                            "bezeichnung": "Zeitraum ab " + de_datum(z["von"]),
                            "rolle": "Zeitraum",
                            "einheit": e.name,
                            "vertrag": v.name,
                            "von": z["von"],
                            "bis": z["bis"],
                            "miete": z["miete"] or None,
                            "kueche": z["kueche"] or None,
                            "extras": z["extras"] or None,
                            "mwst": z["mwst"] or None,
                            "k_zins": z["k_zins"] or None,
                            "bk": z["bk"] or None,
                            "soll": z["soll"] or None,
                            "indent": 3,
                        })

            laufender_zeitraum = laufender["aktuell"] if laufender else None
            if laufender:
                rolle_einheit = "Einheit"
            elif ist_gemeinschaft:
                rolle_einheit = "Gemeinschaft"
            else:
                rolle_einheit = "Leerstand"
            einheit_zeile = {
                "bezeichnung": e.name + " · " + (e.name1 or ""),
                "rolle": rolle_einheit,
                "einheit": e.name,
                "raeume": raeume or None,
                "qm": qm or None,
                "status": e.status if not laufender else laufender["vertrag"].lease_status,
                "indent": 1,
            }
            if laufender:
                v = laufender["vertrag"]
                akt = laufender_zeitraum or {}
                einheit_zeile["vertrag"] = v.name
                einheit_zeile["mieter"] = v.lease_customer
                einheit_zeile["pers"] = personen_je_vertrag.get(v.name)
                einheit_zeile["von"] = datum_oder_none(v.start_date)
                einheit_zeile["bis"] = datum_oder_none(v.end_date)
                einheit_zeile["miete"] = akt.get("miete")
                einheit_zeile["kueche"] = akt.get("kueche")
                einheit_zeile["extras"] = akt.get("extras")
                einheit_zeile["mwst"] = akt.get("mwst")
                einheit_zeile["k_zins"] = akt.get("k_zins")
                einheit_zeile["bk"] = akt.get("bk")
                einheit_zeile["soll"] = akt.get("soll")
                einheit_zeile["kaution"] = frappe.utils.flt(v.security_deposit) or None
                einheit_zeile["kaution_art"] = v.custom_deposit_type
                einheit_zeile["staffel"] = staffel_text(v, laufender["zeitraeume"])

            haus_zeilen.append(einheit_zeile)
            for z in einheit_zeilen:
                haus_zeilen.append(z)

        if not haus_zeilen:
            continue

        haus_zeile = {
            "bezeichnung": haus_titel[haus],
            "rolle": "Objekt",
            "einheit": haus if haus != "—" else None,
            "qm": round(haus_qm, 2) or None,
            "soll": round(haus_soll, 2) or None,
            "kaution": round(haus_kaution, 2) or None,
            "status": str(haus_vermietet) + " / " + str(haus_einheiten) + " vermietet",
            "indent": 0,
        }
        for j in bk_jahre_liste:
            if j in haus_bk:
                haus_zeile["bk_" + str(j)] = round(haus_bk[j], 2)
        rows.append(haus_zeile)
        for z in haus_zeilen:
            rows.append(z)

        summe_soll = summe_soll + haus_soll
        summe_kaution = summe_kaution + haus_kaution
        anzahl_einheiten = anzahl_einheiten + haus_einheiten
        anzahl_vermietet = anzahl_vermietet + haus_vermietet

    leerstand = anzahl_einheiten - anzahl_vermietet
    quote = 0.0
    if anzahl_einheiten:
        quote = round(leerstand * 100.0 / anzahl_einheiten, 1)

    report_summary = [
        {"label": "Einheiten", "value": anzahl_einheiten, "datatype": "Int"},
        {"label": "Vermietet", "value": anzahl_vermietet, "datatype": "Int", "indicator": "Green"},
        {"label": "Leerstand", "value": str(leerstand) + " (" + str(quote) + " %)", "datatype": "Data",
         "indicator": "Red" if leerstand else "Green"},
        {"label": "Soll / Monat", "value": round(summe_soll, 2), "datatype": "Currency", "currency": "EUR"},
        {"label": "Kaution gesamt", "value": round(summe_kaution, 2), "datatype": "Currency", "currency": "EUR"},
    ]

    # Der Hinweis reist an der ersten Zeile mit, statt als `message` zu kommen:
    # Frappe setzt eine Nachricht ueber die Tabelle, dort steht sie im Weg. Die
    # Ansicht liest den Schluessel und haengt ihn als Fussnote unter die Liste.
    hinweis = ("Stichtag " + de_datum(stichtag)
               + " · Beträge sind Monats-Sollwerte des am Stichtag geltenden Zeitraums."
               + " MwSt. ist mit " + str(frappe.utils.cint(MWST_SATZ)) + " % auf steuerpflichtige Positionen gerechnet."
               + " Gepflegt werden die Daten über die verlinkten Mietverträge und Einheiten.")
    if rows:
        rows[0]["fussnote"] = hinweis

    # Das vierte Element bleibt leer: das Diagramm zeichnet die Ansicht aus den Zeilen.
    return columns, rows, None, None, report_summary, 1


data = erzeuge_bericht(filters or {})
