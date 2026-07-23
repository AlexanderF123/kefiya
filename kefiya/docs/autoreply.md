# AutoReply — automatic incoming-mail acknowledgment (FEAT-11901)

Every incoming tenant/prospect email gets exactly **one** acknowledgment per
sender and case: *"Wir haben Ihre Nachricht erhalten, Ihr Vorgang lautet #…,
wir melden uns bis …"*.

Modelled after the FlowFact MailManager AutoReply ("hinterlegte Nachricht wird
je Absender einmalig automatisch versendet"), extended with case numbers,
autonomy levels and guardrails per the axessio development process.

## Components

| Piece | Where | Purpose |
|---|---|---|
| `Kefiya AutoReply Rule` | DocType | One rule per mailbox (Email Account), optionally per Vorgangstyp. Holds autonomy level, Mustertext, guardrails, kill switch. |
| `Kefiya AutoReply Log` | DocType | Zustandsmerker (duplicate guard) + local run log. One row per decision. |
| `kefiya/utils/autoreply.py` | handler | Hooked on `Communication.after_insert`. Never raises — a failure must not break inbox pulling. |

## Decision flow

1. Only `Received` email Communications with an Email Account and sender.
2. Sender guards: `no-reply`, `mailer-daemon`, `postmaster`, `bounce`,
   `notifications@` etc. and the mailbox's own address are never acknowledged
   (loop protection).
3. Rule matching: exact Vorgangstyp match beats the catch-all rule.
4. Kill switch (local rule field, plus best-effort check of a site-wide
   `Automation Rule` record with key `kefiya_autoreply_incoming`, if that
   DocType exists on the site).
5. Duplicate guard: with a linked Vorgang — one acknowledgment per
   sender+case, ever. Without one — one per sender within `cooldown_days`
   (0 = once per sender, ever; FlowFact behaviour).
6. Daily limit per rule (anomaly guardrail, default 200).
7. Compose from the linked Email Template (placeholders
   `{{ vorgangsnummer }}`, `{{ frist }}`, `{{ sender_name }}`,
   `{{ original_subject }}`) or the built-in German default text.

## Autonomy levels (axessio process §2)

| Level | Behaviour |
|---|---|
| 0 — Shadow Mode (default) | Logs `Would Send` with the rendered text. Nothing leaves the system. |
| 1 — Vorschlagen | Creates a draft reply Communication; a human sends it. |
| 2/3 — Versand | Creates the reply Communication and queues it via the Email Queue, threaded onto the incoming mail with `In-Reply-To` (message id). |

Every decision is written to `Kefiya AutoReply Log` and mirrored best-effort
into the site-wide `Automation Run Log` (fields are mapped defensively — only
fields that exist there are set).

## Rollout (risk class C — Versand an Mieter)

Deploying the code is safe: without an **enabled** rule nothing happens, and a
new rule starts in Shadow Mode.

1. Create a rule for one mailbox, leave it at `0 - Shadow Mode`, enable it.
2. Watch `Kefiya AutoReply Log` for ≥ a few days: senders correct? duplicates
   correctly skipped? rendered text sensible?
3. Move to `1 - Vorschlagen`, have the team send a handful of drafts.
4. Only after documented sign-off (GF/Owner, deploy day rules): level 2.
   Level escalation per rule, one step at a time, per process §2.

Emergency stop: set **Kill-Switch** on the rule (acts immediately, no deploy).
