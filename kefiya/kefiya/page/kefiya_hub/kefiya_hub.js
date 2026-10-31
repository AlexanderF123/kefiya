// Copyright (c) 2026, Phamos GmbH and contributors
// For license information, please see license.txt
frappe.provide("kefiya.tools");

frappe.pages["kefiya-hub"].on_page_load = function (wrapper) {
	kefiya.tools.hubObj = new kefiya.tools.KefiyaHub(wrapper);
};

frappe.pages["kefiya-hub"].on_page_show = function () {
	kefiya.tools.hubObj && kefiya.tools.hubObj.refresh();
};

const STEP_INDICATOR = {
	done: { color: "green", label: __("Done") },
	warning: { color: "orange", label: __("Needs attention") },
	error: { color: "red", label: __("Error") },
	todo: { color: "gray", label: __("Not set up") },
};

const LOGIN_INDICATOR = {
	ok: { color: "green", label: __("Up to date") },
	warning: { color: "orange", label: __("Needs attention") },
	error: { color: "red", label: __("Connection failed") },
};

kefiya.tools.KefiyaHub = class KefiyaHub {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Kefiya"),
			single_column: true,
		});
		this.wrapper = $(wrapper);
		this.wrapper.addClass("kefiya-hub-page");
		this.$body = $('<div class="kefiya-hub"></div>').appendTo(this.page.main);
		this.make_filters();
		this.make_actions();
	}

	make_filters() {
		this.company_field = this.page.add_field({
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			change: () => this.refresh(),
		});
	}

	make_actions() {
		this.page.set_primary_action(
			__("Import now"),
			() => this.import_dialog(),
			"download"
		);
		this.page.set_secondary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.page.add_menu_item(__("Kefiya Settings"), () =>
			frappe.set_route("Form", "Kefiya Settings")
		);
		this.page.add_menu_item(__("Kefiya Schedule"), () =>
			frappe.set_route("Form", "Kefiya Schedule")
		);

		frappe.ui.keys.add_shortcut({
			shortcut: "ctrl+i",
			action: () => this.import_dialog(),
			page: this.page,
			description: __("Import bank transactions"),
		});

		this.$body.on("click", "[data-route]", (e) => {
			e.preventDefault();
			frappe.set_route(...$(e.currentTarget).attr("data-route").split("|"));
		});
		this.$body.on("click", "[data-new]", (e) => {
			e.preventDefault();
			frappe.new_doc($(e.currentTarget).attr("data-new"));
		});
		this.$body.on("click", "[data-import]", (e) => {
			e.preventDefault();
			this.import_dialog($(e.currentTarget).attr("data-import"));
		});
		this.$body.on("click", "[data-open-transactions]", (e) => {
			e.preventDefault();
			frappe.set_route("List", "Bank Transaction", {
				bank_account: $(e.currentTarget).attr("data-open-transactions"),
				status: "Unreconciled",
			});
		});
		this.$body.on("click", "[data-step]", (e) => {
			const target = this.$body.find(`#kefiya-step-${$(e.currentTarget).attr("data-step")}`);
			target[0] && target[0].scrollIntoView({ behavior: "smooth", block: "start" });
		});
	}

	refresh() {
		frappe.call({
			method: "kefiya.kefiya.page.kefiya_hub.kefiya_hub.get_overview",
			args: { company: this.company_field.get_value() },
			freeze: !this.data,
			callback: (r) => {
				this.data = r.message;
				this.render();
			},
		});
	}

	import_dialog(kefiya_login) {
		const dialog = new frappe.ui.Dialog({
			title: __("Import bank transactions"),
			fields: [
				{
					fieldname: "kefiya_login",
					label: __("Kefiya Login"),
					fieldtype: "Link",
					options: "Kefiya Login",
					reqd: 1,
					default: kefiya_login,
				},
				{ fieldtype: "Column Break" },
				{
					fieldname: "from_date",
					label: __("From Date"),
					fieldtype: "Date",
					default: frappe.datetime.add_days(frappe.datetime.get_today(), -7),
				},
				{
					fieldname: "to_date",
					label: __("To Date"),
					fieldtype: "Date",
					default: frappe.datetime.get_today(),
				},
			],
			primary_action_label: __("Continue"),
			primary_action: (values) => {
				dialog.hide();
				// The import itself runs in Kefiya Import, which handles TAN challenges
				frappe.new_doc("Kefiya Import", values);
			},
		});
		dialog.show();
	}

	render() {
		const d = this.data;
		this.$body.html(`
			${this.render_kpis(d)}
			${this.render_stepper(d.steps)}
			${this.render_connect(d)}
			${this.render_link(d)}
			${this.render_import(d)}
			${this.render_reconcile(d)}
		`);
	}

	render_kpis(d) {
		const failed = d.logins.filter((l) => l.failed_connection).length;
		const last = d.logins
			.map((l) => l.last_import && l.last_import.creation)
			.filter(Boolean)
			.sort()
			.pop();
		const open_amount = d.bank_accounts.reduce((sum, a) => sum + (a.open.amount || 0), 0);
		const currency = (d.bank_accounts.find((a) => a.open.currency) || {}).open?.currency;
		const unlinked = d.bank_accounts.filter((a) => !a.has_login).length;

		const tile = (label, value, hint, color) => `
			<div class="kefiya-kpi">
				<div class="kefiya-kpi-label">${label}</div>
				<div class="kefiya-kpi-value ${color ? "text-" + color : ""}">${value}</div>
				<div class="kefiya-kpi-hint">${hint}</div>
			</div>`;

		return `<div class="kefiya-kpis">
			${tile(
				__("Bank connections"),
				d.logins.length,
				failed ? __("{0} failing", [failed]) : __("All connected"),
				failed ? "danger" : ""
			)}
			${tile(
				__("Last import"),
				last ? comment_when(last) : __("Never"),
				d.scheduler_active ? __("Scheduler active") : __("Scheduler inactive"),
				d.scheduler_active ? "" : "warning"
			)}
			${tile(
				__("Open transactions"),
				d.steps.open_count,
				format_currency(open_amount, currency),
				d.steps.open_count ? "warning" : ""
			)}
			${tile(
				__("Bank accounts without login"),
				unlinked,
				__("of {0} company accounts", [d.bank_accounts.length]),
				unlinked ? "warning" : ""
			)}
		</div>`;
	}

	render_stepper(steps) {
		const items = [
			["connect", __("Connect bank")],
			["link", __("Link accounts")],
			["import", __("Import")],
			["reconcile", __("Match & reconcile")],
		];
		return `<div class="kefiya-stepper">
			${items
				.map(([key, label], i) => {
					const s = STEP_INDICATOR[steps[key]];
					return `<button class="kefiya-step" data-step="${key}">
						<span class="kefiya-step-number kefiya-step-${steps[key]}">${i + 1}</span>
						<span class="kefiya-step-text">
							<span class="kefiya-step-label">${label}</span>
							<span class="indicator-pill no-indicator-dot ${s.color}">${s.label}</span>
						</span>
					</button>`;
				})
				.join('<span class="kefiya-step-line"></span>')}
		</div>`;
	}

	section(key, number, title, description, actions, body) {
		return `<div class="frappe-card kefiya-section" id="kefiya-step-${key}">
			<div class="kefiya-section-head">
				<div>
					<div class="kefiya-section-title">${number}. ${title}</div>
					<div class="text-muted small">${description}</div>
				</div>
				<div class="kefiya-section-actions">${actions}</div>
			</div>
			${body}
		</div>`;
	}

	button(label, attrs, primary) {
		return `<button class="btn btn-xs ${primary ? "btn-primary" : "btn-default"}" ${attrs}>${label}</button>`;
	}

	empty(text) {
		return `<div class="kefiya-empty text-muted">${text}</div>`;
	}

	render_connect(d) {
		const rows = d.logins
			.map((l) => {
				const s = LOGIN_INDICATOR[l.status];
				const schedule = l.schedule
					? `${__(l.schedule.import_frequency)} ${l.schedule.hour ? l.schedule.hour + ":00" : ""}${
							l.schedule.active ? "" : ` <span class="text-muted">(${__("paused")})</span>`
					  }`
					: `<span class="text-muted">${__("Manual")}</span>`;
				const last = l.last_import
					? frappe.datetime.str_to_user(l.last_import.to_date)
					: `<span class="text-muted">${__("Never")}</span>`;
				return `<tr>
					<td><a href="#" data-route="Form|Kefiya Login|${encodeURIComponent(l.name)}">${frappe.utils.escape_html(l.name)}</a>
						<div class="text-muted small">${frappe.utils.escape_html(l.account_iban || "")}</div></td>
					<td><span class="indicator-pill ${s.color}">${s.label}</span>
						${l.failed_connection ? `<div class="text-muted small">${__("{0} failed attempts", [l.failed_connection])}</div>` : ""}</td>
					<td>${last}</td>
					<td>${schedule}</td>
					<td class="text-right">${this.button(__("Import"), `data-import="${frappe.utils.escape_html(l.name)}"`)}</td>
				</tr>`;
			})
			.join("");
		return this.section(
			"connect",
			1,
			__("Connect bank"),
			__("FinTS logins to your banks. A failed connection usually needs a new TAN or password."),
			this.button(__("New login"), 'data-new="Kefiya Login"'),
			d.logins.length
				? `<table class="table kefiya-table">
					<thead><tr><th>${__("Login")}</th><th>${__("Status")}</th><th>${__("Imported until")}</th><th>${__("Schedule")}</th><th></th></tr></thead>
					<tbody>${rows}</tbody></table>`
				: this.empty(__("No bank connection yet. Create a Kefiya Login to start."))
		);
	}

	render_link(d) {
		const unlinked_logins = d.logins.filter((l) => !l.bank_account);
		const rows = d.bank_accounts
			.map(
				(a) => `<tr>
				<td><a href="#" data-route="Form|Bank Account|${encodeURIComponent(a.name)}">${frappe.utils.escape_html(a.account_name)}</a>
					<div class="text-muted small">${frappe.utils.escape_html(a.bank || "")} · ${frappe.utils.escape_html(a.iban || "")}</div></td>
				<td>${
					a.has_login
						? `<span class="indicator-pill green">${__("Linked")}</span>`
						: `<span class="indicator-pill orange">${__("No Kefiya Login")}</span>`
				}</td>
			</tr>`
			)
			.join("");
		const warnings = unlinked_logins
			.map(
				(l) => `<div class="kefiya-hint">
				${__("Login {0} is not linked to an ERPNext Bank Account, so its transactions cannot be imported.", [
					`<b>${frappe.utils.escape_html(l.name)}</b>`,
				])}
				${this.button(__("Link now"), `data-route="Form|Kefiya Login|${encodeURIComponent(l.name)}"`, true)}
			</div>`
			)
			.join("");
		return this.section(
			"link",
			2,
			__("Link accounts"),
			__("Every company bank account needs a Kefiya Login. Party bank accounts are created with the Bank Account Wizard."),
			this.button(__("Bank Account Wizard"), 'data-route="bank_account_wizard"'),
			warnings +
				(d.bank_accounts.length
					? `<table class="table kefiya-table">
						<thead><tr><th>${__("Company bank account")}</th><th>${__("Kefiya")}</th></tr></thead>
						<tbody>${rows}</tbody></table>`
					: this.empty(__("No company bank account found.")))
		);
	}

	render_import(d) {
		const rows = d.recent_imports
			.map((i) => {
				const route = i.source === "FinTS" ? "Kefiya Import" : "Kefiya Bank Statement Import";
				const detail =
					i.source === "FinTS"
						? `${frappe.utils.escape_html(i.kefiya_login)} · ${frappe.datetime.str_to_user(i.from_date)} – ${frappe.datetime.str_to_user(i.to_date)}`
						: `${frappe.utils.escape_html(i.bank_account || "")} · ${__("{0} of {1} records", [i.imported_records || 0, i.payload_count || 0])}`;
				const status =
					i.source === "FinTS"
						? i.docstatus
							? `<span class="indicator-pill green">${__("Imported")}</span>`
							: `<span class="indicator-pill gray">${__("Draft")}</span>`
						: `<span class="indicator-pill ${{ Success: "green", "Partial Success": "orange", Error: "red" }[i.status] || "gray"}">${__(i.status)}</span>`;
				return `<tr>
					<td><a href="#" data-route="Form|${route}|${encodeURIComponent(i.name)}">${__(i.source === "FinTS" ? "FinTS" : "Bank statement")}</a>
						<div class="text-muted small">${detail}</div></td>
					<td>${status}</td>
					<td class="text-muted">${comment_when(i.creation)}</td>
				</tr>`;
			})
			.join("");
		return this.section(
			"import",
			3,
			__("Import"),
			__("Fetch transactions via FinTS or upload a bank statement file (CSV / MT940)."),
			this.button(__("Upload statement"), 'data-new="Kefiya Bank Statement Import"') +
				this.button(__("Schedule"), 'data-route="Form|Kefiya Schedule"') +
				this.button(__("Import now"), "data-import", true),
			d.recent_imports.length
				? `<table class="table kefiya-table">
					<thead><tr><th>${__("Recent imports")}</th><th>${__("Status")}</th><th></th></tr></thead>
					<tbody>${rows}</tbody></table>`
				: this.empty(__("Nothing imported yet."))
		);
	}

	render_reconcile(d) {
		const accounts = d.bank_accounts.filter((a) => a.open.count);
		const rows = accounts
			.map(
				(a) => `<tr>
				<td><a href="#" data-open-transactions="${frappe.utils.escape_html(a.name)}">${frappe.utils.escape_html(a.account_name)}</a>
					<div class="text-muted small">${__("oldest from {0}", [frappe.datetime.str_to_user(a.open.oldest)])}</div></td>
				<td class="text-right">${a.open.count}</td>
				<td class="text-right">${format_currency(a.open.amount, a.open.currency)}</td>
			</tr>`
			)
			.join("");
		return this.section(
			"reconcile",
			4,
			__("Match & reconcile"),
			__("Assign imported transactions to invoices, payments or expense accounts."),
			this.button(__("Assign Payment Entries"), 'data-route="assign_payment_entries"') +
				this.button(__("Bank Reconciliation Tool"), 'data-route="Form|Bank Reconciliation Tool"') +
				this.button(__("Bank Transaction Wizard"), 'data-route="bank-transaction-wiz"', true),
			accounts.length
				? `<table class="table kefiya-table">
					<thead><tr><th>${__("Bank account")}</th><th class="text-right">${__("Open")}</th><th class="text-right">${__("Unallocated")}</th></tr></thead>
					<tbody>${rows}</tbody></table>`
				: this.empty(__("All transactions are reconciled."))
		);
	}
};
