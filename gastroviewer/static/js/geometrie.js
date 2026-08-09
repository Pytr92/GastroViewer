/* Geometrie ohne Karte.
 *
 * `ueberlappungen` rechnet ausschließlich mit Koordinaten und Radien — es
 * fasst keine Kartenebene an. Deshalb steht es hier und nicht im
 * Kartenmodul: So kann die Vergleichstabelle es benutzen, ohne die halbe
 * Karte mitzuziehen.
 *
 * L (Leaflet) wird als klassisches Skript vor den Modulen geladen und ist
 * damit ein globaler Name.
 */

/* eslint-disable no-undef */
export function ueberlappungen(zeilen) {
  const paare = [];
  for (let i = 0; i < zeilen.length; i += 1) {
    for (let j = i + 1; j < zeilen.length; j += 1) {
      const a = zeilen[i];
      const b = zeilen[j];
      if (a.lat == null || b.lat == null) continue;
      const dist = L.latLng(a.lat, a.lon).distanceTo(L.latLng(b.lat, b.lon));
      const summe = (a.radius || 0) + (b.radius || 0);
      if (dist < summe) {
        paare.push({ a: a.label, b: b.label, aId: a.id, bId: b.id,
          distanz_m: Math.round(dist), um_m: Math.round(summe - dist) });
      }
    }
  }
  return paare;
}
