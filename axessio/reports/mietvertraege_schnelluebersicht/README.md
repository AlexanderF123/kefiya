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
- **Rechte:** gelesen wird über `frappe.get_list` (Kindtabellen mit
  `parent_doctype`), also mit den Rollen- und Benutzerberechtigungen des
  Aufrufers -- keine Rohabfrage am Rechtesystem vorbei
- **Feature-Datensatz:** `FEAT-16128`

## Dateien

| Datei | Ziel in ERPNext |
|---|---|
| `report_script.py` | Feld `report_script` des Report-Datensatzes |
| `report.js` | Feld `javascript` des Report-Datensatzes |
| `wiki_help.md` | Wiki Page `1g85uivt48` (`wiki/help-mietvertraege-schnelluebersicht`) |
| `menuepunkt/block.{html,css,js}` | Custom HTML Block `axessio Schnelluebersicht Weiche` |
| `menuepunkt/workspace.json` | Workspace `Schnellübersicht Mietverträge` |

Diese Dateien sind die versionierte Fassung dessen, was in der Datenbank steht.
Wer etwas ändert, ändert hier **und** am jeweiligen Datensatz -- beides muss
zeichengleich bleiben.

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

## Einzelbeleg öffnen

Die erste Spalte jeder Zeile ist ein Verweis auf ihren Beleg: Objekt- und
Einheitenzeilen führen auf die `Property`, Vertrags- und Zeitraumzeilen auf den
`Lease`. Der Verweis trägt `data-doctype` und `data-name`, damit auch das
Kontextmenü der Oberfläche (`ax_actions_js`) die Zeile erkennt. Die Spalten
*Einheit*, *Mietvertrag* und *Mieter* bleiben zusätzlich als Verknüpfungen
bestehen.

## Kennzahlen, Diagramm, Einstellungen

Über der Liste steht ein Band aus fünf Kennzahlen: Einheiten, Vermietet,
Leerstand, Soll/Monat, Kaution gesamt. Sie beschreiben immer den Bestand der
ausgewählten Objekte, nicht den gerade gefilterten Ausschnitt -- und jede ist ein
**Einstieg**: Ein Klick setzt den Belegungsfilter auf das, was die Zahl zählt,
und klappt den Baum auf die passende Tiefe auf (Einheiten/Vermietet/Leerstand bis
zur Einheit, Soll und Kaution bis zum Vertrag).

Die Schaltfläche **Alle Zeilen** hebt alle einschränkenden Filter auf
(Gesellschaft, Objekt, Einheit, Mieter, Nutzungsart, Belegung, Vertragssicht) und
zeigt den ganzen Bestand; Stichtag und BK-Jahre bleiben stehen.

Kennzahlenband und Diagramm lassen sich über zwei Schalter **ein- und
ausklappen**. Das Diagramm zeigt das Soll je Objekt und ist selbst gezeichnetes
SVG -- nicht frappe-charts: Nur so trägt die **Achse links echte Beträge**
(1 T€, 40 T€, 328 T€ …) statt Skalenwerte, und nur so lässt sich ein Balken
anklicken. Ein Klick filtert auf dieses Objekt und klappt bis zu den Verträgen
auf, ein zweiter Klick hebt die Einschränkung wieder auf.

Die Balkenhöhe folgt einer wählbaren Skala (Schalter **Skala**):

| Skala | Anteil der Höhe | Wofür |
|---|---|---|
| **Wurzel** (Vorgabe) | `√wert / √größter` | Kompromiss: kleine Objekte bleiben sichtbar, die Größenverhältnisse bleiben lesbar |
| Logarithmisch | `log(1+wert) / log(1+größter)` | Sehr große Spannen; ebnet Unterschiede stark ein |
| Linear | `wert / größter` | Echte Proportionen; kleine Objekte verschwinden fast |

Die Achsenmarken werden aus der jeweiligen Umkehrfunktion berechnet und mit dem
Betrag beschriftet, der auf dieser Höhe steht.

