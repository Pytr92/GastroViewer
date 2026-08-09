/* Die Karte, ihre Ebenen und der Deckkraftregler.
 *
 * Dieses Modul hat Seiteneffekte: Beim Laden entsteht die Leaflet-Karte,
 * alle Ebenengruppen werden angelegt und der Ebenenschalter gehängt. Das
 * ist Absicht und der Grund, warum es ein eigenes Modul ist — die
 * Reihenfolge ist verbindlich (erst Karte, dann Ebenen, dann Schalter,
 * dann Regler), und als Modul wird sie einmal und vor allen Nutzern
 * ausgeführt. In app.js stand derselbe Code zwischen Funktionsdefinitionen
 * und war nur deshalb richtig, weil das Skript am Seitenende lag.
 *
 * L (Leaflet) wird als klassisches Skript vor den Modulen geladen und ist
 * damit ein globaler Name.
 */

import { state } from './state.js';

/* --------------------------------------------------------------- Karte */

const karte = L.map('karte', { zoomControl: true }).setView([51.163, 10.448], 6);

const osmKarte = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap-Mitwirkende</a>',
});

/* Amtliche Alternative des Bundesamts für Kartographie und Geodäsie.
   In Phase 0 geprüft: WMTS mit TileMatrixSet GLOBAL_WEBMERCATOR, 20 Zoomstufen,
   „Es gelten keine Zugriffsbeschränkungen". Die TileMatrix-IDs sind zweistellig
   (00–19), deshalb muss z aufgefüllt werden — mit {z} allein käme bei Zoom < 10
   eine 400er-Antwort. */
const BasemapDe = L.TileLayer.extend({
  getTileUrl(coords) {
    const z = String(this._getZoomForUrl()).padStart(2, '0');
    return `https://sgx.geodatenzentrum.de/wmts_basemapde/tile/1.0.0/`
      + `${this.options.stil}/default/GLOBAL_WEBMERCATOR/${z}/${coords.y}/${coords.x}.png`;
  },
});
const bkgAttribution = '&copy; <a href="https://basemap.de/">basemap.de</a> / '
  + 'GeoBasis-DE, BKG (dl-de/by-2-0)';
const basemapFarbe = new BasemapDe('', {
  stil: 'de_basemapde_web_raster_farbe', maxZoom: 19, attribution: bkgAttribution,
});
const basemapGrau = new BasemapDe('', {
  stil: 'de_basemapde_web_raster_grau', maxZoom: 19, attribution: bkgAttribution,
});

osmKarte.addTo(karte);

for (const name of ['zensus', 'gastronomie', 'frequenzbringer', 'oepnv', 'leerstand',
  'overture', 'maerkte', 'baustellen', 'airbnb']) {
  state.ebenen[name] = L.layerGroup();
}
/* Die zu Fuß erreichbare Fläche. Canvas statt SVG, weil es je nach Lage einige
   tausend Punkte sind und SVG dabei spürbar träge wird. */
state.gehwegRenderer = L.canvas({ padding: 0.3 });
state.ebenen.gehflaeche = L.layerGroup();
/* Rad-Liefergebiet (4d): dasselbe Prinzip, größeres Gebiet, Radprofil. */
state.ebenen.liefergebiet = L.layerGroup();
/* ÖPNV-Einzugsgebiet (6h): erreichte Halte, nach Fahrzeit eingefärbt. */
state.ebenen.oepnveinzug = L.layerGroup();
/* Übersichtsgitter 1 km/10 km — beantwortet „WO ist es interessant?", bevor
   man klickt. Canvas, weil es bis zu ~1.500 Zellen sind. */
state.uebersichtRenderer = L.canvas({ padding: 0.3 });
state.ebenen.uebersicht = L.layerGroup();
/* Flächen-Scan: Einwohner je Gastronomiebetrieb im 300-m-Umfeld, je
   100-m-Zelle. Die feine Stufe zwischen Übersichtsebene und Umkreis. */
state.scanRenderer = L.canvas({ padding: 0.3 });
state.ebenen.scan = L.layerGroup();
/* Standort-Finder: nummerierte Top-Zellen des Scans nach eigenen
   Gewichten — entsteht auf Knopfdruck in der Scan-Legende. */
state.ebenen.finder = L.layerGroup();
/* Treffer der Markensuche (Gebietsschutz-Check). Bewusst nicht im
   Ebenenschalter: die Ebene entsteht durch die Suche und verschwindet mit dem
   Punktwechsel. */
state.ebenen.marke = L.layerGroup();
/* Gemerkte Punkte als Kartenebene — mit Einzugsgebietskreisen. Zwei
   Kandidaten, deren Kreise sich überschneiden, teilen sich dieselben
   Einwohner und sind keine zwei unabhängigen Optionen. */
