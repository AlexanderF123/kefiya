# FlowFact-Analyse: Feature- und UI-Abgleich mit axessio ERPNext

Stand: 23.07.2026 · Quellenrecherche via Web (flowfact.de blockt automatisierte Direktabrufe;
Basis sind Suchtreffer von flowfact.de, service.flowfact.de, trusted.de, softwareabc24.de,
hallocleo.de, crmpro.de u.a. – Quellen am Ende).

FlowFact (FLOWFACT GmbH, Teil von ImmoScout24, >35 Jahre am Markt) ist ein **Makler-CRM**
für Vermarktung und Vermittlung von Immobilien. axessio ERPNext ist eine
**Hausverwaltungsplattform**. Der Abgleich erfolgte auf Wunsch vollständig (auch
Verkaufs-/Maklerfunktionen).

---

## 1. FlowFact-Featureliste (nach Modulen)

### Kontakte & Interessenten
| Feature | Beschreibung |
|---|---|
| Kontaktmanagement | Kontaktakte mit Tabs „Information", „Dokumente", „Sonstiges"; flexible Datenerfassung (Preisvorstellung, Lage etc.) |
| Anfragen-/Interessentenmanagement | Zentrale Übersicht aller Portal-Anfragen und Matches; Anforderungsprofile direkt mit Objekt-Exposés vergleichen |
| Suchprofile & Matching | Interessenten-Suchprofile (Miete/Kauf, Ort, Größe, Budget); automatisches Matching bei neuen Objekten |
| ImmoScout24-API | Anfragen von IS24 laufen automatisch ins CRM; „Aktiv ansprechen": bis 50 passende IS24-Suchende mit Teaser-Exposé direkt kontaktieren |
| DSGVO-Modul | Einwilligungen digital erfassen, dokumentieren, nachweisen |

### Objekte & Vermarktung
| Feature | Beschreibung |
|---|---|
| Objektverwaltung | Stammdaten, Bilder, Dokumente je Immobilie |
| Objektphasen | Vermarktungs-Pipeline: Akquise → Vorbereitung → Vermarktung → Abschluss → After-Sales |
| Deals | Interessenten-Funnel je Objekt, mobil steuerbar |
| Exposé-Erstellung | PDF-Exposés, interaktive Online-Exposés (inkl. digitalem Maklervertrags-Abschluss), Teaser-Exposés ohne Adresse |
| Portalexport (OpenImmo) | Übertragung an ImmoScout24, Immowelt u.a.; automatische Neuveröffentlichung nach 24h |
| Stacking Plan (Commercial) | Visuelle Darstellung der Vermietungssituation je Gebäude/Fläche |
| Besichtigungs-Buchung | Objektspezifische Online-Buchungsformulare für Besichtigungstermine (timum-Integration) |

### Kommunikation & Organisation
| Feature | Beschreibung |
|---|---|
| E-Mail-Client + Outlook-Addin | Integrierter Mailclient oder Outlook/Office-365-Anbindung |
| E-Mail-Vorlagen & Serienmails | Vorlagen mit Platzhaltern; Serienmails ohne Versandlimit, eigene Empfängerlisten |
| Mailmanager | Automatisierte Kommunikationsstrecken; wiederkehrende Aufgaben vollständig automatisieren, frei kombinierbare Workflows |
| Aufgaben + Taskboard | Aufgaben an Kontakt/Objekt/Deal; Kanban-Taskboard |
| Termine & Kalender | Kalender mit Objekten/Kontakten/Aufgaben verknüpft |
| Telefonie | CTI-Integration (Anrufe aus dem CRM) |

### Akquise & Bewertung
| Feature | Beschreibung |
|---|---|
| Lead Hunter | Online-Preisschätzung als Widget auf der Makler-Website → Eigentümer-Leads mit voller Adresse im Cockpit |
| Sprengnetter-Bewertungscenter | Marktwertanalyse, Vergleichsmieten, Lagebeurteilung, Leadakquise-Apps |
| Tippgeber | Tippgeber-Verwaltung und -Provisionierung |
| Vertrags-/Dokumentvorlagen | Mitgelieferte Vertragsmuster + regelmäßige Rechtstipps |

