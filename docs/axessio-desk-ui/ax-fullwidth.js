// axessio Uebersichtsseiten - volle Fensterbreite
// Der Desk begrenzt seinen Inhalt per Bootstrap-".container" auf ca. 1140 px.
// Die Uebersichtsseiten sollen die ganze Breite des Bildschirms nutzen, damit
// bei breiten Monitoren mehr Kacheln je Zeile stehen. Dieser Baustein hebt die
// Begrenzung nur fuer die Seite auf, auf der er laeuft, und stellt sie beim
// Verlassen der Seite wieder her. Ohne Datenzugriff, rein visuell.
// Dieser Block gehoert ans Ende des "script"-Feldes jedes Hub-Blocks.
(function () {
  var sr = (typeof root_element !== 'undefined' && root_element) ? root_element : null;
  if (!sr) { return; }

  // Vom Shadow Root in das normale Dokument wechseln
  var node = sr;
  try { var rn = sr.getRootNode && sr.getRootNode(); if (rn && rn.host) { node = rn.host; } } catch (e) {}
  if (!node || !node.closest) { return; }

  // Alle Breitenbegrenzer der aktuellen Desk-Seite einsammeln (Kopf und Inhalt)
  var page = node.closest('.page-container') || node.closest('.content') || null;
  var boxes = [];
  if (page && page.querySelectorAll) {
    var found = page.querySelectorAll('.container');
    for (var i = 0; i < found.length; i++) { boxes.push(found[i]); }
  }
  for (var el = node; el && el !== document.body; el = el.parentElement) {
    if (el.classList && el.classList.contains('container') && boxes.indexOf(el) < 0) { boxes.push(el); }
  }

  var touched = [];
  for (var j = 0; j < boxes.length; j++) {
    if (boxes[j].style.maxWidth === 'none') { continue; }
    touched.push([boxes[j], boxes[j].style.maxWidth]);
    boxes[j].style.maxWidth = 'none';
  }
  if (!touched.length) { return; }

  // Beim Seitenwechsel den Ursprungszustand zurueckgeben
  if (!window.axWideRestore) {
    window.axWideRestore = [];
    try {
      frappe.router.on('change', function () {
        var list = window.axWideRestore || [];
        window.axWideRestore = [];
        for (var k = 0; k < list.length; k++) {
          try { list[k][0].style.maxWidth = list[k][1]; } catch (e) {}
        }
      });
    } catch (e) {}
  }
  for (var m = 0; m < touched.length; m++) { window.axWideRestore.push(touched[m]); }
})();
