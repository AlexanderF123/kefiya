# EU AI Act — Einordnung für Kefiya

**Stand:** 27.07.2026 · **Bewertete Version:** `develop` @ `1196ab6`

## Ergebnis in einem Satz

Kefiya ist **kein KI-System** im Sinne von Art. 3 Nr. 1 KI-VO und löst damit
**keine** Anbieterpflichten aus — die Pflichten, die uns treffen, entstehen
nicht aus dem Produkt, sondern daraus, dass **wir KI-Werkzeuge einsetzen**
(Betreiberrolle) und dass **wir Kefiya mit KI-Assistenz entwickeln**.

---

## 1. Rechtsstand

Maßgeblich ist die KI-VO (VO (EU) 2024/1689) **in der Fassung der VO (EU)
2026/1744** ("Digital Omnibus on AI", ABl. 24.07.2026, in Kraft seit
27.07.2026). Der Omnibus hat die Fristen verschoben:

| Regelungsbereich | Geltung |
|---|---|
| Verbotene Praktiken (Art. 5), KI-Kompetenz (Art. 4) | seit 02.02.2025 |
| GPAI-Modellpflichten (Art. 53 ff.) | seit 02.08.2025 |
| **Transparenzpflichten (Art. 50)** | **ab 02.08.2026** |
| Art. 50 Abs. 2 für vorher in Verkehr gebrachte generative Systeme | Schonfrist bis 02.12.2026 |
| Marktüberwachung / nationale Behörden (DE) | ab 02.08.2026 |
| Hochrisiko Anhang III (eigenständige Systeme) | **02.12.2027** (vorher 02.08.2026) |
| Hochrisiko Anhang I (in Produkte eingebettet) | 02.08.2028 |

Die Verschiebung betrifft **nur** den Hochrisiko-Block. Der 02.08.2026 ist
nicht entfallen: Art. 50 und die Marktüberwachung starten wie geplant.

---

## 2. Ist Kefiya ein KI-System? — Nein

Art. 3 Nr. 1 verlangt ein System, das aus Eingaben **ableitet** ("infers"), wie
Ausgaben zu erzeugen sind. Erwägungsgrund 12 und die Kommissions-Leitlinien zur
KI-System-Definition (C(2025) 924 vom 06.02.2025) nehmen ausdrücklich aus:
Systeme, die **ausschließlich auf von Menschen festgelegten Regeln** beruhen,
klassische Heuristiken und einfache Datenverarbeitung.

Genau das ist Kefiya. Jede Entscheidungslogik ist handgeschrieben und
deterministisch — es gibt kein Modell, kein Training, keine Gewichte, keine
Wahrscheinlichkeiten, keinen Score:

| Funktion | Datei | Logik |
|---|---|---|
| Zahlungs-/Rechnungszuordnung | `utils/sql/payment_to_saleInvoice.sql` | SQL-Join auf **exakter** Betragsgleichheit + Datumsfenster + Kundengleichheit; `PaymentCount = 1 AND SalesCount = 1` verwirft jede Mehrdeutigkeit |
| Auto-Reconcile nach Import | `utils/auto_reconcile.py` | delegiert an ALYF Banking (Regelwerk) + feste Vorkassenregel |
| Partei-Erkennung | `utils/auto_reconcile.py:172` `_identify_party` | exakter IBAN-Vergleich; bei >1 Treffer `(None, None)` — kein Raten |
| Planned-Payment-Matching | `utils/planned_payment.py:277` | IBAN-Gleichheit, sonst Teilstring-Namensvergleich; ohne klares Signal **kein** Match |
| „Forecast" | `utils/planned_payment.py:79` | Kalenderarithmetik (`add_months`) über Daueraufträge — eine Fortschreibung bekannter Termine, **keine** Prognose |

Der Begriff *Forecast* im UI ist insofern irreführend, aber rechtlich
unschädlich: es wird nichts geschätzt, sondern nur ausmultipliziert.

Die Toleranzen (`AMOUNT_EPSILON = 0.005`, `MATCH_DATE_TOLERANCE_DAYS = 3`) sind
fest kodierte Konstanten, keine gelernten Schwellwerte. Auch die
Abhängigkeiten enthalten nichts KI-Bezogenes (`pyproject.toml`: nur
`fints==5.0.0b1`).

**Folge:** keine Anbieterpflichten, keine Konformitätsbewertung, keine
CE-Kennzeichnung, keine Registrierung, keine Art.-50-Transparenzpflicht für
das Produkt.

