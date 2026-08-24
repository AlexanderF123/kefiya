# Strategie: von der E-Mail-Adresse zum Mietvertrag

Stand: 24.08.2026 · System: axessio ERPNext (Frappe Cloud v15) · Risikoklasse B
(schreibend, Datenfelder an Communication) · betrifft FEAT-14589, FEAT-14590, FEAT-14599

## 1. Das Problem, genau benannt

Eine E-Mail trägt eine Absender- und eine Empfängeradresse. Ein Mietvertrag
(DocType `Lease`) trägt keine Adresse. Dazwischen liegen zwei Sprünge, und sie
sind unterschiedlich schwer:

1. **Adresse → Mieter.** Die Adresse hängt am `Contact`, der Contact hängt über
   `Dynamic Link` am `Customer`, der Customer steht als `lease_customer` am
   Vertrag. Dieser Sprung ist fast immer eindeutig.
2. **Mieter → Vertrag.** Ein Mieter kann mehrere Verträge haben — Wohnung plus
   Stellplatz, Gewerbeeinheit plus Lager, aktueller plus beendeter Vertrag.
   Dieser Sprung ist in fast der Hälfte der Treffer *nicht* eindeutig.

Die beiden Sprünge zu vermengen ist der teuerste Fehler dieser Aufgabe: man
verliert sichere Mieterinformation, weil der Vertrag unklar ist.

## 2. Was die Livedaten sagen (gemessen am 24.08.2026)

| Kennzahl | Wert |
|---|---|
| Communications gesamt / davon E-Mail | 17.907 / 17.568 |
| Nachrichten ohne `reference_doctype` | 10.946 (61 %) |
| Nachrichten mit gefülltem `custom_lease` | 147 (0,8 %) |
| Mietverträge gesamt / aktiv oder in Kündigung | 679 / 585 |
| Mieter (distinct `lease_customer`) / davon aktiv | 524 / 454 |
| Mieter mit mindestens einer Kontakt-Mailadresse | 418 von 524 (80 %) |
| Bekannte Mieter-Mailadressen (aktive Verträge) | 530 |
| … davon auf **genau einen Mieter** auflösbar | **524 (98,9 %)** |
| … davon auf **genau einen Vertrag** auflösbar | **408 (77 %)** |
| Empfangene Mails 12 Monate | 14.142 |
| … deren Absender eine Mieter-Adresse ist | 1.555 (11 %) |
| … davon eindeutig auf einen Vertrag | 833 (57 %) |
| … davon auf 2 und mehr Verträge | 628 (43 %) |
| Gelernte Regeln in `Known Message Assignment` | 0 |

Zwei Zahlen tragen die ganze Strategie: **98,9 % auf Mieterebene** gegen
**57 % auf Vertragsebene**. Wer nur `custom_lease` füllen will, wirft 43 % einer
sicheren Zuordnung weg.

## 3. Kernentscheidung: zwei Ebenen, zwei Felder

Die Communication bekommt neben `custom_lease` (Vertrag) ein Feld für den
**Mieter**. Der Resolver setzt immer die Ebene, die er beweisen kann:

| Ergebnis | `custom_lease_customer` | `custom_lease` |
|---|---|---|
| Adresse → ein Mieter, ein Vertrag | gesetzt | gesetzt |
| Adresse → ein Mieter, mehrere Verträge | gesetzt | leer oder Vorschlag |
| Adresse unbekannt | leer | leer |

Damit ist eine Nachricht auch dann in der Mieterakte auffindbar, wenn offen
bleibt, welcher der drei Verträge dieses Mieters gemeint ist.

## 4. Die Auflösungskette

Geordnet nach Beweiskraft; die erste greifende Regel gewinnt, zwei unabhängige
Belege heben die Konfidenz um eine Stufe (gedeckelt bei 0,98).

### Stufe A — Adresse → Mieter