### KI, Mobile, Plattform
| Feature | Beschreibung |
|---|---|
| KI (ChatGPT-Integration) | Objekt-, Lage- und Ausstattungsbeschreibungen automatisch generieren |
| FLOWFACT GO (App) | Volles CRM mobil: Datenpflege, Exposéversand, Portalübertragung, Navigation zum Termin, Interessenten-Management |
| Statistiken & Controlling | Dashboards für Vertrieb, Akquise, Büroorganisation, Marketing |
| Offene API | Eigene Szenarien anbindbar; weniger Marktplatz-Integrationen als onOffice |
| Onboarding | Userlane-Touren direkt im Dashboard-Widget |

**Preismodell:** ab 159 €/Monat (inkl. 2 Nutzer), +79 €/Monat je weiterer Nutzer,
279 € Einrichtung, 14 Tage Test. Webinare + Support inklusive.

**Nutzerfeedback:** gelobt werden automatischer Exposé-Versand, Support und
Entwicklungstempo sowie die GO-App; kritisiert wurden früher die Mobile-Ansicht (vor der
App) und die im Vergleich zu onOffice geringere Zahl an Schnittstellen.

---

## 2. Gap-Analyse: FlowFact vs. axessio

### 2.1 In axessio bereits vorhanden
| FlowFact-Feature | axessio-Pendant |
|---|---|
| Portalveröffentlichung | FEAT-5198 Vermietungsanzeigen auf Knopfdruck |
| Anfragen-Import | FEAT-5200 Automatischer Import von Mietinteressenten |
| Interessenten-Vorauswahl | FEAT-5201 Automatische Vorauswahl |
| Besichtigungs-Buchung | FEAT-5202 Online-Termin-Findung |
| Selbstauskunft | FEAT-5203 Online-Mieter-Selbstauskunft mit Upload |
| Vertragserstellung aus Interessentendaten | FEAT-5204 / FEAT-10080 Mietvertrag-Automatik |
| Kundenportal | FEAT-5205 Mietinteressentenportal, FEAT-5209 Mieterportal |
| E-Mail-Vorlagen | FEAT-5192 Mustertexte (E-Mail, Telegram, WhatsApp) |
| Kalender | FEAT-5191 Universalkalender |
| zentrale Kommunikations-Oberfläche | FEAT-5190 Cockpit im Outlook-Design |
| Aufgaben/Vorgänge | FEAT-5194–5197 Vorgangsverwaltung mit Automatiken |
| KI-Texte | FEAT-5276 KI-Textvorschläge (+ KI-Chat/Agent 5185/5277) |
| Statistiken/Dashboards | FEAT-5272, FEAT-10118 Management-Dashboard |
| Volltextsuche | FEAT-5228, FEAT-10156 |
| DSGVO-Auskunft | FEAT-10319 (Art. 15) – nur Auskunft, kein Einwilligungsmanagement |
| Offene API | FEAT-5229, FEAT-5188 MCP |

*axessio geht in Hausverwaltungsthemen weit über FlowFact hinaus (FinTS-Banking,
Buchhaltung, BKA, Mahnwesen, DATEV, Facility, Personal, KI-Agent) – FlowFact deckt
Verwaltung bewusst nicht ab.*

