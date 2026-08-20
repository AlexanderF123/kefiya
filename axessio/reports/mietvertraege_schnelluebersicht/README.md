# Mietverträge Schnellübersicht

Baumbericht in ERPNext, der die gewachsene Excel-Schnellübersicht (`Brilu_SollHaben`,
Blatt **Soll**) ablöst: dieselbe Gliederung, dieselben Spalten -- aber auf den
Live-Stammdaten, filterbar und mit Drill-down auf die Belege, in denen die Daten
gepflegt werden.

- **Aufruf:** `/app/query-report/Mietverträge Schnellübersicht`
- **Art:** Script Report (in der Datenbank, Modul *Property Management Solution*,
  Referenz-DocType *Lease*)
- **Rollen:** System Manager, Property Manager, axessio Hausverwalter
- **Risikoklasse:** A -- reiner Lesebericht, keine Datenänderung
- **Feature-Datensatz:** `FEAT-16128`

## Dateien

| Datei | Ziel in ERPNext |
|---|---|
| `report_script.py` | Feld `report_script` des Report-Datensatzes |
| `report.js` | Feld `javascript` des Report-Datensatzes |

Beide Dateien sind die versionierte Fassung dessen, was in der Datenbank steht.
Wer etwas ändert, ändert hier **und** am Report -- beides muss zeichengleich bleiben.

## Gliederung (entspricht den Blockstufen der Excel-Tabelle)

| Ebene | Excel | ERPNext |
|---|---|---|
| 0 Objekt | Überschriftenzeile je Haus (`101 Schlowo …`) | `Property` mit `is_group = 1` |
| 1 Einheit | Spalte *Ort* (`UG`, `OG1 links`, `Garage alt links`) | `Property` unterhalb des Hauses |
| 2 Mietvertrag | Spalte *Mieter*, mehrere Zeilen je Einheit = Vormieter | `Lease` je Einheit, chronologisch |
| 3 Mietzeitraum | Zeilen *Von/Bis* innerhalb eines Mieters (Staffeln) | Zeitscheiben aus `Lease Item.valid_from` |

Die Objektzeile summiert Fläche, Soll und Kaution und zeigt die Vermietungsquote.

## Spaltenherkunft

| Spalte | Quelle |
|---|---|
| Räume | `Property.master_bedroom` (ersatzweise `bedroom`) |
| m² | `Property.custom_property_area`, ersatzweise `Lease.custom_total_rental_area` |
| Pers. | `BKA Personenstand` des Vertrags, gültig am Stichtag |
| BK *Jahr* | `BKA Mieter Abrechnung.saldo` der gültigen Version (+ Nachzahlung / − Guthaben) |
| Von / Bis | Vertragszeile: `start_date` / `end_date` (ersatzweise `custom_move_out_date`); Zeitraumzeile: Grenzen der Zeitscheibe |
| Miete | Lease Items mit *Miete* / *Pacht* im Artikelnamen (Wohnung, Gewerbe, Garage, Stellplatz, Keller …) |
| Küche | Artikel *Küchenmiete* |
| Extras/Verw. | Verwaltungskosten, Zuschläge, Ausbaukosten -- alles, was in keine andere Spalte fällt |
| MwSt. | 19 % auf Positionen, deren Artikelname *zzgl./mit MwSt.* trägt |
| K-Zins | Artikel *Kautionsverzinsung* (in der Regel negativ) |
| BK | Betriebskosten-Vorauszahlung bzw. -pauschale |
| Soll | Summe der sechs Spalten -- entspricht `Lease.custom_current_total_net_lease_amount` |
| Kaution / Kautionsart | `Lease.security_deposit` / `custom_deposit_type` |
| Staffel / Index | `custom_rent_increase_type` plus nächste vereinbarte Stufe (Differenz und Datum) |
| Kommentar | `Lease.custom_special_agreements` (auf 300 Zeichen gekürzt) |

## Filter

| Filter | Wirkung |
|---|---|
| Stichtag | Bestimmt, welcher Mietzeitraum gilt und welcher Vertrag als *Aktuell* zählt. Rückdatieren zeigt den Bestand von damals. |
| Gesellschaft / Objekt / Einheit / Nutzungsart | Schränken die Einheiten ein |
| Mieter | Zeigt nur die Einheiten dieses Mieters |
| Verträge | *Mit Vormietern* (Vorgabe), *Nur aktuelle Verträge*, *Nur Vormieter* |
| Mietzeiträume | *Nur aktueller Zeitraum* (Vorgabe), *Alle Staffeln*, *Ohne Zeitraum-Zeilen* |
| Nur Leerstand | Zeigt nur unvermietete Einheiten |
| BK-Jahre | Anzahl der Betriebskosten-Spalten (0 bis 6, rückwärts ab Stichtag) |

Vermietungsquote und Summen einer Objektzeile beschreiben immer den Bestand des
Objekts, nicht den gerade gefilterten Ausschnitt -- sonst läse sich ein
Leerstandsfilter als „0 von 3 vermietet".

## Drill-down und Pflege

Der Bericht schreibt nichts. Die Spalten *Einheit*, *Mietvertrag* und *Mieter* sind
Verknüpfungen: Ein Klick öffnet `Property`, `Lease` bzw. `Customer` -- dort werden die
Daten gepflegt. Zusätzlich öffnen die Schaltflächen *Einheit öffnen* und
*Mietvertrag öffnen* den Beleg der markierten Zeile.

## Was der Bericht nicht kann (Stand der Daten, August 2026)

Diese Lücken liegen in den Stammdaten, nicht im Bericht -- er macht sie sichtbar:

- **106 aktive Verträge ohne Mietpositionen** erscheinen ohne Soll-Beträge.
- **48 Verträge tragen Positionen ohne *Gültig ab***; sie werden ab Vertragsbeginn
  gerechnet. Liegen alle Positionen eines beendeten Vertrags hinter dem Vertragsende,
  werden sie trotzdem gezeigt, statt zu verschwinden.
- **297 von 775 Verträgen ohne Flächenangabe**, **586 von 970 Einheiten ohne Raumzahl**.
- **Personenstände sind erst für 2 Verträge gepflegt** -- die Spalte *Pers.* bleibt sonst leer.
- **Betriebskostensalden liegen nur für 2024 vor** (5 freigegebene Abrechnungen); die
  übrigen BK-Spalten bleiben leer, bis die Läufe erfasst sind.
- Mietpositionen kennen kein Enddatum. Eine Position gilt bis zu ihrer nächsten
  Fassung -- eine weggefallene Position muss mit Betrag 0 fortgeschrieben werden.
- Die MwSt.-Spalte rechnet pauschal mit 19 % auf steuerpflichtige Artikel und ersetzt
  keine Steuerermittlung aus den Belegen.
- Die Excel-Blätter *2021*–*2025* (Soll/Haben je Monat) bildet dieser Bericht nicht ab;
  dafür gibt es die Zahlungs- und Mahnauswertungen.

## Erneut ausrollen

Änderungen am Report werden direkt in der Datenbank gepflegt (Risikoklasse A, jederzeit
deploybar). Ablauf:

1. Datei hier ändern.
2. Inhalt in das jeweilige Feld des Report-Datensatzes übertragen
   (`Report` → *Mietverträge Schnellübersicht*, Felder `report_script` / `javascript`).
3. Testlauf über mehrere Objekte, mindestens einen mit Vormietern, und einmal
   rückdatiert.
4. Zeichenzahl von Datei und Datenbankfeld vergleichen -- sie müssen gleich sein.