### Auch bei anderer Auslegung: nicht Hochrisiko

Selbst wenn man Kefiya als KI-System einordnen wollte, wäre es nicht
hochrisikant. Anhang III Nr. 5 lit. b erfasst die **Bonitätsbewertung
natürlicher Personen**. Kefiya bewertet niemanden — es ordnet bereits
gebuchte Zahlungen bereits bestehenden Rechnungen zu. Buchhaltungsautomatik
ist in keinem Anhang-III-Punkt gelistet.

---

## 3. Wo wir tatsächlich fallen

### 3.1 Betreiberrolle (Art. 3 Nr. 4) — das ist der eigentliche Treffer

Sobald **ein** Mitarbeiter ein KI-Werkzeug beruflich nutzt, sind wir Betreiber.
Bei uns sichtbar mindestens: KI-Coding-Assistenz in der Kefiya-Entwicklung,
Meeting-Transkription (Fireflies), KI-Funktionen im ERPNext-Umfeld.

**Art. 4 (KI-Kompetenz)** gilt seit 02.02.2025 für Anbieter *und* Betreiber:
Personal, das KI einsetzt, braucht ein angemessenes Kompetenzniveau. Der
Omnibus hat Art. 4 sprachlich entschärft und stärker als Förderauftrag von
Kommission und Mitgliedstaaten gefasst; die Sekundärliteratur ist sich über die
Reichweite dieser Abschwächung uneinig. Praktisch ändert das wenig: Art. 4
trägt keine eigene Bußgeldnorm in Art. 99, aber ab **02.08.2026** kann die
nationale Marktüberwachung nachfragen — und dann wollen wir etwas vorzeigen
können. Aufwand ist gering, Nachweisbarkeit ist der Punkt.

**Zu tun:** kurze interne Richtlinie „KI-Einsatz" (welche Tools sind
freigegeben, was darf nicht hineingegeben werden — Mandanten-, Bank-,
Personendaten), einmalige Unterweisung, Teilnahme dokumentieren. Zwei Seiten
plus Teilnehmerliste genügen; ein KI-Beauftragter oder eine Zertifizierung ist
**nicht** vorgeschrieben.

**Art. 50 Abs. 1/4** (Offenlegung gegenüber Personen, Deepfake- und
Publikumstext-Kennzeichnung) trifft uns nur, wenn wir Chatbots oder
veröffentlichte KI-Inhalte einsetzen. In Kefiya: nichts davon. Falls im
Marketing oder im Kundenkontakt KI-Inhalte entstehen, gilt es ab 02.08.2026 —
das ist außerhalb dieses Repos zu klären.

### 3.2 Zu prüfen: Emotionserkennung am Arbeitsplatz

Art. 5 Abs. 1 lit. f **verbietet** seit 02.02.2025 KI zur Ableitung von
Emotionen am Arbeitsplatz — das ist die schärfste Kategorie (bis 35 Mio. € /
7 % Jahresumsatz). Meeting-Intelligence-Tools bieten teils Sentiment- oder
„Talk-Ratio"-Analysen an. Ich habe **nicht** festgestellt, dass wir so etwas
nutzen; es ist ein Prüfpunkt, kein Befund: bei Fireflies (und vergleichbaren
Tools) kontrollieren, ob Sentiment-/Emotionsanalyse über Mitarbeiter aktiv ist,
und sie andernfalls deaktiviert lassen.

### 3.3 KI-generierter Code — keine Kennzeichnungspflicht

Kefiya wird erkennbar mit KI-Assistenz entwickelt. Daraus folgt **keine**
Markierungspflicht nach der KI-VO:

- Art. 50 Abs. 2 (maschinenlesbare Markierung synthetischer Inhalte) adressiert
  den **Anbieter des generativen Systems**, nicht uns als Nutzer. Zudem greift
  die Ausnahme für „unterstützende Funktion bei der Standardbearbeitung".
- Art. 50 Abs. 4 trifft Betreiber nur bei Deepfakes und bei Texten, die zur
  **Unterrichtung der Öffentlichkeit über Angelegenheiten von öffentlichem
  Interesse** veröffentlicht werden. Quellcode ist beides nicht.

Wir müssen Commits also **nicht** AI-Act-halber kennzeichnen. Dass wir es über
`Co-Authored-By` trotzdem tun, ist saubere Provenienz — bitte beibehalten, aber
als Engineering-Praxis, nicht als Rechtspflicht.

### 3.4 Nicht KI-VO, aber im selben Atemzug zu klären: DSGVO

