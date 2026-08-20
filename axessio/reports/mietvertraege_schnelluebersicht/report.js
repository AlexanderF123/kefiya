// Filter und Darstellung der Schnelluebersicht. Liegt in der Datenbank am Report
// (Feld `javascript`); die versionierte Fassung liegt im Repository kefiya.
//
// Ueber die Filter hinaus baut diese Datei vier Dinge:
//   * jede Zeile fuehrt in ihren Beleg -- die erste Spalte ist ein Verweis auf
//     die Einheit bzw. den Mietvertrag und traegt DocType und Name, damit auch
//     das Kontextmenue der Oberflaeche greift,
//   * die Kennzahlen sind Einstiege: ein Klick filtert die Liste auf das, was
//     die Zahl zaehlt, und klappt den Baum auf die passende Tiefe auf,
//   * Kennzahlenband und Diagramm lassen sich ein- und ausklappen,
//   * das Diagramm ist selbst gezeichnet (SVG): die Achse links nennt Betraege,
//     die Balkenhoehe folgt der gewaehlten Skala, und ein Klick auf einen Balken
//     filtert auf dieses Objekt.
//
// Alles, was der Anwender einstellt -- Filter, Klappzustand, Skala, Baumtiefe --
// haengt an seinem Benutzerkonto (frappe.model.utils.user_settings), mit dem
// Browserspeicher als Rueckfallebene, falls der Server gerade nicht antwortet.

frappe.provide("axessio.msu");