state.ebenen.punkte = L.layerGroup();
state.ebenen.zensus.addTo(karte);
state.ebenen.gastronomie.addTo(karte);

const ebenenSchalter = L.control.layers({
  'OpenStreetMap': osmKarte,
  'basemap.de (amtlich)': basemapFarbe,
  'basemap.de grau': basemapGrau,
}, {
  'Übersicht Einwohner (1/10 km)': state.ebenen.uebersicht,
  'Flächen-Scan (Einwohner je Betrieb)': state.ebenen.scan,
  'Standort-Finder (Top 10)': state.ebenen.finder,
  'Gemerkte Punkte': state.ebenen.punkte,
  'Zu Fuß erreichbar': state.ebenen.gehflaeche,
  'Rad-Liefergebiet': state.ebenen.liefergebiet,
  'ÖPNV-Einzugsgebiet': state.ebenen.oepnveinzug,
  'Zensus-Gitter': state.ebenen.zensus,
  'Gastronomie': state.ebenen.gastronomie,
  'Wettbewerb nur in Overture': state.ebenen.overture,
  'Frequenzbringer': state.ebenen.frequenzbringer,
  'ÖPNV': state.ebenen.oepnv,
  'Leerstände (OSM)': state.ebenen.leerstand,
  'Städtische Märkte (M)': state.ebenen.maerkte,
  'Baustellen (M)': state.ebenen.baustellen,
  'Airbnb-Inserate': state.ebenen.airbnb,
}, { collapsed: false }).addTo(karte);
ebenenSchalter.getContainer().classList.add('ebenen-schalter');

/* ------------------------------------------------- Deckkraft der Ebenen */

/* Sobald eine echte Grundkarte darunterliegt, verdeckt das Zensusgitter genau
   das, was man sehen will: Straßenverlauf, Gebäudekanten, Hofflächen. Der
   Regler blendet alle aufgesetzten Ebenen gemeinsam zurück. Die Wahl bleibt
   erhalten, damit sie nicht bei jedem Punktwechsel neu eingestellt werden muss. */
const DECKKRAFT_SPEICHER = 'gastroviewer.deckkraft';

function geladeneDeckkraft() {
  const roh = Number(localStorage.getItem(DECKKRAFT_SPEICHER));
  return Number.isFinite(roh) && roh >= 0.1 && roh <= 1 ? roh : 1;
}
state.deckkraft = geladeneDeckkraft();

/* Rasterebenen (WMS) melden sich hier an, damit der Regler sie mitnimmt. */
state.rasterEbenen = new Set();

function wendeDeckkraftAn() {
  const f = state.deckkraft;
  for (const name of ['zensus', 'gastronomie', 'frequenzbringer', 'oepnv', 'leerstand',
    'overture', 'maerkte', 'baustellen', 'airbnb', 'uebersicht', 'scan', 'marke',
    'gehflaeche', 'liefergebiet', 'oepnveinzug']) {
    state.ebenen[name]?.eachLayer((l) => {
      const basis = l.options?._basisDeckkraft;
      if (basis === undefined || !l.setStyle) return;
      l.setStyle({ fillOpacity: basis * f, opacity: (l.options._basisRand ?? 1) * f });
    });
  }
  for (const r of state.rasterEbenen) {
    if (r.setOpacity) r.setOpacity(f);
  }
  const anzeige = document.getElementById('deckkraft-wert');
  if (anzeige) anzeige.textContent = `${Math.round(f * 100)} %`;
}

function setzeDeckkraft(f) {
  state.deckkraft = Math.min(1, Math.max(0.1, f));
  localStorage.setItem(DECKKRAFT_SPEICHER, String(state.deckkraft));
  wendeDeckkraftAn();
}

const deckkraftRegler = L.control({ position: 'topright' });
deckkraftRegler.onAdd = () => {
  const c = L.DomUtil.create('div', 'leaflet-control deckkraft-regler');
  c.innerHTML = `<label for="deckkraft">Deckkraft der Ebenen
      <span id="deckkraft-wert">${Math.round(state.deckkraft * 100)} %</span></label>
    <input type="range" id="deckkraft" min="10" max="100" step="5"
           value="${Math.round(state.deckkraft * 100)}"
           aria-label="Deckkraft der aufgesetzten Kartenebenen">
    <div class="hinweis-klein">Blendet Gitter und Marker zurück, damit
      Straßen und Gebäude der Grundkarte sichtbar bleiben.</div>`;
  L.DomEvent.disableClickPropagation(c);
  L.DomEvent.disableScrollPropagation(c);
  c.querySelector('#deckkraft').addEventListener('input', (ev) => {
    setzeDeckkraft(Number(ev.target.value) / 100);
  });
  return c;
};
deckkraftRegler.addTo(karte);

export { karte, osmKarte, ebenenSchalter, setzeDeckkraft, wendeDeckkraftAn };
