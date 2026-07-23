# Dokumenten-Index: SharePoint-Dokumente mit KI-Zusammenfassung & OCR in ERPNext

Stand: 2026-07-23 · Risikoklasse **B** (neuer DocType + schreibende Automatik) · Status: Konzept + Bau-Artefakte (Reifegrad 1)

## 1. Ausgangsfrage und Entscheidung

> „Ich will eine Datenbank aller unserer Dokumente in SharePoint, mit kurzer Inhaltszusammenfassung, OCR, bei Bildern auch. Nutzen wir dafür besser neue Felder in SharePoint oder in ERPNext?"

**Entscheidung: Die Felder kommen nach ERPNext.** Die Dokumente selbst bleiben in SharePoint; ERPNext erhält einen Index-DocType `AX Dokument` mit Metadaten, Kurzzusammenfassung, Volltext/OCR und (später) Verknüpfung zu Objekt/Mieteinheit/Vertrag.

Begründung:

1. **SharePoint-Spalten skalieren schlecht über Quellen hinweg.** Der Bestand verteilt sich auf mindestens die Site „HausverwaltungaxessioGmbH" (Bibliotheken „Freigegebene Dokumente", „Dokumentvorlagen"), die Site „DigitalAdmin" und den OneDrive-Ordner „Email attachments from Flow". Eigene Spalten müssten je Bibliothek/Site provisioniert und konsistent gehalten werden; lange OCR-Volltexte passen zudem schlecht in Listenspalten.
2. **Nur ERPNext kann verknüpfen.** Die Ordnerpfade enthalten bereits Objekt- und Einheitencodes (`103 HD Sofienstr. 6-10/Mieter/103-008-02 …`, Vertragsnummern wie `E-304-005-03`). Ein Index in ERPNext kann Dokumente automatisch mit Mietobjekt, Mieteinheit, Lease und Mieter verlinken — die Basis für Auswertungen wie „Mieter ohne abgelegten Mietvertrag".
3. **Prozesskonformität.** Nach dem axessio-Entwicklungsprozess gilt: n8n transportiert, ERPNext entscheidet und speichert; jede produktive Automatik braucht Automation Rule + Run Log — beides lebt in ERPNext.
4. **SharePoint verliert nichts.** Die native SharePoint-/Microsoft-Volltextsuche bleibt unverändert nutzbar. Der Mehrwert (strukturierter Index, KI-Zusammenfassung, Geschäftsdaten-Verknüpfung) gehört zu den Stammdaten.

Ein optionales Rückschreiben der Zusammenfassung als SharePoint-Spalte ist als späterer Ausbauschritt möglich, aber nicht Teil von Phase 1–2.

## 2. Ist-Aufnahme (Recherche vom 2026-07-23)

