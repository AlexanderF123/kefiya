# Mietverträge Schnellübersicht

Die Schnellübersicht zeigt Ihren gesamten Bestand auf einer Seite: welches Objekt welche Einheiten hat, wer dort wohnt, wer vorher dort wohnte, was vereinbart ist und was monatlich zu zahlen wäre. Sie ersetzt die gewachsene Excel-Tabelle „Soll" – mit demselben Aufbau, aber auf den gepflegten Daten.

Sie erreichen die Seite über die Seitenleiste unter **axessio Hausverwaltung › Schnellübersicht Mietverträge** oder direkt unter `/app/query-report/Mietverträge Schnellübersicht`.

> **Die Liste liest nur.** Geändert wird nichts in der Übersicht selbst, sondern in den verknüpften Mietverträgen und Einheiten – ein Klick auf eine Verknüpfung führt dorthin.

## Aufbau: vier Ebenen

Jede Zeile gehört zu einer Ebene; die Spalte **Rolle** sagt, zu welcher. Mit den kleinen Pfeilen in der ersten Spalte klappen Sie auf und zu.

| Ebene | Rolle | Was dort steht |
|---|---|---|
| 0 | **Objekt** | Das Haus. Fläche, Soll und Kaution sind die Summen des Hauses, im Status steht die Vermietungsquote („9 / 10 vermietet"). |
| 1 | **Einheit**, **Leerstand**, **Gemeinschaft** | Die Wohnung, die Garage, der Laden – mit Räumen, Fläche und den Werten des laufenden Vertrags. Rot heisst leerstehend. |
| 2 | **Aktuell**, **Vormieter**, **Künftig** | Die Mietverträge dieser Einheit, älteste zuerst. Vormieter stehen grau, künftige Mieter blau. |
| 3 | **Zeitraum** | Die Mietzeiträume eines Vertrags – jede Staffel, jede Anpassung mit ihrem Von und Bis. |

Die Zeile am Ende der Liste nennt den Stichtag und sagt, worauf sich die Beträge beziehen.

## Kennzahlen: die fünf Kacheln sind Einstiege

Oben stehen fünf Kacheln: **Einheiten**, **Vermietet**, **Leerstand**, **Soll / Monat**, **Kaution gesamt**. Sie beschreiben immer den Bestand der ausgewählten Objekte – auch dann, wenn die Liste gerade nur einen Ausschnitt zeigt.

Ein **Klick auf eine Kachel** filtert die Liste auf das, was die Zahl zählt:

- **Einheiten** – alle Einheiten, aufgeklappt bis zur Einheitenebene
- **Vermietet** – nur Einheiten mit laufendem Vertrag
- **Leerstand** – nur Einheiten ohne laufenden Vertrag
- **Soll / Monat** und **Kaution gesamt** – die vermieteten Einheiten, aufgeklappt bis zu den Verträgen, aus denen sich die Summe ergibt

Gemeinschaftsflächen zählen weder als vermietet noch als Leerstand.

## Ein- und ausklappen

Über den Kacheln stehen zwei Schalter:

- **▾ Kennzahlen** blendet das Kachelband aus und wieder ein.
- **▾ Soll je Objekt** blendet das Diagramm aus und wieder ein.

Beides bleibt so, wie Sie es zuletzt gelassen haben – persönlich, nicht für alle.

## Diagramm: Soll je Objekt

Das Diagramm zeigt das monatliche Soll je Haus. Die Spanne reicht von wenigen Euro (eine Plakatwand) bis in die Hunderttausende (ein Hotelobjekt) – linear wären die kleinen Objekte unsichtbar. Deshalb steht die Achse in der Vorgabe auf **logarithmisch**: Jeder gleiche Schritt nach oben bedeutet den zehnfachen Betrag. Die Sprechblase am Balken nennt immer den echten Betrag in Euro.

Mit dem Schalter **Achse: logarithmisch / linear** wechseln Sie die Darstellung.

## Filter

| Filter | Wirkung |
|---|---|
| **Stichtag** | Bestimmt, welcher Mietzeitraum gilt und welcher Vertrag als laufend zählt. Ein Datum in der Vergangenheit zeigt den Bestand von damals. |
| **Gesellschaft** | Nur Einheiten dieser Gesellschaft |
| **Objekt / Haus**, **Einheit** | Schränkt auf ein Haus oder eine einzelne Einheit ein |
| **Mieter** | Zeigt nur die Einheiten dieses Mieters |
| **Nutzungsart** | Wohnen, Gewerbe, Anlage |
| **Verträge** | Mit Vormietern (Vorgabe), nur aktuelle Verträge oder nur Vormieter |
| **Mietzeiträume** | Nur der geltende Zeitraum (Vorgabe), alle Staffeln oder gar keine Zeitraumzeilen |
| **Belegung** | Alle, nur vermietet oder nur Leerstand |
| **BK-Jahre (Spalten)** | Wie viele Betriebskosten-Jahresspalten gezeigt werden (0 bis 6, rückwärts ab Stichtag) |

## Die Spalten und woher sie kommen

| Spalte | Herkunft |
|---|---|
| Räume, m² | Angaben an der Einheit; fehlt die Fläche dort, wird die Fläche aus dem Mietvertrag genommen |
| Pers. | Personenstand des Vertrags, gültig am Stichtag |
| BK *Jahr* | Saldo der freigegebenen Betriebskostenabrechnung (plus = Nachzahlung, minus = Guthaben) |
| Von / Bis | Vertragszeile: Beginn und Ende des Vertrags; Zeitraumzeile: Grenzen der Staffel |
| Miete, Küche, Extras/Verw., MwSt., K-Zins, BK | Die vereinbarten Positionen des Vertrags, nach Art sortiert |
| Soll | Summe dieser sechs Spalten – der Monatsbetrag, der zu zahlen wäre |
| Kaution, Kautionsart | Vereinbarte Sicherheit und ihre Form |
| Staffel / Index | Art der Mietanpassung und die nächste vereinbarte Stufe mit Datum |
| Kommentar | Besondere Vereinbarungen aus dem Vertrag |

Die MwSt. wird mit 19 % auf die steuerpflichtigen Positionen gerechnet (erkennbar an „zzgl. MwSt." in der Positionsbezeichnung).

## Daten pflegen

Drei Spalten sind Verknüpfungen: **Einheit**, **Mietvertrag** und **Mieter**. Ein Klick öffnet den jeweiligen Datensatz – dort ändern Sie Fläche, Positionen, Kaution oder Vereinbarungen. Nach dem Speichern zeigt die Übersicht die neuen Werte.

Zusätzlich öffnen die Schaltflächen **Einheit öffnen** und **Mietvertrag öffnen** den Datensatz der markierten Zeile.

## Ihre Einstellungen

Filter, Klappzustände, Achse und Baumtiefe hängen an Ihrem Benutzerkonto: Beim nächsten Öffnen finden Sie die Liste so vor, wie Sie sie verlassen haben – auch an einem anderen Rechner. Über das Menü **⋮ › Einstellungen zurücksetzen** stellen Sie den Auslieferungszustand wieder her.

## Wenn Beträge fehlen

Die Übersicht rechnet nur mit dem, was gepflegt ist. Bleiben Felder leer, liegt das an den Stammdaten – die Liste macht diese Lücken sichtbar:

- Ein Vertrag **ohne Mietpositionen** hat kein Soll. Ergänzen Sie die Positionen im Mietvertrag.
- Positionen **ohne „Gültig ab"** werden ab Vertragsbeginn gerechnet.
- Eine Position gilt bis zu ihrer nächsten Fassung fort; eine weggefallene Position tragen Sie mit Betrag 0 fort.
- **Pers.** bleibt leer, solange kein Personenstand erfasst ist; **BK-Spalten** bleiben leer, solange für das Jahr keine freigegebene Abrechnung vorliegt.
- **Räume und m²** fehlen bei vielen Einheiten – sie werden an der Einheit gepflegt.

## Was die Übersicht nicht ist

Sie zeigt das **Soll**, also das Vereinbarte – nicht die tatsächlichen Zahlungen. Wer wann gezahlt hat, steht in den Zahlungs- und Mahnauswertungen.