| # | Regel | Signal | Konfidenz |
|---|---|---|---|
| A0 | **Thread** | `in_reply_to` bzw. `message_id`-Kette zeigt auf eine bereits zugeordnete Nachricht → deren Zuordnung erben | 0,98 |
| A1 | **Bestätigte Regel** | Treffer in `Known Message Assignment` (`match_type = Sender Email`, `confirmed = 1`) | 0,95 |
| A2 | **Stammdaten** | Absender (bzw. bei ausgehender Post Empfänger/CC) ist `Contact Email` eines `lease_customer` oder `Customer.email_id` | 0,90 |
| A3 | **Absender-Domain** | nur aus bestätigten, nicht-freemail, nicht-institutionellen Domains — **nie automatisch erzeugt** | 0,70 |
| A4 | **Inhaltsanker** | Vertragsnummer, Objektadresse/Einheit, Rechnungs- oder Kundennummer, IBAN im Betreff/Text | 0,60–0,85 |
| A5 | **Namensabgleich** | `sender_full_name` gegen Mietername — immer nur als Zusatzbeleg, nie allein | 0,40 |

### Stufe B — Mieter → Vertrag

| # | Kriterium | Wirkung in den Daten |
|---|---|---|
| B1 | **Zeitfilter**: nur Verträge, die am `communication_date` liefen | trennt Alt- von Neuvertrag desselben Mieters |
| B2 | **Inhaltsanker**: Objekt, Einheit, Vertragsnummer im Text | stärkstes Signal, aber selten vorhanden |
| B3 | **Hauptnutzung**: genau ein Vertrag auf Wohnung/Büro/Laden/Praxis/Gewerbe, Nebenverträge (Stellplatz, Garage, Keller, Werbefläche) zählen nicht | löst 52 von 78 Mehrfachmietern; 7 haben nur Nebenverträge → dann höchste Miete |
| B4 | **sonst offen lassen** | Mieter setzen, Vertrag als Vorschlag ins Cockpit |

B3 ist eine Heuristik und wird als solche protokolliert (`source = Heuristik`,
Konfidenz ≤ 0,75). Sie darf nie ohne Stufe-A-Treffer greifen.

## 5. Ausschlüsse — Präzision vor Trefferquote

Eine falsch zugeordnete Nachricht ist teurer als eine nicht zugeordnete, weil an
der Zuordnung Sichtbarkeiten hängen (Mieterportal, Dokumentfreigabe, Auskunft am
Telefon). Vor Regel A2 greift deshalb eine Ausschlussprüfung:

* **Eigene Postfächer** (12 Adressen aus `Email Account`). Beleg aus den Daten:
  `rechnungseingang@axessio.de` hängt als Kontakt an 12 Verträgen — die eigene
  Adresse darf niemals eine Mieterzuordnung auslösen.
* **Adressen, die auch an einem `Supplier` oder `Employee` hängen** — Handwerker,
  die zugleich Mieter sind, gibt es (`norbert-bauer-elektrotechnik@gmx.de`,
  12 Verträge). Solche Fälle sind Vorschlag, nie Automatik.
* **Freemail-Domains** nie als Domainregel.
* **Institutionelle Domains** nie als Domainregel. Beleg: `jobcenter-ge.de`,
  `mannheim.de`, `dpdhl.com` stehen in Mieterkontakten und identifizieren keinen
  Mieter, sondern dessen Arbeitgeber oder Amt.
* **Spam / Systemmeldungen** (`custom_is_spam`, `custom_is_system_notification`)
  und Duplikate (`custom_is_duplicate`) laufen gar nicht erst durch.

## 6. Was am Datenmodell fehlt

1. `Communication.custom_lease_customer` (Link `Customer`) — die Mieterebene.
2. `Communication.custom_assignment_confidence` (Float 0–1) und
   `custom_assignment_source` (Select: Thread / Regel / Stammdaten / Inhalt /
   Heuristik / Mensch). Ohne diese zwei Felder ist die Korrekturquote nicht
   messbar und damit nach dem axessio-Prozess kein Stufenaufstieg begründbar.
3. `Known Message Assignment`: `match_type` um `Recipient Email` erweitern und
   ein Kennzeichen für **Negativregeln** ("diese Adresse ist nie ein Mieter").
4. Kein weiteres Vorschlags-DocType. Vorschläge bleiben im `Automation Run Log`
   (`status = Proposal`), das Cockpit liest von dort.

## 7. Ausbaustufen nach axessio-Prozess

Der Resolver ist eine Automatik der Risikoklasse B und hängt an der bereits
registrierten Automation Rule *Zuordnungsvorschlag Nachrichten (Shadow)*.

**Stufe 0 — Shadow (mindestens 4 Wochen).** `comm_learn_loop_assignment_shadow`
wird um die Stammdatenkette (A2/A0) erweitert und schreibt weiterhin nur
Run-Log-Vorschläge. Parallel ein Dry-Run über die 10.946 unverknüpften
Bestandsnachrichten: Trefferquote, Eindeutigkeit und Konflikte je Regelstufe.

