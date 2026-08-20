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
//     die Balkenhoehe folgt der gewaehlten Skala, ein Klick auf einen Balken
//     filtert auf dieses Objekt, und die Hoehe ist mit der Maus veraenderbar.
//
// Alles, was der Anwender einstellt -- Filter, Klappzustand, Skala, Baumtiefe --
// haengt an seinem Benutzerkonto (frappe.model.utils.user_settings), mit dem
// Browserspeicher als Rueckfallebene, falls der Server gerade nicht antwortet.

frappe.provide("axessio.msu");

(function () {
	const BERICHT = "Mietverträge Schnellübersicht";
	const ABLAGE_DOCTYPE = "Lease";
	const ABLAGE_SCHLUESSEL = "mietvertraege_schnelluebersicht";
	const VORGABE = {
		kennzahlen_offen: 1,
		diagramm_offen: 1,
		skala: "wurzel",
		tiefe: 1,
		diagramm_hoehe: 320,
		filter: {},
	};
	const HOEHE_MIN = 160;
	const HOEHE_MAX = 900;
	const SVG_NS = "http://www.w3.org/2000/svg";

	// Skalen des Diagramms. `hin` bildet einen Betrag auf die Zeichenhoehe ab,
	// `zurueck` fuehrt eine Achsenmarke wieder in einen Betrag zurueck -- mehr
	// braucht es nicht: Balkenhoehe und Achsenbeschriftung fallen beide daraus ab.
	// Wurzel ist die Vorgabe, weil sie kleine Objekte sichtbar laesst, ohne die
	// Groessenverhaeltnisse so einzuebnen wie der Zehnerlogarithmus.
	const SKALEN = ["wurzel", "log", "linear"];
	const SKALA = {
		wurzel: {
			name: "Wurzel",
			hinweis: "Wurzelskala: kleine Objekte bleiben sichtbar, die Achse nennt die Beträge.",
			hin: function (betrag) {
				return Math.sqrt(betrag);
			},
			zurueck: function (hoehe) {
				return hoehe * hoehe;
			},
		},
		log: {
			name: "Logarithmisch",
			hinweis: "Logarithmisch: von Marke zu Marke der zehnfache Betrag.",
			hin: function (betrag) {
				return Math.log10(1 + betrag);
			},
			zurueck: function (hoehe) {
				return Math.pow(10, hoehe) - 1;
			},
		},
		linear: {
			name: "Linear",
			hinweis: "Lineare Achse: kleine Objekte verschwinden fast.",
			hin: function (betrag) {
				return betrag;
			},
			zurueck: function (hoehe) {
				return hoehe;
			},
		},
	};

	// Rollen, deren Zeile zu einem Mietvertrag gehoert; alle uebrigen zur Einheit.
	const VERTRAGSROLLEN = ["Aktuell", "Vormieter", "Künftig", "Zeitraum"];

	// Farbe der Zeile nach ihrer Rolle. Objektzeilen stehen fett statt farbig.
	const ROLLENFARBE = {
		Leerstand: "var(--red-500)",
		Vormieter: "var(--text-muted)",
		Künftig: "var(--blue-500)",
		Zeitraum: "var(--text-light)",
	};

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
	msu.vorgabe = function () {
		return Object.assign({}, VORGABE);
	};
	msu.einstellungen = msu.vorgabe();
	msu.bereit = false;
	msu.einmal_aufklappen = 0;

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
		msu.einstellungen = Object.assign(msu.vorgabe(), msu.lokal_lesen());
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
					msu.einstellungen = Object.assign(msu.vorgabe(), gespeichert);
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
		msu.tiefe_uebernehmen();
	};

	msu.baum_aufklappen = function (tiefe) {
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

	msu.einfaerben = function (data, inhalt) {
		if (data.rolle === "Objekt") return "<b>" + inhalt + "</b>";
		const farbe = ROLLENFARBE[data.rolle];
		return farbe ? "<span style='color: " + farbe + "'>" + inhalt + "</span>" : inhalt;
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

	msu.skala = function () {
		return SKALA[msu.einstellungen.skala] || SKALA.wurzel;
	};

	msu.hoehe = function () {
		const wert = Number(msu.einstellungen.diagramm_hoehe) || VORGABE.diagramm_hoehe;
		return Math.min(Math.max(Math.round(wert), HOEHE_MIN), HOEHE_MAX);
	};

	// Die Zeichenflaeche traegt `resize: vertical`; der Beobachter merkt sich die
	// gezogene Hoehe und zeichnet einmal neu, damit Achse und Balken mitwachsen.
	msu.hoehe_beobachten = function ($flaeche) {
		const el = $flaeche.get(0);
		if (!el || typeof ResizeObserver !== "function") return;
		let warten = null;
		const beobachter = new ResizeObserver(function () {
			if (warten) {
				clearTimeout(warten);
			}
			warten = setTimeout(function () {
				const jetzt = Math.round(el.clientHeight);
				if (!jetzt || Math.abs(jetzt - msu.hoehe()) < 8) return;
				msu.einstellungen.diagramm_hoehe = jetzt;
				msu.sichern();
				msu.diagramm_zeichnen($flaeche);
			}, 250);
		});
		beobachter.observe(el);
	};

	msu.objektwerte = function () {
		const zeilen = (frappe.query_report && frappe.query_report.data) || [];
		const objekte = [];
		zeilen.forEach(function (zeile) {
			if ((zeile.indent || 0) !== 0 || zeile.rolle !== "Objekt") return;
			objekte.push({
				id: zeile.einheit || "",
				kurz: zeile.einheit || "—",
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
		const HOEHE = msu.hoehe();
		const LINKS = 96;
		const RECHTS = 16;
		const OBEN = 12;
		const UNTEN = 86;
		const feldbreite = BREITE - LINKS - RECHTS;
		const feldhoehe = HOEHE - OBEN - UNTEN;
		const skala = msu.skala();

		let groesster = 0;
		objekte.forEach(function (o) {
			if (o.wert > groesster) groesster = o.wert;
		});
		if (!(groesster > 0)) groesster = 1;
		const spanne = skala.hin(groesster) || 1;

		const svg = svg_knoten("svg", {
			viewBox: "0 0 " + BREITE + " " + HOEHE,
			class: "msu-svg",
			style: "height: " + HOEHE + "px",
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
					msu.euro_kurz(skala.zurueck(spanne * anteil))
				)
			);
		}

		const schritt = feldbreite / objekte.length;
		const balken = Math.max(3, Math.min(26, schritt * 0.66));
		const aktives_haus = msu.filterwert("haus");

		objekte.forEach(function (objekt, i) {
			const mitte = LINKS + schritt * (i + 0.5);
			const hoehe = feldhoehe * (skala.hin(Math.max(objekt.wert, 0)) / spanne);
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
		// Ein zweiter Klick auf dasselbe Objekt hebt die Einschränkung wieder auf.
		const ziel = msu.filterwert("haus") === haus ? "" : haus;
		msu.einstieg_setzen("haus", ziel, ziel ? 2 : 1);
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
			".msu-svg { width: 100%; display: block; }",
			".msu-flaeche { resize: vertical; overflow: hidden; min-height: 160px; }",
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
		const skala = msu.skala();
		$leiste
			.find(".msu-skala")
			.text(__("Skala") + ": " + __(skala.name))
			.toggle(!!e.diagramm_offen);
		$leiste.find(".msu-hinweis").text(e.diagramm_offen ? __(skala.hinweis) : "");
	};

	msu.filterwert = function (feld, report) {
		try {
			return (report || frappe.query_report).get_filter_value(feld) || "";
		} catch (e) {
			return "";
		}
	};

	msu.tiefe_uebernehmen = function () {
		if (frappe.query_reports[BERICHT]) {
			frappe.query_reports[BERICHT].initial_depth = msu.einstellungen.tiefe || 1;
		}
	};

	// Gespeicherte Filter setzen. `sanft` schreibt nur in die Eingabefelder, ohne
	// eine Neuberechnung auszuloesen -- so wie es vor dem ersten Lauf gebraucht
	// wird. Felder, die ohnehin schon so stehen, bleiben unberuehrt; deshalb ist
	// der spaetere Abgleich mit dem Server in der Regel ein Nichts-tun.
	msu.filter_uebernehmen = function (report, werte, sanft) {
		const anzuwenden = {};
		Object.keys(werte || {}).forEach(function (feld) {
			const wert = werte[feld];
			if (wert === undefined || wert === null) return;
			if (!report.get_filter(feld)) return;
			if (msu.filterwert(feld, report) === (wert || "")) return;
			anzuwenden[feld] = wert;
		});
		const felder = Object.keys(anzuwenden);
		if (!felder.length) return false;
		if (sanft) {
			felder.forEach(function (feld) {
				try {
					report.get_filter(feld).set_input(anzuwenden[feld]);
				} catch (e) {
					// Steuerelement mag kein set_input: dann eben mit Neuberechnung.
					report.set_filter_value(feld, anzuwenden[feld]);
				}
			});
		} else {
			report.set_filter_value(anzuwenden);
		}
		return true;
	};

	// Einstieg = Filter setzen und den Baum auf die passende Tiefe aufklappen.
	// Steht der Filter schon so, bleibt nur die Tiefe zu tun -- ein unveraenderter
	// Filter loest keine Neuberechnung aus.
	msu.einstieg_setzen = function (feld, wert, tiefe) {
		const report = frappe.query_report;
		if (!report) return;
		msu.tiefe_setzen(tiefe);
		if (msu.filterwert(feld) === (wert || "")) {
			msu.baum_aufklappen(tiefe);
		} else {
			// Nach dem Neuaufbau einmal nachfassen -- der Rahmen klappt zwar selbst
			// bis `initial_depth` auf, aber darauf allein soll ein bewusster Klick
			// des Anwenders nicht angewiesen sein.
			msu.einmal_aufklappen = tiefe;
			report.set_filter_value(feld, wert);
		}
	};

	msu.einstieg = function (ziel) {
		msu.einstieg_setzen("belegung", ziel.belegung, ziel.tiefe);
	};

	msu.filter_aufheben = function () {
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
		$rahmen.find(".msu-flaeche").css("height", msu.hoehe() + "px");

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
		msu.hoehe_beobachten($rahmen.find(".msu-flaeche"));
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
		return msu.einfaerben(data, value);
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

		report.page.add_inner_button(__("Filter aufheben"), function () {
			msu.filter_aufheben();
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
			msu.einstellungen = msu.vorgabe();
			msu.sichern();
			frappe.show_alert({ message: __("Einstellungen zurückgesetzt."), indicator: "green" });
			frappe.query_report.refresh();
		});

		// Der gespeicherte Stand kommt zuerst aus dem Browserspeicher: er ist ohne
		// Serverfrage da und damit noch vor dem ersten Lauf des Berichts. Frueher
		// wurde er erst nach der Serverantwort gesetzt -- der Bericht lief dadurch
		// zweimal, einmal mit den Vorgaben und einmal mit den Filtern des Anwenders.
		msu.einstellungen = Object.assign(msu.vorgabe(), msu.lokal_lesen());
		msu.tiefe_uebernehmen();
		msu.filter_uebernehmen(report, msu.einstellungen.filter, true);
		msu.bereit = true;

		// Der Server haelt den Stand ueber Rechnergrenzen hinweg. Stimmt er mit dem
		// Browserspeicher ueberein -- der Normalfall --, aendert dieser Abgleich
		// nichts und loest auch keinen zweiten Lauf aus.
		msu.laden().then(function (einstellungen) {
			msu.tiefe_uebernehmen();
			msu.filter_uebernehmen(report, einstellungen.filter, false);
			msu.oberflaeche_aufbauen();
		});
	},

	after_datatable_render: function () {
		const msu = axessio.msu;
		msu.oberflaeche_aufbauen();
		if (msu.bereit) {
			msu.filter_merken();
		}
		// Aufgeklappt wird nur nach einem bewussten Einstieg. Bei jedem Rendern zu
		// und wieder aufzuklappen kostete bei tausend Einheiten mehr Zeit als der
		// ganze Bericht -- den Rest erledigt `initial_depth` beim Aufbau.
		if (msu.einmal_aufklappen) {
			const tiefe = msu.einmal_aufklappen;
			msu.einmal_aufklappen = 0;
			msu.baum_aufklappen(tiefe);
		}
	},
};