### 2.2 Lücken – zur Aufnahme ausgewählt (12)
| # | Feature | Kategorie-Vorschlag | Aufwand |
|---|---|---|---|
| 1 | Exposé-Modul (PDF + interaktives Online-Exposé, Teaser, KI-Texte, Tracking) | Vermietung & Interessenten | mittel |
| 2 | Aktives Suchprofil-Matching (Bestandspool → Auto-Angebot bei freier Einheit) | Vermietung & Interessenten | mittel |
| 3 | Vermietungs-Pipeline als Kanban (Anfrage→Besichtigung→Selbstauskunft→Vertrag; Frappe-Kanban) | Vermietung & Interessenten | klein–mittel |
| 4 | Serienmail-Kampagnen an Segmente (Mieter je Haus, alte Interessenten; ERPNext Newsletter/Email Campaign als Basis) | Cockpit & Kommunikation | klein–mittel |
| 5 | Telefonie-Integration CTI (Anruf aus Akte, Anrufprotokoll) | Cockpit & Kommunikation | mittel |
| 6 | DSGVO-Einwilligungsmanagement (Erfassung, Nachweis, Löschkonzept) | Plattform & Administration | mittel |
| 7 | Digitale Signatur für Verträge (Mietvertrag online signieren) | Verträge & Mieter | mittel |
| 8 | Eigentümer-Reporting (Vermarktungs-/Aktivitätenreport an Auftraggeber) | Daten & Berichte | klein–mittel |
| 9 | Mobile App / PWA (Kontakte, Objekte, Aufgaben, Termine, Fotos, Navigation) | Plattform & Administration | groß |
| 10 | Stacking Plan (visuelle Gebäude-/Etagenansicht mit Vermietungsstatus) | Vermietung & Interessenten | mittel |
| 11 | Interaktive Onboarding-Touren (Userlane-Pendant, ergänzt Hilfe-Drawer) | KI & Hilfe | mittel |
| 12 | Personalisierbare Widget-Dashboards (Drag&Drop-Startseite je Nutzer) | Plattform & Administration | mittel |

Verwandte bestehende Features: #3 ↔ FEAT-7944 „Bereich Vermietung"; #12 ↔ FEAT-7943
„Mein Tag"; Objekt-/Mieterakte FEAT-7903.

> Hinweis: Die Anlage als `axessio Feature`-Datensätze wurde in dieser Session nicht
> ausgeführt (Freigabe zurückgezogen); die Tabelle oben ist als Vorlage dafür gedacht.