**Stufe 1 — Vorschlagen.** Das Zuordnungs-Cockpit (FEAT-14589) zeigt Vorschlag
und Konfidenz; ein Klick schreibt `custom_lease_customer`/`custom_lease` **und**
legt eine `Known Message Assignment` an (`source = Learn-Loop`, `confirmed = 1`).
Damit schließt sich der Lernkreis, der in FEAT-14590 offen geblieben ist.

**Stufe 2 — Handeln mit Freigabe.** Automatische Zuordnung nur bei Konfidenz
≥ 0,90 *und* Eindeutigkeit auf der jeweiligen Ebene. Alles darunter bleibt
Vorschlag. Jede Zuordnung ist mit einem Klick rücknehmbar, jede Rücknahme zählt
in die Korrekturquote.

**Stufe 3 — autonom mit Leitplanken.** Erst nach ≥ 4 Wochen mit ≥ 98 %
Übereinstimmung bzw. Korrekturquote < 2 %, belegt aus dem Run Log.

**Portal-Guard, ab Stufe 2 zwingend:** eine automatisch zugeordnete Nachricht
wird im Mieterportal *nicht* sichtbar. Sichtbarkeit setzt
`custom_assignment_source = Mensch` voraus. Eine Fehlzuordnung darf niemals
fremde Korrespondenz in eine Mieterakte spülen, die der Mieter selbst einsehen
kann.

## 8. Stammdatenpflege als Nebenprodukt

106 von 524 Mietern haben gar keine Mailadresse im System — für sie kann keine
Regel greifen. Deshalb gehört zum Bestätigungsklick im Cockpit die Rückfrage
"Adresse am Kontakt des Mieters ergänzen?" (der DocType `Tenant Contact Update`
existiert bereits). Kennzahl: Mieter mit Mailadresse, heute 80 %, Ziel 95 %.
Diese Quote ist die Obergrenze für alles Weitere — jeder Prozentpunkt hier hebt
die Trefferquote direkt mit.

## 9. Messplan

Wöchentlich aus dem `Automation Run Log`:

* Vorschlagsquote: Anteil eingehender Nachrichten mit Vorschlag
* Präzision: bestätigt / (bestätigt + abgelehnt), getrennt nach Regelstufe
* Eindeutigkeitsquote Stufe B
* Konfliktfälle (mehrere Mieter auf eine Adresse — heute 6 Adressen)
* Korrekturquote nach Aufstieg auf Stufe 2

## 10. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| Falscher Vertrag bei Mehrfachmietern | Zwei-Ebenen-Zuordnung, B3 nur als Heuristik mit gedeckelter Konfidenz |
| Fremde Korrespondenz in der Mieterakte | Ausschlussliste (§ 5) und Portal-Guard (§ 7) |
| Ehepaare/Mitmieter mit einer Adresse (6 Fälle) | Konflikt erzeugt Vorschlag, nie Automatik |
| Altmieter behält Adresse am Kontakt | Zeitfilter B1 zwingend |
| Verwalter- oder Sammeladressen | nur als bestätigte Regel, nie aus Stammdaten abgeleitet |
| Regelwildwuchs durch den Lernkreis | Regeln mit `match_count`/`last_matched` bewerten, ungenutzte Regeln nach 12 Monaten zur Sichtung vorlegen |

## 11. Nächste Schritte, in dieser Reihenfolge

1. FEAT-14590 um diese Strategie und Akzeptanzkriterien ergänzen (kein neues
   Feature — die Bausteine existieren bereits).
2. **Messlauf, nur lesend** (Klasse A): API-Server-Script
   `ax_comm_lease_match_report` über den Bestand, Ergebnis je Regelstufe. Erst
   diese Zahlen entscheiden über die Schwellenwerte in § 4.
3. Felder aus § 6 anlegen (Klasse B, Dienstag-Deploy).
4. Resolver als API-Script mit Plan/Execute-Schalter, angebunden an die
   bestehende Automation Rule; Shadow-Betrieb 4 Wochen.
5. Bestätigungsknopf im Cockpit (Lernkreis, FEAT-14589 Baustein 2).
6. Backfill der Bestandsnachrichten chargenweise im Execute-Modus, erst nach
   erfolgreichem Shadow-Betrieb.
