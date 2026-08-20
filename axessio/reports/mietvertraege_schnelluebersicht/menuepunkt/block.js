// axessio Schnelluebersicht Weiche
// Diese Seite ist nur ein Menuepunkt: Frappe zeigt in der Seitenleiste
// Arbeitsbereiche, keine Berichte. Der Aufruf landet deshalb hier und wird
// sofort auf den Bericht weitergereicht. Der sichtbare Link bleibt als
// Rueckfallebene stehen, falls die Weiterleitung nicht greift.
(function () {
    var ZIEL_ROUTE = ['query-report', 'Mietverträge Schnellübersicht'];
    var ZIEL_PFAD = '/app/query-report/' + encodeURIComponent('Mietverträge Schnellübersicht');

    function auf_arbeitsbereich() {
        // Der Block steckt nur in dieser einen Seite -- steht die Route auf
        // einem Arbeitsbereich, sind wir hier richtig und leiten weiter.
        try {
            var r = (frappe.get_route && frappe.get_route()) || [];
            return String(r[0] || '').toLowerCase().indexOf('workspace') === 0;
        } catch (e) {
            return false;
        }
    }

    function los() {
        if (!auf_arbeitsbereich()) return;
        try {
            if (window.frappe && frappe.set_route) { frappe.set_route(ZIEL_ROUTE); }
        } catch (e) {
            // egal -- die harte Weiterleitung unten faengt das ab
        }
        setTimeout(function () {
            if (auf_arbeitsbereich()) { window.location.replace(ZIEL_PFAD); }
        }, 400);
    }

    setTimeout(los, 0);
})();
