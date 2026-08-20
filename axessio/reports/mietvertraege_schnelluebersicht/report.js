// Filter und Darstellung der Schnelluebersicht. Liegt in der Datenbank am Report
// (Feld `javascript`); die versionierte Fassung liegt im Repository kefiya.
//
// Ueber die Filter hinaus baut diese Datei drei Dinge:
//   * die Kennzahlen sind Einstiege -- ein Klick filtert die Liste auf das,
//     was die Zahl zaehlt, und klappt den Baum auf die passende Tiefe auf,
//   * Kennzahlenband und Diagramm lassen sich ein- und ausklappen,
//   * das Diagramm zeichnet die Ansicht selbst, damit die Achse zwischen
//     linear und logarithmisch umschaltbar ist (frappe-charts kennt keine
//     logarithmische Achse -- gezeichnet werden die Zehnerlogarithmen, die
//     Sprechblase nennt den echten Betrag).
//
// Alles, was der Anwender einstellt -- Filter, Klappzustand, Achse, Baumtiefe --
// haengt an seinem Benutzerkonto (frappe.model.utils.user_settings), mit dem
// Browserspeicher als Rueckfallebene, falls der Server gerade nicht antwortet.

frappe.provide("axessio.msu");

(function () {
	const BERICHT = "Mietverträge Schnellübersicht";
	const ABLAGE_DOCTYPE = "Lease";
	const ABLAGE_SCHLUESSEL = "mietvertraege_schnelluebersicht";
	const VORGABE = { kennzahlen_offen: 1, diagramm_offen: 1, skala: "log", tiefe: 1, filter: {} };

	// Jede Kennzahl fuehrt dorthin, wo die Zahl herkommt.
	const EINSTIEGE = {
		"Einheiten": { belegung: "Alle", tiefe: 1, hinweis: "Alle Einheiten zeigen" },
		"Vermietet": { belegung: "Nur vermietet", tiefe: 1, hinweis: "Nur vermietete Einheiten zeigen" },
		"Leerstand": { belegung: "Nur Leerstand", tiefe: 1, hinweis: "Nur leerstehende Einheiten zeigen" },
		"Soll / Monat": { belegung: "Nur vermietet", tiefe: 2, hinweis: "Vermietete Einheiten mit ihren Verträgen" },
		"Kaution gesamt": { belegung: "Nur vermietet", tiefe: 2, hinweis: "Vermietete Einheiten mit ihren Verträgen" },
	};

	const msu = axessio.msu;
	msu.bericht = BERICHT;
	msu.einstellungen = Object.assign({}, VORGABE);
	msu.bereit = false;

	// ---------------------------------------------------------- Einstellungen

	msu.lokal_schluessel = function () {
		const nutzer = (frappe.session && frappe.session.user) || "anon";
		return ABLAGE_SCHLUESSEL + "::" + nutzer;
	};

	msu.lokal_lesen = function () {
		try {
			return JSON.parse(window.localStorage.getItem(msu.lokal_schluessel()) || "{}");
		} catch (e) {
			return {};
		}
	};

	msu.lokal_schreiben = function (stand) {
		try {
			window.localStorage.setItem(msu.lokal_schluessel(), JSON.stringify(stand));
		} catch (e) {
			// Privater Modus oder volles Kontingent: der Server bleibt die Wahrheit.
		}
	};

	msu.laden = function () {
		msu.einstellungen = Object.assign({}, VORGABE, msu.lokal_lesen());
		return frappe
			.xcall("frappe.model.utils.user_settings.get", { doctype: ABLAGE_DOCTYPE })
			.then(function (antwort) {
				let alle = antwort;
				if (typeof alle === "string") {
					try {
						alle = JSON.parse(alle);
					} catch (e) {
						alle = {};
					}
				}
				const gespeichert = (alle || {})[ABLAGE_SCHLUESSEL];
				if (gespeichert) {
					msu.einstellungen = Object.assign({}, VORGABE, gespeichert);
				}
				return msu.einstellungen;
			})
			.catch(function () {
				return msu.einstellungen;
			});
	};

	msu.sichern = function () {
		msu.lokal_schreiben(msu.einstellungen);
		const nutzlast = {};
		nutzlast[ABLAGE_SCHLUESSEL] = msu.einstellungen;
		try {
			frappe
				.xcall("frappe.model.utils.user_settings.save", {
					doctype: ABLAGE_DOCTYPE,
					user_settings: JSON.stringify(nutzlast),
				})
				.catch(function () {});
		} catch (e) {
			// Der Browserspeicher hat den Stand bereits.
		}
	};

	msu.filter_merken = function () {
		const report = frappe.query_report;
		if (!report || !report.get_filter_values) return;
		let werte = {};
		try {
			werte = report.get_filter_values(false) || {};
		} catch (e) {
			return;
		}
		const vorher = JSON.stringify(msu.einstellungen.filter || {});
		msu.einstellungen.filter = werte;
		if (JSON.stringify(werte) !== vorher) {
			msu.sichern();
		}
	};

	// ----------------------------------------------------------------- Baum

	msu.tiefe_anwenden = function (tiefe) {
		const datatable = frappe.query_report && frappe.query_report.datatable;
		if (!datatable || !datatable.rowmanager) return;
		const zeilen = (frappe.query_report && frappe.query_report.data) || [];
		try {
			if (typeof datatable.rowmanager.collapseAllNodes === "function") {
				datatable.rowmanager.collapseAllNodes();
			}
			if (tiefe > 0 && typeof datatable.rowmanager.openSingleNode === "function") {
				zeilen.forEach(function (zeile, i) {
					if ((zeile.indent || 0) < tiefe) {
						datatable.rowmanager.openSingleNode(i);
					}
				});
			}
		} catch (e) {
			// Andere Datatable-Fassung: die Tiefe bleibt, wie sie gerendert wurde.
		}
	};

	// ------------------------------------------------------------- Diagramm

	msu.euro = function (betrag) {
		try {
			return format_currency(betrag, "EUR");
		} catch (e) {
			return (Number(betrag) || 0).toFixed(2) + " €";
		}
	};

	msu.objektwerte = function () {
		const zeilen = (frappe.query_report && frappe.query_report.data) || [];
		const labels = [];
		const werte = [];
		zeilen.forEach(function (zeile) {
			if ((zeile.indent || 0) !== 0 || zeile.rolle !== "Objekt") return;
			labels.push(String(zeile.bezeichnung || "").split(" · ")[0]);
			werte.push(Number(zeile.soll) || 0);
		});
		return { labels: labels, werte: werte };
	};

	msu.diagramm_zeichnen = function ($flaeche) {
		const daten = msu.objektwerte();
		$flaeche.empty();
		if (!daten.labels.length) {
			$flaeche.append($("<div class='text-muted'></div>").text(__("Keine Objekte in der Auswahl.")));
			return;
		}
		const logarithmisch = msu.einstellungen.skala === "log";
		const gezeichnet = daten.werte.map(function (wert) {
			if (!logarithmisch) return wert;
			return wert > 0 ? Math.log10(wert) : 0;
		});
		try {
			new frappe.Chart($flaeche.get(0), {
				data: {
					labels: daten.labels,
					datasets: [{ name: logarithmisch ? "Soll / Monat (log₁₀)" : "Soll / Monat", values: gezeichnet }],
				},
				type: "bar",
				height: 260,
				colors: ["#14532d"],
				axisOptions: { xAxisMode: "tick", yAxisMode: "span" },
				tooltipOptions: {
					formatTooltipY: function (wert) {
						if (!logarithmisch) return msu.euro(wert);
						if (!wert) return msu.euro(0);
						return msu.euro(Math.pow(10, wert));
					},
				},
			});
		} catch (e) {
			$flaeche.append($("<div class='text-muted'></div>").text(__("Diagramm nicht verfügbar.")));
		}
	};

	// ------------------------------------------------------------ Oberflaeche

	msu.stil_setzen = function () {
		if (document.getElementById("msu-stil")) return;
		const stil = document.createElement("style");
		stil.id = "msu-stil";
		stil.textContent = [
			".msu-leiste { display: flex; align-items: center; gap: 8px; margin: 10px 0 4px 0; flex-wrap: wrap; }",
			".msu-leiste .msu-hinweis { margin-left: auto; font-size: var(--text-sm); }",
			".msu-rahmen { border: 1px solid var(--border-color); border-radius: var(--border-radius-md);",
			"  padding: 8px 12px; margin-bottom: 10px; background: var(--card-bg); }",
			".msu-klickbar { cursor: pointer; border-radius: var(--border-radius-md); }",
			".msu-klickbar:hover { background: var(--bg-light-gray, var(--subtle-fg)); }",
			".msu-fussnote { margin: 12px 0 4px 0; font-size: var(--text-sm); }",
		].join("\n");
		document.head.appendChild(stil);
	};

	msu.schalter_beschriften = function ($leiste) {
		const e = msu.einstellungen;
		$leiste.find("[data-ziel='kennzahlen']").text((e.kennzahlen_offen ? "▾ " : "▸ ") + __("Kennzahlen"));
		$leiste.find("[data-ziel='diagramm']").text((e.diagramm_offen ? "▾ " : "▸ ") + __("Soll je Objekt"));
		$leiste
			.find(".msu-skala")
			.text(e.skala === "log" ? __("Achse: logarithmisch") : __("Achse: linear"))
			.toggle(!!e.diagramm_offen);
		$leiste
			.find(".msu-hinweis")
			.text(e.diagramm_offen && e.skala === "log" ? __("Balken in Zehnerpotenzen; die Sprechblase nennt den Betrag.") : "");
	};

	msu.einstieg = function (ziel) {
		const report = frappe.query_report;
		if (!report) return;
		msu.einstellungen.tiefe = ziel.tiefe;
		msu.sichern();
		const einstellungen = frappe.query_reports[BERICHT];
		if (einstellungen) einstellungen.initial_depth = ziel.tiefe;

		let vorher = null;
		try {
			vorher = report.get_filter_value("belegung");
		} catch (e) {
			vorher = null;
		}
		if (vorher === ziel.belegung) {
			msu.tiefe_anwenden(ziel.tiefe);
		} else {
			report.set_filter_value("belegung", ziel.belegung);
		}
	};

	msu.fussnote_setzen = function ($haupt) {
		$haupt.find(".msu-fussnote").remove();
		const zeilen = (frappe.query_report && frappe.query_report.data) || [];
		const text = zeilen.length ? zeilen[0].fussnote : null;
		if (!text) return;
		$haupt.append($("<div class='msu-fussnote text-muted'></div>").text(text));
	};

	msu.oberflaeche_aufbauen = function () {
		const report = frappe.query_report;
		if (!report || !report.page) return;
		msu.stil_setzen();

		const $haupt = $(report.page.main);
		const $kennzahlen = $haupt.find(".report-summary").first();
		$haupt.find(".chart-container").hide(); // gezeichnet wird im eigenen Rahmen

		$haupt.find(".msu-leiste, .msu-rahmen").remove();

		const $leiste = $(
			"<div class='msu-leiste'>" +
				"<button class='btn btn-xs btn-default msu-schalter' data-ziel='kennzahlen'></button>" +
				"<button class='btn btn-xs btn-default msu-schalter' data-ziel='diagramm'></button>" +
				"<button class='btn btn-xs btn-default msu-skala'></button>" +
				"<span class='msu-hinweis text-muted'></span>" +
			"</div>"
		);
		const $rahmen = $("<div class='msu-rahmen'><div class='msu-flaeche'></div></div>");

		if ($kennzahlen.length) {
			$leiste.insertBefore($kennzahlen);
			$rahmen.insertAfter($kennzahlen);
		} else {
			$haupt.prepend($rahmen);
			$haupt.prepend($leiste);
		}

		$leiste.find(".msu-schalter").on("click", function () {
			const ziel = $(this).attr("data-ziel");
			if (ziel === "kennzahlen") {
				msu.einstellungen.kennzahlen_offen = msu.einstellungen.kennzahlen_offen ? 0 : 1;
				$kennzahlen.toggle(!!msu.einstellungen.kennzahlen_offen);
			} else {
				msu.einstellungen.diagramm_offen = msu.einstellungen.diagramm_offen ? 0 : 1;
				$rahmen.toggle(!!msu.einstellungen.diagramm_offen);
				if (msu.einstellungen.diagramm_offen) {
					msu.diagramm_zeichnen($rahmen.find(".msu-flaeche"));
				}
			}
			msu.schalter_beschriften($leiste);
			msu.sichern();
		});

		$leiste.find(".msu-skala").on("click", function () {
			msu.einstellungen.skala = msu.einstellungen.skala === "log" ? "linear" : "log";
			msu.schalter_beschriften($leiste);
			msu.sichern();
			msu.diagramm_zeichnen($rahmen.find(".msu-flaeche"));
		});

		// Kennzahlen zu Einstiegen machen.
		$kennzahlen.find(".summary-item").each(function () {
			const $kachel = $(this);
			const text = ($kachel.find(".summary-label").text() || $kachel.text() || "").trim();
			let treffer = null;
			Object.keys(EINSTIEGE).forEach(function (label) {
				if (!treffer && text.indexOf(label) === 0) treffer = label;
			});
			if (!treffer) return;
			const ziel = EINSTIEGE[treffer];
			$kachel
				.addClass("msu-klickbar")
				.attr("title", ziel.hinweis)
				.off("click.msu")
				.on("click.msu", function () {
					msu.einstieg(ziel);
				});
		});

		$kennzahlen.toggle(!!msu.einstellungen.kennzahlen_offen);
		$rahmen.toggle(!!msu.einstellungen.diagramm_offen);
		msu.schalter_beschriften($leiste);
		if (msu.einstellungen.diagramm_offen) {
			msu.diagramm_zeichnen($rahmen.find(".msu-flaeche"));
		}
		msu.fussnote_setzen($haupt);
	};
})();

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
			fieldname: "belegung",
			label: "Belegung",
			fieldtype: "Select",
			options: ["Alle", "Nur vermietet", "Nur Leerstand"],
			default: "Alle",
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
		const msu = axessio.msu;

		// Das Hilfe-Schiebefenster haengt sonst an Client Scripts, die es nur fuer
		// Formular- und Listenansichten gibt. Auf einer Berichtsseite laedt der
		// Bericht es selbst nach; der Einbauer im Fenster setzt dann den Knopf.
		if (!window.axessio_help_drawer && !window.ax_help_loading) {
			window.ax_help_loading = true;
			frappe.call({
				method: "ax_drawer_js",
				callback: function (r) {
					if (r && r.message) {
						try {
							eval(r.message);
						} catch (e) {
							console.error("axessio help drawer load failed", e);
						}
					}
					window.ax_help_loading = false;
				},
			});
		}

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
		report.page.add_menu_item(__("Einstellungen zurücksetzen"), function () {
			msu.einstellungen = { kennzahlen_offen: 1, diagramm_offen: 1, skala: "log", tiefe: 1, filter: {} };
			msu.sichern();
			frappe.show_alert({ message: __("Einstellungen zurückgesetzt."), indicator: "green" });
			frappe.query_report.refresh();
		});

		// Gespeicherte Einstellungen des Benutzers nachziehen.
		msu.laden().then(function (einstellungen) {
			msu.bereit = true;
			frappe.query_reports[msu.bericht].initial_depth = einstellungen.tiefe || 1;
			const gespeichert = einstellungen.filter || {};
			const anzuwenden = {};
			Object.keys(gespeichert).forEach(function (feld) {
				if (report.get_filter(feld) && gespeichert[feld] !== undefined && gespeichert[feld] !== null) {
					anzuwenden[feld] = gespeichert[feld];
				}
			});
			if (Object.keys(anzuwenden).length) {
				report.set_filter_value(anzuwenden);
			} else {
				msu.oberflaeche_aufbauen();
			}
		});
	},

	after_datatable_render: function () {
		const msu = axessio.msu;
		msu.oberflaeche_aufbauen();
		if (msu.bereit) {
			msu.filter_merken();
			msu.tiefe_anwenden(msu.einstellungen.tiefe || 1);
		}
	},
};