Filter, Klappzustände, Achse und Baumtiefe hängen am Benutzerkonto
(`frappe.model.utils.user_settings`, Ablagefach `Lease`, Schlüssel
`mietvertraege_schnelluebersicht`), mit dem Browserspeicher als Rückfallebene.
Über das Menü **Einstellungen zurücksetzen** stellt der Anwender die Vorgaben
wieder her.

## Menüpunkt und Hilfe

Die Seitenleiste zeigt Arbeitsbereiche, keine Berichte. Der Menüpunkt
**Kaufmännische Verwaltung › Schnellübersicht Mietverträge** ist deshalb ein
Arbeitsbereich, dessen einziger Block sofort auf den Bericht weiterleitet
(`menuepunkt/`); ein sichtbarer Link bleibt als Rückfallebene stehen.

Zusätzlich zeigt die Kachel **Mietverträge** im Block *axessio Commercial Hub*
(Seite `/app/commercial-management`) nicht mehr auf `/app/leases`, sondern auf
den Bericht. Der Block gehört nicht zu diesem Bericht und liegt deshalb nicht
hier im Repository -- geändert wurde dort nur das Ziel und der Untertitel dieser
einen Kachel. Die alte Stamm- und Detailansicht bleibt über die Seitenleiste
(*Kaufmännische Verwaltung › Mietverträge*) erreichbar.

Die Hilfe im Schiebefenster (`❔ Hilfe`) hängt sonst an Client Scripts, die es nur
für Formular- und Listenansichten gibt -- der Bericht lädt `ax_drawer_js` deshalb
selbst nach. Die Zuordnung zur Wiki-Seite läuft über zwei `User Help Mapping`
-Datensätze auf die Routen `/app/query-report/Mietverträge Schnellübersicht`
(Report) und `/app/schnellübersicht-mietverträge` (Workspace).

## Filter

| Filter | Wirkung |
|---|---|
| Stichtag | Bestimmt, welcher Mietzeitraum gilt und welcher Vertrag als *Aktuell* zählt. Rückdatieren zeigt den Bestand von damals. |
| Gesellschaft / Objekt / Einheit / Nutzungsart | Schränken die Einheiten ein |
| Mieter | Zeigt nur die Einheiten dieses Mieters |
| Verträge | *Mit Vormietern* (Vorgabe), *Nur aktuelle Verträge*, *Nur Vormieter* |
| Mietzeiträume | *Nur aktueller Zeitraum* (Vorgabe), *Alle Staffeln*, *Ohne Zeitraum-Zeilen* |
| Belegung | *Alle* (Vorgabe), *Nur vermietet*, *Nur Leerstand* |
| BK-Jahre | Anzahl der Betriebskosten-Spalten (0 bis 6, rückwärts ab Stichtag) |

Vermietungsquote und Summen einer Objektzeile beschreiben immer den Bestand des
Objekts, nicht den gerade gefilterten Ausschnitt -- sonst läse sich ein
Leerstandsfilter als „0 von 3 vermietet". Der alte Haken `nur_leerstand` wird
weiter verstanden, damit gespeicherte Verknüpfungen nicht ins Leere laufen.

Der Hinweis zu Stichtag und Steuersatz steht **unter** der Tabelle: Er reist als
Schlüssel `fussnote` an der ersten Zeile mit, weil Frappe eine `message` über die
Liste setzen würde, wo sie den Blick auf die Daten verstellt.

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
2. Inhalt in das jeweilige Feld des Datensatzes übertragen (`Report` →
   *Mietverträge Schnellübersicht*, Felder `report_script` / `javascript`;
   Wiki Page `1g85uivt48`; Custom HTML Block *axessio Schnelluebersicht Weiche*).
3. Testlauf über mehrere Objekte, mindestens einen mit Vormietern, und einmal
   rückdatiert.
4. Zeichenzahl von Datei und Datenbankfeld vergleichen -- sie müssen gleich sein.
