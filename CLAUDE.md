# Projekt-Memory / Arbeitsregeln

## axessio ERPNext — Skripte NIE ohne Prüfung veröffentlichen

**Verbindliche Regel:** Bevor ein Skript in der axessio-ERPNext-Instanz (axessio.de, Frappe Cloud v15)
veröffentlicht/deployt wird — Server Script, Client Script, API-Script, Scheduler-Script,
Custom-HTML-Block-`script` oder sonstiger serverseitiger Code — MÜSSEN **beide** Prüfungen bestanden sein:

1. **Frappe-Richtlinien-Prüfung** (safe_exec / RestrictedPython & Frappe-Best-Practices)
   - Kein Tuple-Unpacking (`a, b = f()`, `for a, b in …`, `k, v in .items()`) → braucht
     `_unpack_sequence_`, das in dieser Frappe-Version nicht bereitsteht → stattdessen Index-Zugriff
     (`x = f(); a = x[0]; b = x[1]`). **Runtime-Fehler** (`NameError: _unpack_sequence_`).
   - **Keine führenden Unterstriche in Variablennamen** (`_x`, `_tmp` …). RestrictedPython verbietet
     das → **Compile-Fehler** (`SyntaxError: "_x" is an invalid variable name because it starts with "_"`).
     Temp-Namen ohne führenden Unterstrich wählen (`xr`, `tmp`, `res`). Mid-/Trailing-Unterstrich ist ok.
   - Keine `import`-Statements; nur erlaubte Builtins/Whitelisted-Funktionen.
   - Kein String-interpoliertes SQL; parametrisiert arbeiten.
   - Prüfung gegen die `frappe-*`-Skills, insbesondere `frappe-errors-serverscripts`,
     `frappe-syntax-serverscripts`, `frappe-agent-validator`.
   - **Test gegen die ECHTE Sandbox, nicht gegen `run_python_code`** (dessen Sandbox erzwingt diese
     Regeln NICHT und liefert falsche „grün"-Ergebnisse). Verbindlich vor Deploy:
     `se = frappe.utils.safe_exec`;
     `se.compile_restricted(script, filename=name, policy=se.FrappeTransformer)` (fängt Syntax/Unterstrich)
     **und** `se.safe_exec(script)` mit gesetztem `frappe.form_dict` gegen einen echten Datensatz
     (fängt Runtime-Fehler wie `_unpack_sequence_`). Alternativ direkt den API-Endpunkt aufrufen.

2. **Thermonuclear-Test** (erschöpfender, adversarialer Testlauf gegen echte Daten & Edge-Cases)
   - Kanten testen: leerer/kein Lauf, Teilzeitraum (Ein-/Auszug), fehlende Ablesungen/Schätzung,
     optiert vs. nicht optiert, Leerstand-Umlage, Wohnanlage (mehrere Häuser), 0-Beträge.
   - Ergebnis im Server-Script-Dokument dokumentieren:
     `custom_thermonuclear_tested_on` (Datum) und `custom_thermonuclear_test_result`.
   - Erst nach grünem Test veröffentlichen.

**Reihenfolge ist verbindlich: TEST VOR DEM SCHREIBEN.** Beide Prüfungen (1 UND 2) laufen gegen den
**Kandidaten** (die neue Fassung), BEVOR die produktive Fassung überschrieben wird. Niemals
„deploy-then-test". Mechanik unter den Sandbox-Einschränkungen (kein Datei-/Netzzugriff in
`run_python_code`):
- Kandidaten in einem **deaktivierten Staging-Server-Script** ablegen (z. B. `*_staging`,
  `disabled=1`, unwirksame `api_method`) und dort via `frappe.utils.safe_exec` compile+exec testen —
  die produktive Fassung bleibt unangetastet. Erst bei grün die produktive überschreiben, dann
  Staging löschen. (Alternativ Kandidat als String in die Sandbox testen.)
- Ausnahme nur bei **akutem Produktionsausfall**: „restore first" ist erlaubt, aber der
  Sandbox-Test (compile+exec) bleibt Pflicht und wird unmittelbar nach dem Notfall-Deploy nachgezogen.

**Erst wenn 1 UND 2 grün sind → deployen.** Gilt zusätzlich zum Skill `axessio-dev-process`
(Risikoklassen, Autonomiestufen, Definition of Done, Run-Log-Pflicht), nicht statt ihm.

## Produktions-Deploy — Freigabe-Grenze

- **Verifizierte Compute-/Korrektheits-Fixes** an Rechen-Skripten (z. B. `bka_live_compute`) dürfen nach
  grünem Test-first + Thermonuclear **autonom** deployt werden.
- **Nach außen wirkende Änderungen** — Versand, echter Mailversand, alles, was Daten an Mieter/Dritte
  schickt oder schwer reversibel ist (z. B. `bka_versand`, tatsächliche E-Rechnungen) — brauchen **immer
  eine ausdrückliche Freigabe** des Users vor dem Produktions-Deploy. Der validierte Kandidat wird zur
  Freigabe vorgelegt (Staging-Test + Vorschau), nicht einfach live geschaltet.
