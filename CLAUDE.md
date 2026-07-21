# Kefiya – Regeln für Claude

## Datenzugriff: Frappe-Berechtigungen sind IMMER zu respektieren

**Rohes `frappe.db.sql` (oder anderes rohes SQL) umgeht das Frappe-Berechtigungssystem
vollständig (Role Permissions, User Permissions, Match-Conditions). Das ist niemals
gestattet — weder in Server Scripts auf der ERPNext-Instanz (Cockpit/Monoblock,
Sent-Mail, Dashboards o. Ä.) noch in Whitelisted-Methoden dieser App.**

Verbindliche Regeln für allen Daten lesenden/schreibenden Code:

1. Lesen: `frappe.get_list` / `frappe.get_all` **ohne** `ignore_permissions=True`,
   `frappe.client.get_list`, Query Reports oder `frappe.qb` **plus** expliziten
   `frappe.has_permission(doctype, throw=True)`-Check. `frappe.get_all` prüft
   selbst keine Berechtigungen auf Feldebene — Feldliste bewusst wählen.
2. Schreiben: über Document-API (`frappe.get_doc(...).save()` / `.insert()` /
   `.submit()`) ohne `ignore_permissions=True`. Ausnahmen (Systemjobs ohne
   Benutzerkontext) müssen einen expliziten, eigenen Berechtigungs-Gate davor
   haben und im Code begründet sein.
3. Jede `@frappe.whitelist()`-Methode braucht in der ersten Zeile einen
   expliziten Permission-Check (`frappe.has_permission` / `frappe.only_for`),
   bevor irgendetwas gelesen oder geschrieben wird.
4. Bestehendes rohes SQL (`kefiya/utils/sql/*.sql`, `assign_payment_controller.py`,
   `bank_account_controller.py`, `client.py`) gilt als Altlast und wird bei
   jeder Änderung an diesen Stellen auf `frappe.qb`/`frappe.get_all` migriert —
   niemals erweitert.
