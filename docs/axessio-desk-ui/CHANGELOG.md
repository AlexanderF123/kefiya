# Änderungen an den axessio-Übersichtsseiten

## 2026-08-23 — Übersichtsseiten responsive; Commercial Management → Property Management

**Responsive (Risikoklasse A)**

Alle sechs Übersichtsseiten passen sich jetzt der verfügbaren Breite an statt
auf 1100 px festzustehen:

- `.axih` (5 Hub-Blöcke), `.axh` (Home Hub), `.axmt` (Mein Tag Cockpit) und
  `.axwb` (Bereichs-Buttons): feste Breite entfernt, Container Queries,
  `clamp(…cqi…)` für Schrift und Abstände, `minmax(min(…,100%),1fr)` in allen
  Rastern, Umbruch statt Quetschen im Kopfbereich, Fallbacks für Browser ohne
  Container-Query-Unterstützung, Rücksicht auf Touch und
  `prefers-reduced-motion`.
- Neuer Baustein `ax-fullwidth.js` am Ende jedes Hub-Skripts: hebt die
  Bootstrap-Breitenbegrenzung des Desks (ca. 1140 px) für die eigene Seite auf
  und stellt sie beim Seitenwechsel wieder her.

**Umbenennung**

„Kaufmännische Verwaltung" heißt technisch nicht mehr *Commercial Management*,
sondern **Property Management**:

- Workspace `Commercial Management` → `Property Management`,
  URL `/app/commercial-management` → `/app/property-management`.
- Acht Unterseiten (Leasing, Leases, Schnellübersicht Mietverträge, Customers,
  Insurances, Consumer Price Index, Management Fee Invoices, Rent Increases)
  auf den neuen Elternbereich umgehängt; Reihenfolge unverändert.
- Custom HTML Block `axessio Commercial Hub` → `axessio Property Hub`.
- Übersetzung `de`: Quelltext `Property Management` → „Kaufmännische
  Verwaltung"; die deutsche Oberfläche bleibt unverändert.
- Kachelzuordnung im Home Hub (`META`) auf den neuen Namen gezogen.

Alte Lesezeichen auf `/app/commercial-management` laufen ins Leere — Frappe
legt für umbenannte Workspaces keine Weiterleitung an.
