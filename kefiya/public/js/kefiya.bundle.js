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

import "./controllers/bank_refresh";
// Opened from the outgoing-payments page, and from anywhere else that wants
// to show one transfer without navigating away from what the reader is doing.
import "./controllers/transfer_details";