### 2.3 Bewusst zurückgestellt (4)
| Feature | Grund |
|---|---|
| Lead Hunter / Bewertungswidget | Nur relevant bei Ankauf/Akquise von Verwaltungsmandaten |
| Immobilienbewertung / Marktwertanalyse | Verwandt mit FEAT-7912 Mietpreis-Vorschlag; braucht externe Marktdaten |
| Provisionsabrechnung / Verkaufsabwicklung | Nur bei Geschäftsfeld Vermittlung/Verkauf |
| Tippgeber-Verwaltung | Optional („Mieter werben Mieter"), geringer Aufwand, bei Bedarf nachziehen |

---

## 3. UI-Vergleich und Verbesserungsvorschläge (Ziel: einfache Bedienung)

### 3.1 FlowFacts Bedienkonzept
- **Eine Startseite:** Widget-Dashboard nach Login (Anfragen, Aufgaben, Immobilien,
  Onboarding); Widgets per Drag&Drop anordenbar, Spaltenlayout wählbar.
- **Wenige Kernobjekte:** Kontakte, Immobilien, Deals, Aufgaben, Termine – alles andere
  hängt an diesen Akten.
- **Pipeline-/Board-Denken:** Objektphasen und Taskboard statt langer Listen.
- **Akten mit Tabs:** Kontakt/Objekt als Akte (Info / Dokumente / Sonstiges).
- **Geführtes Onboarding:** interaktive Userlane-Touren im Dashboard.
- **Mobile App** als vollwertiger Kanal.

### 3.2 axessio heute
Frappe/ERPNext-Desk mit vielen Workspaces und DocType-Formularen; bereits vorhanden:
Cockpit im Outlook-Design, Vermietungsliste, Management-Dashboard, Hilfe-Drawer,
verbesserte Awesomebar, neu geordnete Sidebar. Stärke: Funktionstiefe. Schwäche für
Gelegenheitsnutzer: viele Einstiegspunkte, rohe Formulare, Admin-Elemente sichtbar.

### 3.3 Priorisierte Vorschläge
| Prio | Vorschlag | Was konkret | Bezug |
|---|---|---|---|
| P1 | „Mein Tag"-Startseite | Eine Widget-Startseite je Rolle: heutige Termine, offene Vorgänge, neue Anfragen, zuletzt bearbeitete Akten; Aufbau als Workspace + Custom HTML Block | FEAT-7943 |
| P2 | Vermietungs-Kanban | Vermietungsprozess als Board mit Karten-Drag&Drop statt Listen | FEAT-7944, Gap #3 |
| P3 | Navigation verschlanken | Geschlossene HV-Oberfläche mit 5–7 Bereichen (Mein Tag, Kommunikation, Vermietung, Verträge, Finanzen, Instandhaltung, Berichte); Admin-Workspaces für Normalnutzer ausblenden | FEAT-7942 |
| P4 | Akten-Prinzip | Objekt-/Mieterakte mit Tabs (Info, Dokumente, Kommunikation, Historie) als Standard-Einstieg statt DocType-Rohformular | FEAT-7903 |
| P5 | Onboarding-Touren | Geführte Klick-Touren für Kernprozesse (neue Vermietung, Vorgang bearbeiten), verzahnt mit Hilfe-Drawer | Gap #11 |
| P6 | Widget-Dashboards | Nutzer ordnen ihre Startseiten-Widgets selbst an (Drag&Drop) | Gap #12 |
| P7 | Globale Schnellanlage | „+ Neu"-Knopf überall: Vorgang, Kontakt, Termin, Notiz in 2 Klicks | – |
| P8 | Mobile/PWA | Kernfunktionen für unterwegs (Hausmeister, Besichtigungen) | Gap #9 |

**Leitprinzip aus dem FlowFact-Vergleich:** Der Normalnutzer sieht Prozesse und Akten,
nicht DocTypes. Je Rolle eine Startseite, je Prozess ein Board, je Datensatz eine Akte.

---

## 4. Quellen
- https://flowfact.de/ · https://flowfact.de/funktionen-von-flowfact/ · https://flowfact.de/crm/
- https://flowfact.de/interessentenmanagement/ · https://flowfact.de/akquise/ · https://flowfact.de/suchprofil-matching/
- https://flowfact.de/flowfact-go/ · https://flowfact.de/ki-integration-chatgpt-kommt-zu-flowfact/
- https://flowfact.de/das-neue-dashboard/ · https://flowfact.de/der-optimierte-lead-hunter/
- https://flowfact.de/sprengnetter-bewertungsapps/ · https://flowfact.de/telefonie/ · https://flowfact.de/commercial/
- https://flowfact.de/die-immoscout24-vorteile/ · https://flowfact.de/neue-anfragen-von-immoscout24-via-api/
- https://service.flowfact.de/ (Serviceportal: Dashboard, Widgets, Aufgaben, Termine, Suchprofile, Objektphasen)
- https://performer-service.flowfact.de/ (Performer-Legacy: Serienmails, Kalender, E-Mail)
- https://trusted.de/flowfact · https://trusted.de/flowfact-kosten
- https://www.softwareabc24.de/immobilienmakler-software/flowfact · https://www.softwareabc24.de/vergleiche/flowfact-vs-onoffice
- https://hallocleo.de/blog/crm-immobilienmakler-vergleich-2026 · https://neue.immo/flowfact-die-immobiliensoftware-fuer-digitales-makeln/
- https://www.crmpro.de/post/der-flowfact-mailmanager · https://www.crmpro.de/post/flowfact-datenschutz-l%C3%B6sung-flowfact-dsgvo-modul-datenschutz-leicht-gemacht
