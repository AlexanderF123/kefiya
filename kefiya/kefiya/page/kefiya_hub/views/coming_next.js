// Copyright (c) 2026, Phamos GmbH and contributors
// For license information, please see license.txt

// Views that the next children of #41 build into the hub. Until then each one
// says so and opens the existing form or page.
[
	["bank_account_wizard", __("Bank Account Wizard"), 56, ["bank_account_wizard"]],
	["schedule", __("Schedule"), 55, ["Form", "Kefiya Schedule"]],
	["bank_transaction_wizard", __("Bank Transaction Wizard"), 58, ["bank-transaction-wiz"]],
	["assign_payments", __("Assign Payment Entries"), 57, ["assign_payment_entries"]],
	["settings", __("Settings"), 55, ["Form", "Kefiya Settings"]],
].forEach(([key, label, issue, route]) => {
	kefiya.hub.register_view({
		key,
		label,
		render($container) {
			$container.html(`<div class="frappe-card kefiya-section kefiya-empty">
				<p class="text-muted">${__("This view moves into the Kefiya page with phamos/kefiya#{0}.", [issue])}</p>
				<button class="btn btn-default btn-sm" data-route="${route.join("|")}">${__("Open {0}", [label])}</button>
			</div>`);
		},
	});
});