- SharePoint Hausverwaltung-Site: objektweise Struktur, zehntausende Dokumente (Suche nach „Mietvertrag" allein: ~54.000 Treffer über alle Quellen). Viele Scans (CamScanner-PDFs) und Fotos.
- OneDrive `admin@…/Documents/Email attachments from Flow`: automatisch abgelegte Mail-Anhänge (u. a. Mietverträge) — laufend wachsend.
- ERPNext: ~24.400 Dateianhänge (`tabFile`), bislang keine SharePoint-/OCR-Felder; Automations-Infrastruktur (Automation Rule, Automation Run Log, Automation Exception) vorhanden.

## 3. Architektur

```
SharePoint / OneDrive (Originale bleiben hier)
        │  Graph API Delta-Query (n8n, stündlich)
        ▼
n8n „Dokumenten-Inventar“ ──► ERPNext API-Endpoint upsert_ax_dokument
                                   │ validiert, Kill-Switch, Run Log
                                   ▼
                             DocType AX Dokument (Index)
                                   ▲
n8n „Dokumenten-Anreicherung“ ─────┘
   lädt Datei via Graph, Claude API liest PDF/Bild direkt
   (Text + OCR + Zusammenfassung + Kategorie in einem Schritt)
```

- **Ein KI-Schritt statt separater OCR-Engine:** Die Claude API verarbeitet PDFs (auch reine Scans) und Bilder nativ als `document`-/`image`-Block; Zusammenfassung, Kategorie, Sprache und Volltext-Auszug kommen als Structured Output zurück. Limits: base64-PDF max. 32 MB / 600 Seiten (100 Seiten bei Haiku); Überläufer werden gesplittet oder mit Status „Fehler" markiert.
- **n8n transportiert nur.** Es schreibt nie direkt per REST in den DocType, sondern ruft ausschließlich den API-Server-Script-Endpoint auf, der validiert, upsertet und ins Run Log schreibt. Antwortet der Endpoint „blocked" (Kill-Switch), bricht der Workflow ab.
- **Eigener ERPNext-API-User** für n8n mit Minimalrollen; Secrets nur im n8n-Credential-Store.

## 4. Datenmodell: DocType `AX Dokument` (Custom)

Definition: [`erpnext/ax_dokument.doctype.json`](erpnext/ax_dokument.doctype.json). Kernfelder:

| Feld | Typ | Zweck |
|---|---|---|
| `source` | Select (SharePoint/OneDrive/ERPNext) | Quellsystem |
| `drive_id`, `item_id` | Data (zusammen eindeutig) | Graph-Identität, Upsert-Schlüssel |
| `web_url` | Data (URL) | Klickbarer Link zum Original |
| `file_name`, `file_type`, `file_size`, `folder_path` | Data/Int | Metadaten |
| `modified_on_source`, `etag` | Datetime/Data | Änderungserkennung für Delta-Sync |
| `summary` | Small Text | KI-Kurzzusammenfassung (deutsch, 2–3 Sätze) |
| `full_text` | Long Text | Extrahierter Text bzw. OCR-Ergebnis (durchsuchbar) |
| `document_category` | Select | Mietvertrag, Nachtrag, Rechnung, Schreiben, Protokoll, Foto, … |
| `language` | Data | Erkannte Sprache |
| `property`, `rental_unit`, `lease`, `customer` | Link (optional) | Auto-Verknüpfung per Pfad-Heuristik (Phase 3) |
| `processing_status` | Select | Neu → Text extrahiert → Zusammengefasst / Fehler |
| `error_message`, `last_synced` | Small Text/Datetime | Pipeline-Betrieb |

UI-Labels deutsch, technische Feldnamen englisch (Sprachcode `de`).

## 5. Rollout-Phasen

| Phase | Inhalt | Kosten | Voraussetzung |
|---|---|---|---|
| **1 Inventar** | DocType + Endpoint deployen, n8n-Inventar-Workflow: Delta-Query je Drive → Metadaten-Upsert. Erst `?dry=1`, dann `?limit=100`, dann Vollbestand, dann Scheduler. | keine | Deploy-Dienstag, Review |
| **2 Anreicherung** | n8n-Anreicherungs-Workflow: Datei laden → Claude API (Batch für Bestand, −50 %) → PATCH an Endpoint. Gestaffelt 50 → 500 → Vollbestand. | Modellwahl durch Owner: Haiku grob 100–300 € einmalig, Opus grob 500–1.500 € (Bestandsschätzung 30–60 Tsd. Dokumente; echte Zahl liefert Phase 1) | Kostenfreigabe nach Inventar |
| **3 Verknüpfung** | Server-seitige Heuristik: Einheiten-/Vertragscodes aus Pfad/Dateiname → Links auf Mieteinheit/Lease (Autonomiestufe 0/1: erst Vorschlag + Stichprobe). | keine | Trefferquote im Run Log |
| **4 UI & DoD** | Workspace-Seite, Slideout-Hilfe, Doku, Reifegrad-Pflege im Feature-Datensatz. | keine | — |

## 6. Prozess-Compliance (axessio-dev-process)

- **Vor Baubeginn:** `axessio Feature`-Datensatz „Dokumenten-Index" anlegen (Kategorie „Daten & Berichte", Risikoklasse B, Reifegrad 1, Akzeptanzkriterien s. u.).
- **Automation Rule** „Dokumenten-Index Sync" (Typ Extern/API, Autonomiestufe 1 – Vorschlagen für den Erstlauf, danach Aufstieg nach Nachweis), Kill-Switch wird vom Endpoint vor jedem Lauf geprüft.
- **Run-Log-Pflicht:** Jeder Endpoint-Aufruf schreibt einen Automation-Run-Log-Eintrag (Trigger, Anzahl neu/aktualisiert/Fehler); Fehler erzeugen eine Automation Exception (Sev 3, Rolle Hausverwalter).
- **Backfill-Muster:** Endpoint unterstützt `?dry=1` (Plan ohne Schreiben) und `?limit=` (gestaffelte Läufe) gemäß frappe-util-api-script.
- **Deploy:** Klasse B → Dienstag, danach 1 Tag Beobachtung im Run Log. Workflow-JSONs und Script-Quellen sind in diesem Ordner versioniert.

**Akzeptanzkriterien (Feature-Datensatz):**
1. Vollständiges Inventar der Phase-1-Quellen, jeder Datensatz mit klickbarem Original-Link.
2. Delta-Sync erkennt neue und geänderte Dateien (Test: Datei ändern → nächster Lauf aktualisiert).
3. Zusammenfassungen deutsch, 2–3 Sätze, fachlich korrekt (Owner-Stichprobe über 10 gemischte Dokumente: Text-PDF, Scan, Foto, docx).
4. Volltext in ERPNext durchsuchbar; Liste nach Kategorie/Objekt filterbar.
5. Alle Läufe vollständig im Automation Run Log, Fehler als Automation Exception.

## 7. Artefakte in diesem Ordner

| Datei | Inhalt |
|---|---|
| `erpnext/ax_dokument.doctype.json` | DocType-Definition (Custom) zum Import |
| `erpnext/api_upsert_ax_dokument.py` | Quellcode des API-Server-Scripts (Ingestion-Endpoint) |
| `erpnext/setup_ax_dokument.md` | Deploy-Anleitung (DocType, Script, Automation Rule, API-User) |
| `n8n/inventar_workflow.json` | n8n-Workflow „Dokumenten-Inventar" (Import-Vorlage) |
| `n8n/anreicherung_workflow.json` | n8n-Workflow „Dokumenten-Anreicherung" (Import-Vorlage) |