Die Auto-Zuordnung verarbeitet personenbezogene Daten (IBAN, Name von
Zahlenden) und legt in `_create_advance_payments` **automatisiert** Belege an.
Art. 22 DSGVO greift erst bei rechtlicher oder ähnlich erheblicher Wirkung — eine
interne Verbuchung dürfte darunter liegen, aber Verarbeitungsverzeichnis,
Rechtsgrundlage und Löschkonzept gelten unabhängig davon. `match_on_bank_transaction`
löscht Treffer bewusst ohne Audit-Historie (`planned_payment.py:295`); das ist
datensparsam, aber sollte im Löschkonzept stehen. Das ist eine
Datenschutz-, keine KI-Act-Aufgabe — hier nur zur Vollständigkeit vermerkt.

---

## 4. Was das konkret heißt

| # | Maßnahme | Wer | Bis |
|---|---|---|---|
| 1 | Diese Einordnung als Nachweis ablegen und bei Funktionsänderungen fortschreiben | Entwicklung | erledigt |
| 2 | Interne KI-Nutzungsrichtlinie + Unterweisung, Teilnahme dokumentiert (Art. 4) | Geschäftsführung | 02.08.2026 |
| 3 | Inventar der eingesetzten KI-Tools (Zweck, Anbieter, Datenkategorien) | IT | 02.08.2026 |
| 4 | Sentiment-/Emotionsanalyse in Meeting-Tools prüfen und ggf. abschalten (Art. 5 Abs. 1 lit. f) | IT | sofort |
| 5 | Kefiya-Verarbeitungen ins Verarbeitungsverzeichnis (DSGVO) | Datenschutz | laufend |

---

## 5. Wann diese Einordnung ungültig wird

Die Bewertung hängt allein daran, dass Kefiya nichts *ableitet*. Sie ist neu zu
prüfen, sobald einer dieser Punkte eintritt:

- **Unscharfes Matching** — gelernte Schwellwerte, Ähnlichkeits-/Confidence-Scores
  oder statistische Zuordnung statt exakter Gleichheit.
- **LLM-Einsatz im Produkt**, z. B. um Verwendungszwecke zu interpretieren,
  Buchungssätze vorzuschlagen oder Kontoauszüge zu klassifizieren.
- **Echte Prognose** — Liquiditäts- oder Zahlungseingangsvorhersage aus
  historischen Daten (statt Fortschreibung von Daueraufträgen).
- **Bonitäts- oder Mahnwürdigkeitsbewertung natürlicher Personen.** Das wäre
  nicht nur ein KI-System, sondern **Hochrisiko** nach Anhang III Nr. 5 lit. b —
  mit Risikomanagement, Daten-Governance, technischer Dokumentation (Anhang IV),
  Protokollierung, menschlicher Aufsicht und Registrierung. Pflichten ab
  **02.12.2027**.

Faustregel für Reviews: **Sobald eine Zuordnung nicht mehr aus fest
kodierten Regeln folgt, ist die KI-VO wieder auf dem Tisch.**

---

## 6. Textbaustein für Kunden- und Auditrückfragen

> Kefiya (FinTS-Konnektor für ERPNext) enthält keine Komponente künstlicher
> Intelligenz. Die Zuordnung von Zahlungen zu Belegen erfolgt ausschließlich
> über deterministische, von Menschen festgelegte Regeln (exakter Betrags- und
> IBAN-Abgleich innerhalb definierter Datumsfenster). Es werden keine Modelle
> trainiert, eingebunden oder abgefragt und keine Wahrscheinlichkeits- oder
> Score-Werte gebildet. Kefiya ist damit kein KI-System im Sinne von Art. 3
> Nr. 1 der Verordnung (EU) 2024/1689; Anbieterpflichten der KI-Verordnung
> werden nicht ausgelöst.

---

## 7. Grenzen dieser Einordnung

Dies ist eine technische Selbsteinschätzung auf Basis des Codes, keine
Rechtsberatung. Sie deckt **den Kefiya-Quellcode** ab; die Betreiberpflichten
in Abschnitt 3 betreffen die Organisation und sind hier nur so weit erfasst,
wie sie aus diesem Repository erkennbar waren. Die Reichweite der
Art.-4-Abschwächung durch VO (EU) 2026/1744 ist in der Literatur noch
uneinheitlich dargestellt — die empfohlenen Maßnahmen sind bewusst so
gewählt, dass sie in beiden Lesarten tragen. Fremdkomponenten (ALYF Banking,
ERPNext-Kern, python-fints) sind nicht mitbewertet.
