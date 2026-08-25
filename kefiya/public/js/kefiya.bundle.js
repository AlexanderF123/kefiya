// Copyright (c) 2026, Phamos GmbH and contributors
// For license information, please see license.txt
//
// Everything this app wants loaded on every desk page.
//
// It is a bundle and not a plain file path for one reason: esbuild gives the
// built file a content hash and records it in assets.json, and hooks.py names
// the bundle rather than the built name. Assets under /assets are served with
// a long cache, so a plain path would leave browsers on the version they
// happened to fetch first -- the fix would be deployed and nobody would have
// it until they cleared their cache.
//
// Adding something here means it loads for every user on every page. That is
// a cost; the bar is that it must be needed by more than one page.

// An IBAN in groups of four, wherever one is shown to a person.
import "./controllers/iban_display";
// What the bank allows on an account. Both transfer forms ask it now, so
// it belongs to every page rather than to one doctype.
import "./controllers/account_capabilities";
// What our own payment history says about a recipient. Asked at entry,
// because the person who sends the order is not the one who saw the
// invoice.
import "./controllers/payee_check";
import "./controllers/bank_refresh";
// Opened from the outgoing-payments page, and from anywhere else that wants
// to show one transfer without navigating away from what the reader is doing.
import "./controllers/transfer_details";
// Entering and correcting one transfer, with the execution options the
// document has always carried.
import "./controllers/transfer_form";
// The outgoing-payments list. It used to be a stored script on one site; the
// page there is now a bootstrap that calls kefiya.payment_outbox().
import "./controllers/payment_outbox";