(function () {
	const BERICHT = "Mietverträge Schnellübersicht";
	const ABLAGE_DOCTYPE = "Lease";
	const ABLAGE_SCHLUESSEL = "mietvertraege_schnelluebersicht";
	const VORGABE = { kennzahlen_offen: 1, diagramm_offen: 1, skala: "wurzel", tiefe: 1, filter: {} };
	const SVG_NS = "http://www.w3.org/2000/svg";

	// Reihenfolge des Skalen-Schalters. Wurzel ist die Vorgabe: sie laesst kleine
	// Objekte sichtbar, ohne die Groessenverhaeltnisse so einzuebnen wie der
	// Zehnerlogarithmus.
	const SKALEN = ["wurzel", "log", "linear"];
	const SKALA_NAME = { wurzel: "Wurzel", log: "Logarithmisch", linear: "Linear" };
	const SKALA_HINWEIS = {
		wurzel: "Wurzelskala: kleine Objekte bleiben sichtbar, die Achse nennt die Beträge.",
		log: "Logarithmisch: von Marke zu Marke der zehnfache Betrag.",
		linear: "Lineare Achse: kleine Objekte verschwinden fast.",
	};

	// Rollen, deren Zeile zu einem Mietvertrag gehoert; alle uebrigen zur Einheit.
	const VERTRAGSROLLEN = ["Aktuell", "Vormieter", "Künftig", "Zeitraum"];

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
				if (SKALEN.indexOf(msu.einstellungen.skala) < 0) {
					msu.einstellungen.skala = VORGABE.skala;
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

	msu.tiefe_setzen = function (tiefe) {
		msu.einstellungen.tiefe = tiefe;
		msu.sichern();
		if (frappe.query_reports[BERICHT]) {
			frappe.query_reports[BERICHT].initial_depth = tiefe;
		}
	};

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

	// ------------------------------------------------------------ Einzelbeleg

	msu.zielbeleg = function (data) {
		if (!data) return null;
		if (VERTRAGSROLLEN.indexOf(data.rolle) >= 0) {
			return data.vertrag ? { doctype: "Lease", name: data.vertrag } : null;
		}
		return data.einheit ? { doctype: "Property", name: data.einheit } : null;
	};

	msu.beleg_verweis = function (data, inhalt) {
		const ziel = msu.zielbeleg(data);
		if (!ziel) return inhalt;
		const pfad = "/app/" + frappe.router.slug(ziel.doctype) + "/" + encodeURIComponent(ziel.name);
		// DocType und Name an der Zeile: daran erkennt auch das Kontextmenue der
		// Oberflaeche, welcher Beleg gemeint ist.
		return (
			"<a href='" + pfad + "' data-doctype='" + ziel.doctype + "'" +
			" data-name='" + frappe.utils.escape_html(ziel.name) + "'>" + inhalt + "</a>"
		);
	};

	// ------------------------------------------------------------- Diagramm

	msu.euro = function (betrag) {
		try {
			return format_currency(betrag, "EUR");
		} catch (e) {
			return (Number(betrag) || 0).toFixed(2) + " €";
		}
	};

	msu.euro_kurz = function (betrag) {
		const wert = Number(betrag) || 0;
		if (wert >= 1000000) return (wert / 1000000).toFixed(1).replace(".", ",") + " Mio €";
		if (wert >= 1000) return Math.round(wert / 1000) + " T€";
		return Math.round(wert) + " €";
	};

	// Anteil der Balkenhoehe (0..1) und die Umkehrung fuer die Achsenbeschriftung.
	msu.anteil = function (wert, groesster, skala) {
		if (!(groesster > 0)) return 0;
		const w = wert > 0 ? wert : 0;
		if (skala === "linear") return w / groesster;
		if (skala === "log") return Math.log10(1 + w) / Math.log10(1 + groesster);
		return Math.sqrt(w) / Math.sqrt(groesster);
	};

	msu.betrag_bei = function (anteil, groesster, skala) {
		if (!(groesster > 0)) return 0;
		if (skala === "linear") return anteil * groesster;
		if (skala === "log") return Math.pow(10, anteil * Math.log10(1 + groesster)) - 1;
		return anteil * anteil * groesster;
	};

	msu.objektwerte = function () {
		const zeilen = (frappe.query_report && frappe.query_report.data) || [];
		const objekte = [];
		zeilen.forEach(function (zeile) {
			if ((zeile.indent || 0) !== 0 || zeile.rolle !== "Objekt") return;
			objekte.push({
				id: zeile.einheit || "",
				kurz: String(zeile.bezeichnung || "").split(" · ")[0],
				name: String(zeile.bezeichnung || ""),
				wert: Number(zeile.soll) || 0,
			});
		});
		return objekte;
	};

	function svg_knoten(tag, attribute, text) {
		const el = document.createElementNS(SVG_NS, tag);
		Object.keys(attribute || {}).forEach(function (schluessel) {
			el.setAttribute(schluessel, attribute[schluessel]);
		});
		if (text !== undefined && text !== null) {
			el.textContent = text;
		}
		return el;
	}

	msu.diagramm_zeichnen = function ($flaeche) {
		const objekte = msu.objektwerte();
		$flaeche.empty();
		if (!objekte.length) {
			$flaeche.append($("<div class='text-muted'></div>").text(__("Keine Objekte in der Auswahl.")));
			return;
		}

		const BREITE = 1000;
		const HOEHE = 320;
		const LINKS = 96;
		const RECHTS = 16;
		const OBEN = 12;
		const UNTEN = 86;
		const feldbreite = BREITE - LINKS - RECHTS;
		const feldhoehe = HOEHE - OBEN - UNTEN;
		const skala = msu.einstellungen.skala;

		let groesster = 0;
		objekte.forEach(function (o) {
			if (o.wert > groesster) groesster = o.wert;
		});
		if (!(groesster > 0)) groesster = 1;

		const svg = svg_knoten("svg", {
			viewBox: "0 0 " + BREITE + " " + HOEHE,
			class: "msu-svg",
			preserveAspectRatio: "xMidYMid meet",
			role: "img",
			"aria-label": __("Soll je Objekt"),
		});

		// Achse links: fünf Marken, beschriftet mit dem Betrag auf dieser Höhe.
		for (let i = 0; i <= 4; i++) {
			const anteil = i / 4;
			const y = OBEN + feldhoehe * (1 - anteil);
			svg.appendChild(
				svg_knoten("line", { x1: LINKS, y1: y, x2: BREITE - RECHTS, y2: y, class: "msu-gitter" })
			);
			svg.appendChild(
				svg_knoten(
					"text",
					{ x: LINKS - 8, y: y + 4, "text-anchor": "end", class: "msu-achse" },
					msu.euro_kurz(msu.betrag_bei(anteil, groesster, skala))
				)
			);
		}

		const schritt = feldbreite / objekte.length;
		const balken = Math.max(3, Math.min(26, schritt * 0.66));
		let aktives_haus = "";
		try {
			aktives_haus = frappe.query_report.get_filter_value("haus") || "";
		} catch (e) {
			aktives_haus = "";
		}

		objekte.forEach(function (objekt, i) {
			const mitte = LINKS + schritt * (i + 0.5);
			const hoehe = feldhoehe * msu.anteil(objekt.wert, groesster, skala);
			const y = OBEN + feldhoehe - hoehe;
			const gruppe = svg_knoten("g", {
				class:
					"msu-balken" +
					(objekt.id ? " msu-balken-klickbar" : "") +
					(objekt.id && objekt.id === aktives_haus ? " msu-balken-aktiv" : ""),
			});
			gruppe.appendChild(
				svg_knoten("rect", {
					x: mitte - balken / 2,
					y: y,
					width: balken,
					height: Math.max(hoehe, 1),
					rx: 2,
				})
			);
			gruppe.appendChild(svg_knoten("title", {}, objekt.name + ": " + msu.euro(objekt.wert)));
			gruppe.appendChild(
				svg_knoten(
					"text",
					{
						class: "msu-marke",
						transform: "translate(" + mitte + "," + (OBEN + feldhoehe + 12) + ") rotate(-45)",
						"text-anchor": "end",
					},
					objekt.kurz
				)
			);
			if (objekt.id) {
				gruppe.addEventListener("click", function () {
					msu.diagramm_einstieg(objekt.id);
				});
			}
			svg.appendChild(gruppe);
		});

		$flaeche.get(0).appendChild(svg);
	};

	msu.diagramm_einstieg = function (haus) {
		const report = frappe.query_report;
		if (!report) return;
		let vorher = "";
		try {
			vorher = report.get_filter_value("haus") || "";
		} catch (e) {
			vorher = "";
		}
		// Ein zweiter Klick auf dasselbe Objekt hebt die Einschränkung wieder auf.
		const ziel = vorher === haus ? "" : haus;
		msu.tiefe_setzen(ziel ? 2 : 1);
		report.set_filter_value("haus", ziel);
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
			".msu-svg { width: 100%; height: auto; display: block; }",
			".msu-gitter { stroke: var(--border-color); stroke-width: 1; }",
			".msu-achse, .msu-marke { fill: var(--text-muted); font-size: 11px; }",
			".msu-balken rect { fill: #14532d; }",
			".msu-balken-klickbar { cursor: pointer; }",
			".msu-balken-klickbar:hover rect { fill: #1d7a44; }",
			".msu-balken-aktiv rect { fill: #1d7a44; }",
		].join("\n");
		document.head.appendChild(stil);
	};

	msu.schalter_beschriften = function ($leiste) {
		const e = msu.einstellungen;
		$leiste.find("[data-ziel='kennzahlen']").text((e.kennzahlen_offen ? "▾ " : "▸ ") + __("Kennzahlen"));
		$leiste.find("[data-ziel='diagramm']").text((e.diagramm_offen ? "▾ " : "▸ ") + __("Soll je Objekt"));
		$leiste
			.find(".msu-skala")
			.text(__("Skala") + ": " + __(SKALA_NAME[e.skala] || SKALA_NAME.wurzel))
			.toggle(!!e.diagramm_offen);
		$leiste.find(".msu-hinweis").text(e.diagramm_offen ? __(SKALA_HINWEIS[e.skala] || "") : "");
	};

	msu.einstieg = function (ziel) {
		const report = frappe.query_report;
		if (!report) return;
		msu.tiefe_setzen(ziel.tiefe);

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

	msu.alle_zeilen = function () {
		const report = frappe.query_report;
		if (!report) return;
		msu.tiefe_setzen(1);
		report.set_filter_value({
			company: "",
			haus: "",
			einheit: "",
			mieter: "",
			nutzungsart: "",
			belegung: "Alle",
			vertraege: "Mit Vormietern",
			zeitraeume: "Nur aktueller Zeitraum",
		});
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
			const jetzt = SKALEN.indexOf(msu.einstellungen.skala);
			msu.einstellungen.skala = SKALEN[(jetzt + 1) % SKALEN.length];
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
		const msu = axessio.msu;
		value = default_formatter(value, row, column, data);
		if (!data) {
			return value;
		}
		if (column.fieldname === "bezeichnung") {
			value = msu.beleg_verweis(data, value);
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

		report.page.add_inner_button(__("Alle Zeilen"), function () {
			msu.alle_zeilen();
		});
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
			msu.einstellungen = { kennzahlen_offen: 1, diagramm_offen: 1, skala: "wurzel", tiefe: 1, filter: {} };
			msu.sichern();
			frappe.show_alert({ message: __("Einstellungen zurückgesetzt."), indicator: "green" });
			frappe.query_report.refresh();
		});

		// Gespeicherte Einstellungen des Benutzers nachziehen.
		msu.laden().then(function (einstellungen) {
			msu.bereit = true;
			if (frappe.query_reports[msu.bericht]) {
				frappe.query_reports[msu.bericht].initial_depth = einstellungen.tiefe || 1;
			}
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
