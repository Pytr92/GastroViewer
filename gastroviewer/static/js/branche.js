/* Branchenprofile — welche OSM-Typen als direkter Wettbewerb zählen.
 *
 * Eigenes Modul, weil zwei Seiten dasselbe Profil brauchen: der
 * Gastronomieblock im Datenreiter und das Schätzmodul, das die
 * branchenscharfe Wettbewerberzahl als Vorgabe anbietet. Läge es in einem
 * der beiden, importierte der andere quer.
 */

import { state } from './state.js';

/* ------------------------------------------------- Branchenprofile
   Für einen Imbiss sind 30 Cafés kein Wettbewerb. Ein Profil legt fest,
   welche OSM-Typen (amenity) als direkter Wettbewerb zählen — mehr nicht:
   es filtert vorhandene Daten, es lädt nichts nach und wertet nichts um.
   Grundlage ist bewusst nur der amenity-Typ; das cuisine-Feld ist Freitext
   und bleibt, wie überall im Werkzeug, unangetastet stehen. */
export const BRANCHEN = [
  { key: 'alle', label: 'alle Gastronomie', typen: null },
  { key: 'schnellrestaurant', label: 'Schnellrestaurant / Imbiss',
    typen: ['fast_food', 'food_court'] },
  { key: 'restaurant', label: 'Restaurant', typen: ['restaurant'] },
  { key: 'cafe', label: 'Café', typen: ['cafe'] },
  { key: 'bar', label: 'Bar / Kneipe / Abendlokal',
    typen: ['bar', 'pub', 'biergarten', 'nightclub'] },
  { key: 'eisdiele', label: 'Eisdiele', typen: ['ice_cream'] },
];
export const BRANCHE_SPEICHER = 'gastroviewer.branche';

export function brancheKennzahlen(gastro, typen) {
  const treffer = typen ? gastro.filter((g) => typen.includes(g.typ)) : gastro;
  const dist = treffer.map((g) => g.distanz_m).filter((d) => typeof d === 'number');
  const einwohner = state.daten.zensus?.data?.bevoelkerung?.einwohner?.wert;
  return {
    anzahl: treffer.length,
    bis300: treffer.filter((g) => g.distanz_m <= 300).length,
    naechster: dist.length ? Math.min(...dist) : null,
    ketten: treffer.filter((g) => g.kette).length,
    je1000: einwohner ? (treffer.length / einwohner) * 1000 : null,
  };
}
