# Server Script (Typ: API) — api_method: upsert_ax_dokument
# Endpoint: /api/method/upsert_ax_dokument
#
# Ingestion-Endpoint für den Dokumenten-Index (Aufrufer: n8n-Workflows
# "Dokumenten-Inventar" und "Dokumenten-Anreicherung").
# Muster: frappe-util-api-script — ?dry=1 (Plan ohne Schreiben), ?limit=N.
#
# ACHTUNG Server-Script-Sandbox: keine import-Statements; json/frappe sind
# vorgeladen. Die Feldnamen des Run-Log-Blocks unten beim Deploy gegen den
# DocType "Automation Run Log" abgleichen (Wrapper-Muster, Handoff H1).

RULE_NAME = "Dokumenten-Index Sync"

# Whitelist der Felder, die der Aufrufer setzen darf (n8n schreibt nie direkt)
INVENTORY_FIELDS = [
    "source", "file_name", "file_type", "file_size", "web_url",
    "folder_path", "modified_on_source", "etag", "unit_code",
]
ENRICH_FIELDS = [
    "summary", "full_text", "document_category", "language",
    "processing_status", "error_message",
]

payload = frappe.form_dict
dry = frappe.utils.cint(payload.get("dry"))
limit = frappe.utils.cint(payload.get("limit")) or 0
action = payload.get("action") or "inventory"   # inventory | enrich

# --- Kill-Switch / Autonomiestufe prüfen (Pflicht vor jedem Lauf) ------------
rule = frappe.db.get_value(
    "Automation Rule", {"rule_name": RULE_NAME},
    ["name", "kill_switch"], as_dict=True,
)
if not rule:
    frappe.response["message"] = {"status": "blocked", "reason": "Automation Rule '%s' fehlt" % RULE_NAME}
elif frappe.utils.cint(rule.kill_switch):
    frappe.response["message"] = {"status": "blocked", "reason": "Kill-Switch aktiv"}
else:
    docs = payload.get("docs") or []
    if isinstance(docs, str):
        docs = json.loads(docs)
    if limit:
        docs = docs[:limit]

    created, updated, skipped, errors = [], [], [], []

    for d in docs:
        try:
            drive_id = (d.get("drive_id") or "").strip()
            item_id = (d.get("item_id") or "").strip()
            if not drive_id or not item_id:
                skipped.append({"file_name": d.get("file_name"), "reason": "drive_id/item_id fehlt"})
                continue

            existing = frappe.db.get_value(
                "AX Dokument", {"drive_id": drive_id, "item_id": item_id},
                ["name", "etag"], as_dict=True,
            )

            allowed = ENRICH_FIELDS if action == "enrich" else INVENTORY_FIELDS
            values = {k: d.get(k) for k in allowed if d.get(k) is not None}

            if action == "inventory":
                # Unverändertes ETag → nichts zu tun (Delta-Sync-Idempotenz)
                if existing and d.get("etag") and existing.etag == d.get("etag"):
                    skipped.append({"name": existing.name, "reason": "etag unverändert"})
                    continue
                values["last_synced"] = frappe.utils.now()

            if action == "enrich" and not existing:
                skipped.append({"item_id": item_id, "reason": "Datensatz nicht gefunden"})
                continue

            if dry:
                (updated if existing else created).append({
                    "plan": "update" if existing else "insert",
                    "name": existing.name if existing else None,
                    "file_name": d.get("file_name"),
                    "values": values,
                })
                continue

            if existing:
                doc = frappe.get_doc("AX Dokument", existing.name)
                doc.update(values)
                doc.save(ignore_permissions=True)
                updated.append(existing.name)
            else:
                doc = frappe.get_doc(dict(
                    doctype="AX Dokument",
                    drive_id=drive_id,
                    item_id=item_id,
                    source=d.get("source") or "SharePoint",
                    processing_status="Neu",
                    **values,
                ))
                doc.insert(ignore_permissions=True)
                created.append(doc.name)
        except Exception as e:
            errors.append({"item_id": d.get("item_id"), "error": str(e)[:300]})

    result = {
        "status": "dry-run" if dry else "ok",
        "action": action,
        "received": len(docs),
        "created": len(created), "updated": len(updated),
        "skipped": len(skipped), "errors": len(errors),
        "details": {"created": created[:20], "updated": updated[:20],
                    "skipped": skipped[:20], "errors": errors[:20]},
    }

    # --- Run-Log (Pflicht; Feldnamen beim Deploy abgleichen) -----------------
    if not dry:
        try:
            frappe.get_doc({
                "doctype": "Automation Run Log",
                "automation_rule": rule.name,
                "trigger": "API %s (n8n)" % action,
                "action": "upsert_ax_dokument",
                "result": json.dumps({k: result[k] for k in ("received", "created", "updated", "skipped", "errors")}),
                "status": "Fehler" if errors else "Erfolg",
            }).insert(ignore_permissions=True)
            frappe.db.set_value("Automation Rule", rule.name, "last_run", frappe.utils.now())
            if errors:
                frappe.get_doc({
                    "doctype": "Automation Exception",
                    "automation_rule": rule.name,
                    "severity": "3",
                    "details": json.dumps(errors[:20]),
                }).insert(ignore_permissions=True)
        except Exception as log_err:
            result["log_warning"] = str(log_err)[:200]

    frappe.response["message"] = result
