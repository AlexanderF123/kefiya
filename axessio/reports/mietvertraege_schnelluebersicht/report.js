// Filter und Darstellung der Schnelluebersicht. Liegt in der Datenbank am Report
// (Feld `javascript`); die versionierte Fassung liegt im Repository kefiya.

frappe.query_reports["Mietverträge Schnellübersicht"] = {
	tree: true,
	initial_depth: 1,
	filters: [
		{
			fieldname: "stichtag",
			label: "Stichtag",
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "company",
			label: "Gesellschaft",
			fieldtype: "Link",
			options: "Company",
		},
		{
			fieldname: "haus",
			label: "Objekt / Haus",
			fieldtype: "Link",
			options: "Property",
			get_query: function () {
				return { filters: { is_group: 1 } };
			},
		},
		{
			fieldname: "einheit",
			label: "Einheit",
			fieldtype: "Link",
			options: "Property",
			get_query: function () {
				const haus = frappe.query_report.get_filter_value("haus");
				const filters = { is_group: 0 };
				if (haus) {
					filters.parent_property = haus;
				}
				return { filters: filters };
			},
		},
		{
			fieldname: "mieter",
			label: "Mieter",
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "nutzungsart",
			label: "Nutzungsart",
			fieldtype: "Select",
			options: ["", "WOHNEN", "GEWERBE", "ANLAGE", "WOHNEN_GEWERBE"],
		},
		{
			fieldname: "vertraege",
			label: "Verträge",
			fieldtype: "Select",
			options: ["Mit Vormietern", "Nur aktuelle Verträge", "Nur Vormieter"],
			default: "Mit Vormietern",
		},
		{
			fieldname: "zeitraeume",
			label: "Mietzeiträume",
			fieldtype: "Select",
			options: ["Nur aktueller Zeitraum", "Alle Staffeln", "Ohne Zeitraum-Zeilen"],
			default: "Nur aktueller Zeitraum",
		},
		{
			fieldname: "nur_leerstand",
			label: "Nur Leerstand",
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "bk_jahre",
			label: "BK-Jahre (Spalten)",
			fieldtype: "Int",
			default: 4,
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) {
			return value;
		}
		if (data.rolle === "Objekt") {
			value = "<b>" + value + "</b>";
		} else if (data.rolle === "Leerstand" && column.fieldname === "bezeichnung") {
			value = "<span style='color: var(--red-500)'>" + value + "</span>";
		} else if (data.rolle === "Vormieter") {
			value = "<span style='color: var(--text-muted)'>" + value + "</span>";
		} else if (data.rolle === "Künftig" && column.fieldname === "bezeichnung") {
			value = "<span style='color: var(--blue-500)'>" + value + "</span>";
		} else if (data.rolle === "Zeitraum") {
			value = "<span style='color: var(--text-light)'>" + value + "</span>";
		}
		return value;
	},

	onload: function (report) {
		report.page.add_inner_button(__("Einheit öffnen"), function () {
			const zeile = frappe.query_report.get_checked_items()[0] || frappe.query_report.data[0];
			if (zeile && zeile.einheit) {
				frappe.set_route("Form", "Property", zeile.einheit);
			}
		});
		report.page.add_inner_button(__("Mietvertrag öffnen"), function () {
			const zeile = frappe.query_report.get_checked_items()[0];
			if (zeile && zeile.vertrag) {
				frappe.set_route("Form", "Lease", zeile.vertrag);
			} else {
				frappe.msgprint(__("Bitte zuerst eine Zeile mit Mietvertrag auswählen."));
			}
		});
	},
};
