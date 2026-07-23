# Deploy-Anleitung: Dokumenten-Index (Klasse B → Deploy-Dienstag)

Reihenfolge beim Deploy auf axessio.de (Frappe Cloud v15). Alle Schritte zuerst
als Dry-Run/kleines Limit, siehe Schritt 6.

## 1. Feature-Datensatz (Pflicht vor Baubeginn)

`axessio Feature` anlegen:
- Bezeichnung: **Dokumenten-Index (SharePoint-Dokumente mit KI-Zusammenfassung & OCR)**
- Kategorie: Daten & Berichte · Status: In Entwicklung · Nutzt KI: Ja
- Reifegrad: 1 – Spezifiziert · Risikoklasse: B – Schreibend (Daten) · Bewertet am: Deploy-Datum
- Ziel: `AX Dokument` · App/Modul: n8n + Server Script (API)
- Beschreibung: Akzeptanzkriterien aus `../KONZEPT.md` §6 übernehmen.

## 2. DocType `AX Dokument`

`ax_dokument.doctype.json` als Custom DocType anlegen (Desk → DocType → neu, oder
per `frappe.get_doc(json).insert()` in einem Einmal-Setup-Script
`run_setup_ax_dokument_<YYYYMMDD>`, danach `disabled=1`).

Hinweise:
- Die Link-Ziele `Property` und `Lease` vor dem Anlegen gegen die tatsächlichen
  propms-DocType-Namen der Site prüfen; `unit_code` bleibt bewusst ein Data-Feld,
  bis das Ziel für Mieteinheiten feststeht.
- Composite-Unique (`drive_id`, `item_id`) kann Frappe nicht deklarativ; der
  Endpoint upsertet über dieses Paar. Optional zusätzlich einen DB-Index anlegen.

## 3. Server Script (Endpoint)

Setup → Server Script → neu:
- Typ: **API**, API-Methode: `upsert_ax_dokument`, Modul-Code aus
  `api_upsert_ax_dokument.py` (Kommentarkopf entfernen optional).
- **Vor Aktivierung:** Die Feldnamen des Run-Log-Blocks gegen die DocTypes
  `Automation Run Log` und `Automation Exception` abgleichen (Wrapper-Muster
  Handoff H1) — die Namen im Quellcode sind Platzhalter.
- Nach Deploy Cache-Verhalten beachten (frappe-util-api-script → Deploy + Cache).

## 4. Automation Rule

`Automation Rule` anlegen:
- Regelname: **Dokumenten-Index Sync** (muss exakt `RULE_NAME` im Script entsprechen)
- Automatik-Typ: API · Betroffener DocType: AX Dokument · Script: (das Server Script)
- Risikoklasse: B · **Autonomiestufe: 1 – Vorschlagen** (Erstläufe), Aufstieg nach
  ≥ 4 Wochen mit Korrekturquote < 2 % laut Run Log
- Zuständige Rolle: axessio Hausverwalter · Kill-Switch: aus

## 5. API-User für n8n

- Eigener User `n8n-dokumente@axessio.de`, nur Rolle mit Zugriff auf
  `AX Dokument` + Aufruf des Endpoints; API-Key/Secret erzeugen.
- Credentials ausschließlich im n8n-Credential-Store hinterlegen.

## 6. Inbetriebnahme (gestaffelt)

```
# 1) Dry-Run mit 5 Beispieldokumenten
POST /api/method/upsert_ax_dokument?dry=1        body: {docs: [...5...]}
# 2) Echtlauf klein
POST /api/method/upsert_ax_dokument?limit=100    body: {docs: [...]}
# 3) Vollbestand (n8n-Inventar-Workflow, paginiert)
# 4) Scheduler im n8n-Workflow aktivieren (stündlicher Delta-Sync)
```

Danach 1 Tag Beobachtung im Automation Run Log (Klasse-B-Regel).

## 7. Phase 2 (Anreicherung) — erst nach Kostenfreigabe

- Bestandszahl aus Phase 1 dem Owner vorlegen; Modellwahl (Haiku vs. Opus,
  Batch-API) freigeben lassen.
- Anthropic-API-Key im n8n-Credential-Store; `anreicherung_workflow.json`
  importieren, gestaffelt 50 → 500 → Vollbestand.
