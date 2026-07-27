# Projekt-Memory / Arbeitsregeln

## axessio ERPNext — Skripte NIE ohne Prüfung veröffentlichen

**Verbindliche Regel:** Bevor ein Skript in der axessio-ERPNext-Instanz (axessio.de, Frappe Cloud v15)
veröffentlicht/deployt wird — Server Script, Client Script, API-Script, Scheduler-Script,
Custom-HTML-Block-`script` oder sonstiger serverseitiger Code — MÜSSEN **beide** Prüfungen bestanden sein:

1. **Frappe-Richtlinien-Prüfung** (safe_exec / RestrictedPython & Frappe-Best-Practices)
   - Kein Tuple-Unpacking (`a, b = f()`, `for a, b in …`, `k, v in .items()`) → braucht
     `_unpack_sequence_`, das in dieser Frappe-Version nicht bereitsteht → stattdessen Index-Zugriff
     (`_x = f(); a = _x[0]; b = _x[1]`).
   - Keine `import`-Statements; nur erlaubte Builtins/Whitelisted-Funktionen.
   - Kein String-interpoliertes SQL; parametrisiert arbeiten.
   - Prüfung gegen die `frappe-*`-Skills, insbesondere `frappe-errors-serverscripts`,
     `frappe-syntax-serverscripts`, `frappe-agent-validator`.

2. **Thermonuclear-Test** (erschöpfender, adversarialer Testlauf gegen echte Daten & Edge-Cases)
   - Kanten testen: leerer/kein Lauf, Teilzeitraum (Ein-/Auszug), fehlende Ablesungen/Schätzung,
     optiert vs. nicht optiert, Leerstand-Umlage, Wohnanlage (mehrere Häuser), 0-Beträge.
   - Ergebnis im Server-Script-Dokument dokumentieren:
     `custom_thermonuclear_tested_on` (Datum) und `custom_thermonuclear_test_result`.
   - Erst nach grünem Test veröffentlichen.

**Erst wenn 1 UND 2 grün sind → deployen.** Gilt zusätzlich zum Skill `axessio-dev-process`
(Risikoklassen, Autonomiestufen, Definition of Done, Run-Log-Pflicht), nicht statt ihm.
