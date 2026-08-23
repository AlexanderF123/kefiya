# axessio Desk-UI — Responsive-Standard für Übersichtsseiten

Dieser Ordner ist die versionierte Quelle für die Oberfläche der axessio-
Übersichtsseiten auf https://axessio.de. Die Seiten selbst sind keine App-
Dateien, sondern **Workspaces mit Custom HTML Blocks** in der Live-Instanz;
hier liegen die CSS-/JS-Bausteine, damit Änderungen review- und rückrollbar
sind.

## Betroffene Seiten und Bausteine

| Seite (Workspace) | URL | Block | Stylesheet |
|---|---|---|---|
| Property Management | `/app/property-management` | axessio Property Hub | `axih-hub.css` |
| axessio Hausverwaltung | `/app/axessio-hausverwaltung` | axessio Home Hub | `axh-home-hub.css` |
| | | axessio Mein Tag Cockpit | `axmt-mein-tag.css` |
| Facility Management | `/app/facility-management` | axessio Instandhaltung Hub | `axih-hub.css` |
| Finance | `/app/finance` | axessio Finance Hub | `axih-hub.css` |
| Lawyer | `/app/lawyer` | axessio Lawyer Hub | `axih-hub.css` |
| Management | `/app/management` | axessio Management Hub | `axih-hub.css` |
| (Finance, Lawyer, Management) | | axessio Bereichs-Buttons | `axwb-bereichs-buttons.css` |

`ax-fullwidth.js` gehört ans Ende des `script`-Feldes jedes Hub-Blocks.

## Die Regeln (gelten für jede Seite, die wir künftig bauen)

1. **Keine festen Breiten.** Wurzelcontainer `width:100%; max-width:100%`.
   Nie `max-width:1100px` — was begrenzt, ist der Desk, nicht der Block.
2. **Container Queries statt Media Queries.** Der Block sitzt in einer Spalte,
   deren Breite von der ein-/ausgeklappten Seitenleiste abhängt; das Fenster
   ist das falsche Maß. Auf dem Wurzelcontainer
   `container-type:inline-size; container-name:<prefix>`, Breakpoints als
   `@container <prefix> (max-width:…)`. Dazu ein
   `@supports not (container-type:inline-size)`-Block mit denselben Regeln als
   `@media`-Fallback.
3. **Fließende Größen:** `clamp(min, Xcqi, max)` für Schrift, Abstände und
   Kopfbereiche. Jeder cq-Angabe geht eine reine Pixel-Deklaration voraus:
   `font-size:26px;font-size:clamp(19px,3.2cqi,26px)`.
4. **Raster ohne Überlauf:**
   `grid-template-columns:repeat(auto-fill,minmax(min(232px,100%),1fr))`.
   Ohne `min(…,100%)` schiebt eine 232-px-Spalte die Seite bei schmalem
   Fenster seitlich heraus.
5. **Umbrechen statt quetschen:** Kopfzeilen `flex-wrap:wrap`, Textblöcke
   `flex:1 1 260px`, `.wrapper *{min-width:0}`, `overflow-wrap:anywhere` für
   lange Wörter, IBANs und Objektnamen.
6. **Volle Bildschirmbreite:** Der Desk kappt seinen Inhalt per Bootstrap-
   `.container` auf ca. 1140 px. `ax-fullwidth.js` hebt das nur für die eigene
   Seite auf und stellt es beim Seitenwechsel wieder her.
7. **Zeigegerät und Bewegung:** `@media (hover:none)` kein Hover-Anheben,
   `@media (prefers-reduced-motion:reduce)` keine Transitions.
8. **Abnahme in drei Breiten:** ~380 px (Telefon), ~760 px (Tablet/halbes
   Fenster), ≥1600 px (breiter Monitor). Kein horizontaler Scrollbalken, kein
   abgeschnittener Text, keine Kachel unter ~170 px.

## Ausrollen

Custom HTML Blocks sind reine Client-Artefakte: Feld `style` bzw. `script` in
`/app/custom-html-block/<Name>` ersetzen, speichern, im Desk **Strg+F5**.
Kein `bench clear-cache` nötig — anders als bei Server Scripts.

Risikoklasse **A** nach `axessio-dev-process` (nur Oberfläche, keine
Datenänderung, jederzeit deploybar und rückrollbar).
