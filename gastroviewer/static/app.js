/* Standort-Datenterminal — Frontend.
 *
 * Zwei Grundsätze aus der Spec bestimmen den Aufbau:
 *
 * 1. Jede Quelle lädt einzeln (§5 „Ladefortschritt je Quelle einzeln anzeigen").
 *    Deshalb wird nicht /api/point aufgerufen, sondern je Block ein eigener
 *    Endpunkt. Fällt eine Quelle aus, laufen die übrigen weiter und der Block
 *    zeigt die konkrete Ursache statt zu verschwinden.
 * 2. Kein Wert ohne Herkunft (§7). Jeder Block bekommt eine Fußzeile
 *    „Quelle · Stand · Lizenz", jede Aggregation nennt ihre Zellenbasis.
 *    Fehlende Werte erscheinen als „keine Angabe", nie als 0.
 */

/* Module statt einer Datei: Die Oberfläche war auf 6 400 Zeilen gewachsen,
   in denen jede Änderung eine Suche in einem Text war, den niemand mehr im
   Kopf hat. Aufgeteilt wird schrittweise und jeweils gegen die 44
   Browserprüfungen abgesichert — ohne dieses Netz wäre der Umbau nicht
   verantwortbar.

   Kein Buildschritt: native ES-Module, eingebunden mit type="module".
   score.js bleibt bewusst ein klassisches Skript, weil bericht.html es
   ebenfalls lädt; seine Funktionen sind daher weiterhin globale Namen. */

import {
  NF, NF1, NF2, OVERPASS_WARNSCHWELLE, nfFest, zahl,
} from './js/format.js';
import { state } from './js/state.js';
import {
  beiBlockRender, block, el, esc, fehlerbox, hinweisZeile, kennzahl,
  setInhalt, setQuelle, setStatus, warnungen,
} from './js/dom.js';

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

/* ---------------------------------------- Übersichtsgitter (Erkundung) */

/* Feste Klassengrenzen statt Quantile: beim Schwenken über München oder Bayern
   müssen die Farben vergleichbar bleiben. Gewählte Grenzen, keine Messwerte —
   die Legende sagt das. */
const UEBERSICHT_KLASSEN = {
  '1km': { titel: 'Einwohner je 1-km-Zelle', grenzen: [50, 250, 1000, 3000, 8000] },
  '10km': { titel: 'Einwohner je 10-km-Zelle', grenzen: [1000, 5000, 20000, 75000, 200000] },
};

const uebersichtState = { schluessel: null, laedt: false };

function uebersichtEbene() {
  return karte.getZoom() >= 12 ? '1km' : '10km';
}

function uebersichtFarbe(ew, grenzen) {
  let i = 0;
  while (i < grenzen.length && ew > grenzen[i]) i += 1;
  return FARBEN[i];
}

const uebersichtLegende = L.control({ position: 'bottomright' });
uebersichtLegende.onAdd = () => {
  const c = L.DomUtil.create('div', 'leaflet-control uebersicht-legende');
  c.id = 'uebersicht-legende';
  return c;
};

function zeigeUebersichtLegende(ebene, anzahl, hinweis) {
  const c = document.getElementById('uebersicht-legende');
  if (!c) return;
  if (hinweis) {
    c.replaceChildren(el('div', { class: 'hinweis-klein' }, hinweis));
    return;
  }
  const k = UEBERSICHT_KLASSEN[ebene];
  const zeilen = [el('strong', {}, k.titel)];
  let von = 0;
  for (let i = 0; i <= k.grenzen.length; i += 1) {
    const bis = k.grenzen[i];
    zeilen.push(el('div', { class: 'legende-zeile' },
      el('i', { style: `background:${FARBEN[i]}` }),
      bis === undefined ? `über ${NF.format(von)}` : `${NF.format(von)} – ${NF.format(bis)}`));
    von = bis;
  }
  zeilen.push(el('div', { class: 'hinweis-klein' },
    `${NF.format(anzahl)} Zellen · feste, gewählte Klassen · Zensus 2022 · `
    + 'Klick auf eine Zelle: Werte und „Hier analysieren"'));
  c.replaceChildren(...zeilen);
}

function uebersichtPopup(z, ebene, mitte) {
  const wert = (v, einheit = '', nk = 0) => (v === null || v === undefined
    ? 'keine Angabe' : `${zahl(v, nk)}${einheit}`);
  const inhalt = el('div', {},
    el('h4', {}, `Zensuszelle ${z.id || ''} (${ebene})`),
    el('table', {},
      el('tr', {}, el('td', {}, 'Einwohner'), el('td', {}, el('b', {}, wert(z.einwohner)))),
      el('tr', {}, el('td', {}, 'Durchschnittsalter'), el('td', {}, el('b', {}, wert(z.alter, ' J.', 1)))),
      el('tr', {}, el('td', {}, 'Nettokaltmiete'), el('td', {}, el('b', {}, wert(z.miete_qm, ' €/m²', 2)))),
      el('tr', {}, el('td', {}, 'Leerstandsquote'), el('td', {}, el('b', {}, wert(z.leerstand, ' %', 1))))),
    el('button', {
      style: 'margin-top:7px',
      onclick: () => { karte.closePopup(); setzePunkt(mitte[0], mitte[1], true); },
    }, 'Hier analysieren'),
    el('p', { class: 'hinweis-klein' },
      'Setzt den Punkt in die Zellmitte und lädt alle Blöcke.'));
  return inhalt;
}

async function ladeUebersicht() {
  if (!karte.hasLayer(state.ebenen.uebersicht)) return;
  const ebene = uebersichtEbene();
  const b = karte.getBounds();
  const west = Math.max(5.0, b.getWest());
  const ost = Math.min(16.0, b.getEast());
  const sued = Math.max(46.5, b.getSouth());
  const nord = Math.min(56.0, b.getNorth());
  const k = UEBERSICHT_KLASSEN[ebene];

  if (west >= ost || sued >= nord) {
    state.ebenen.uebersicht.clearLayers();
    zeigeUebersichtLegende(ebene, 0, 'Der Ausschnitt liegt außerhalb Deutschlands.');
    return;
  }
  const spanne = ebene === '1km' ? [1.6, 1.0] : [7.5, 5.0];
  if ((ost - west) > spanne[0] || (nord - sued) > spanne[1]) {
    state.ebenen.uebersicht.clearLayers();
    zeigeUebersichtLegende(ebene, 0,
      'Für die Übersicht weiter hineinzoomen — dieser Ausschnitt ist zu groß.');
    return;
  }

  const schluessel = `${ebene}|${west.toFixed(2)}|${sued.toFixed(2)}|${ost.toFixed(2)}|${nord.toFixed(2)}`;
  if (schluessel === uebersichtState.schluessel || uebersichtState.laedt) return;
  uebersichtState.laedt = true;
  try {
    const d = await hole('/api/gitter', { ebene, west, sued, ost, nord });
    if (!d.ok) {
      zeigeUebersichtLegende(ebene, 0, `Übersicht nicht ladbar: ${d.error?.message || '?'}`);
      return;
    }
    uebersichtState.schluessel = schluessel;
    const gruppe = state.ebenen.uebersicht;
    gruppe.clearLayers();
    for (const z of d.data.zellen) {
      const latlngs = z.ring.map((pt) => [pt[1], pt[0]]);
      const mitte = [
        latlngs.reduce((s, x) => s + x[0], 0) / latlngs.length,
        latlngs.reduce((s, x) => s + x[1], 0) / latlngs.length,
      ];
      const ew = z.einwohner ?? 0;
      const poly = L.polygon(latlngs, {
        renderer: state.uebersichtRenderer,
        color: '#ffffff', weight: 0.5,
        fillColor: uebersichtFarbe(ew, k.grenzen),
        fillOpacity: 0.55 * state.deckkraft, opacity: 0.6 * state.deckkraft,
        _basisDeckkraft: 0.55, _basisRand: 0.6,
      });
      poly.bindPopup(() => uebersichtPopup(z, ebene, mitte), { maxWidth: 300 });
      gruppe.addLayer(poly);
    }
    zeigeUebersichtLegende(ebene, d.data.zellen.length, null);
  } catch (e) {
    zeigeUebersichtLegende(ebene, 0, `Übersicht nicht ladbar: ${e.message}`);
  } finally {
    uebersichtState.laedt = false;
  }
}

karte.on('moveend', () => ladeUebersicht());
karte.on('overlayadd', (ev) => {
  if (ev.layer === state.ebenen.uebersicht) {
    uebersichtLegende.addTo(karte);
    uebersichtState.schluessel = null;
    ladeUebersicht();
  }
});
karte.on('overlayremove', (ev) => {
  if (ev.layer === state.ebenen.uebersicht) {
    state.ebenen.uebersicht.clearLayers();
    uebersichtState.schluessel = null;
    uebersichtLegende.remove();
  }
});

/* ------------------------------------------------------- Flächen-Scan */

/* Die feine Stufe zwischen Übersichtsebene (WO wohnen Menschen?) und Umkreis
   (WIE ist es hier?): WO im Viertel teilen sich viele Anwohner wenige
   Betriebe? Backend: eine Zensus- und EINE Overpass-Abfrage für den ganzen
   Ausschnitt — deshalb lädt der Scan beim Einschalten und danach nur auf
   Knopfdruck, nicht bei jedem Schwenken. */

/* Feste, gewählte Klassen wie bei der Übersicht — beim Schwenken müssen die
   Farben vergleichbar bleiben. Grüne Skala, damit sie sich vom blauen
   Zensusgitter unterscheidet.

   Drei Metriken aus denselben Zellwerten — der Wechsel zeichnet nur um und
   löst KEINE neue Abfrage aus. Die Klassengrenzen sind gewählt, keine
   Statistik, und stehen als solche in der Legende. */
const SCAN_METRIKEN = [
  { key: 'je_betrieb', titel: 'Einwohner je Gastronomiebetrieb',
    grenzen: [100, 300, 700, 1500, 3000],
    deutung: 'Dunkel = viele Anwohner je Betrieb — ein Suchhinweis, keine Entscheidung.' },
  { key: 'betriebe_umfeld', titel: 'Betriebe im 300-m-Umfeld',
    grenzen: [1, 3, 7, 15, 30],
    deutung: 'Dunkel = Gastro-Cluster. Cluster heißt Wettbewerb UND Lauflage — beides zugleich.' },
  { key: 'einwohner_umfeld', titel: 'Einwohner im 300-m-Umfeld',
    grenzen: [500, 1500, 3000, 6000, 10000],
    deutung: 'Dunkel = dichte Wohnbevölkerung (Zensus 2022, ohne Büros und Touristen).' },
];
const SCAN_METRIK_SPEICHER = 'gastroviewer.scanmetrik';
const SCAN_FARBEN = ['#f4f9f0', '#d9ecc6', '#b4d893', '#86bc62', '#569940', '#2f712c'];
const SCAN_OHNE_BETRIEB = '#1c4f22';

function scanMetrik() {
  const key = localStorage.getItem(SCAN_METRIK_SPEICHER);
  return SCAN_METRIKEN.find((m) => m.key === key) || SCAN_METRIKEN[0];
}
/* Etwas unter dem Server-Limit, damit die Kachelrundung des Backends die
   Box nicht über die Abweisungsgrenze hinausschiebt. */
const SCAN_SPANNE = [0.055, 0.04];

const scanState = { schluessel: null, laedt: false, status: null, daten: null };

const scanLegende = L.control({ position: 'bottomright' });
scanLegende.onAdd = () => {
  const c = L.DomUtil.create('div', 'leaflet-control uebersicht-legende');
  c.id = 'scan-legende';
  L.DomEvent.disableClickPropagation(c);
  return c;
};

function scanFarbe(z, metrik) {
  const wert = z[metrik.key];
  if (wert === null || wert === undefined) {
    // Nur bei „je Betrieb" ist Fehlend eine eigene Aussage (kein Betrieb).
    return metrik.key === 'je_betrieb' ? SCAN_OHNE_BETRIEB : SCAN_FARBEN[0];
  }
  let i = 0;
  while (i < metrik.grenzen.length && wert > metrik.grenzen[i]) i += 1;
  return SCAN_FARBEN[i];
}

function scanBox() {
  /* Ist der Kartenausschnitt größer als das Scanfenster, wird das Fenster um
     die Kartenmitte gelegt — der gestrichelte Rahmen zeigt, was gescannt ist. */
  const b = karte.getBounds();
  const c = karte.getCenter();
  const west = Math.max(5.0, b.getWest(), c.lng - SCAN_SPANNE[0] / 2);
  const ost = Math.min(16.0, b.getEast(), c.lng + SCAN_SPANNE[0] / 2);
  const sued = Math.max(46.5, b.getSouth(), c.lat - SCAN_SPANNE[1] / 2);
  const nord = Math.min(56.0, b.getNorth(), c.lat + SCAN_SPANNE[1] / 2);
  if (west >= ost || sued >= nord) return null;
  return { west, sued, ost, nord };
}

function zeigeScanLegende(status) {
  const c = document.getElementById('scan-legende');
  if (!c) return;
  const metrik = scanMetrik();
  if (status.hinweis) {
    c.replaceChildren(el('strong', {}, metrik.titel),
      el('div', { class: 'hinweis-klein' }, status.hinweis));
    return;
  }
  const auswahl = el('select', { onchange: (ev) => {
    localStorage.setItem(SCAN_METRIK_SPEICHER, ev.target.value);
    zeichneScan();
  } }, SCAN_METRIKEN.map((m) => {
    const o = el('option', { value: m.key }, m.titel);
    if (m.key === metrik.key) o.selected = true;
    return o;
  }));
  const zeilen = [el('strong', {}, 'Flächen-Scan'), auswahl];
  let von = 0;
  for (let i = 0; i <= metrik.grenzen.length; i += 1) {
    const bis = metrik.grenzen[i];
    zeilen.push(el('div', { class: 'legende-zeile' },
      el('i', { style: `background:${SCAN_FARBEN[i]}` }),
      bis === undefined ? `über ${NF.format(von)}` : `${NF.format(von)} – ${NF.format(bis)}`));
    von = bis;
  }
  if (metrik.key === 'je_betrieb') {
    zeilen.push(el('div', { class: 'legende-zeile' },
      el('i', { style: `background:${SCAN_OHNE_BETRIEB}` }), 'kein Betrieb im Umfeld'));
  }
  zeilen.push(el('div', { class: 'hinweis-klein' },
    `${NF.format(status.zellen)} Zellen · ${NF.format(status.betriebe)} Betriebe · `
    + '300-m-Umfeld je 100-m-Zelle · feste, gewählte Klassen · Wechsel der '
    + 'Kennzahl zeichnet nur um, ohne neue Abfrage'));
  zeilen.push(el('div', { class: 'hinweis-klein' },
    `${metrik.deutung} OSM zählt Betriebe unvollständig: Betriebszahlen sind `
    + 'Untergrenzen, „je Betrieb“-Werte damit Obergrenzen.'));
  if (status.veraltet) {
    zeilen.push(el('button', { class: 'scan-knopf', onclick: () => ladeScan() },
      'Diesen Ausschnitt scannen'));
  }
  zeilen.push(...finderBedienung());
  c.replaceChildren(...zeilen);
}

/* ------------------------------------------------- Standort-Finder (Z4) */

/* Verheiratet Scan und Gewichtungsidee des Gesamt-Scores: die Zellen des
   gescannten Ausschnitts werden nach EIGENEN Gewichten geordnet und die
   zehn besten nummeriert auf die Karte gelegt. Ehrlich beschriftet: Das
   Komposit rechnet nur über die drei Scan-Kennzahlen (Perzentilränge im
   Ausschnitt), nicht über den vollen Gesamt-Score — der braucht je Punkt
   eine komplette Analyse. Reine Lokalrechnung, keine neue Abfrage. */
const FINDER_SPEICHER = 'gastroviewer.finder';

function finderGewichte() {
  try {
    const g = JSON.parse(localStorage.getItem(FINDER_SPEICHER) || '{}');
    return {
      chance: [0, 1, 2, 3].includes(g.chance) ? g.chance : 2,
      dichte: [0, 1, 2, 3].includes(g.dichte) ? g.dichte : 1,
      cluster: [-2, -1, 0, 1, 2].includes(g.cluster) ? g.cluster : 0,
    };
  } catch { return { chance: 2, dichte: 1, cluster: 0 }; }
}

function finderBedienung() {
  const g = finderGewichte();
  const wahl = (name, werte, wert, titel) => el('label', { class: 'finder-gewicht' },
    `${titel} `,
    el('select', { onchange: (ev) => {
      const neu = finderGewichte();
      neu[name] = Number(ev.target.value);
      localStorage.setItem(FINDER_SPEICHER, JSON.stringify(neu));
    } }, werte.map((w) => {
      const o = el('option', { value: String(w) }, String(w));
      if (w === wert) o.selected = true;
      return o;
    })));
  return [
    el('div', { class: 'legende-zeile' }, el('strong', {}, 'Standort-Finder')),
    wahl('chance', [0, 1, 2, 3], g.chance, 'Einwohner je Betrieb (Chance)'),
    wahl('dichte', [0, 1, 2, 3], g.dichte, 'Einwohnerdichte im Umfeld'),
    wahl('cluster', [-2, -1, 0, 1, 2], g.cluster,
      'Gastro-Cluster (− meiden … + suchen)'),
    el('button', { class: 'scan-knopf', onclick: () => zeigeFinder() },
      'Top 10 nach meinen Gewichten'),
  ];
}

function zeigeFinder() {
  const daten = scanState.daten;
  state.ebenen.finder.clearLayers();
  if (!daten || !daten.zellen?.length) return;
  const g = finderGewichte();
  const summe = g.chance + g.dichte + Math.abs(g.cluster);
  if (!summe) return;
  const zellen = daten.zellen.filter((z) => z.einwohner_umfeld > 0);

  // Perzentilrang je Kennzahl im gescannten Ausschnitt (0 … 1).
  const rang = (werte) => {
    const sortiert = [...werte].sort((a, b) => a - b);
    return (w) => sortiert.findIndex((x) => x >= w) / Math.max(1, sortiert.length - 1);
  };
  // „Kein Betrieb im Umfeld" ist für die Chance-Kennzahl der Extremfall —
  // er zählt als bester Rang und wird in der Liste eigens benannt.
  const chanceWerte = zellen.map((z) => z.je_betrieb ?? Infinity);
  const rc = rang(chanceWerte.filter(Number.isFinite));
  const rd = rang(zellen.map((z) => z.einwohner_umfeld));
  const rk = rang(zellen.map((z) => z.betriebe_umfeld));

  const bewertet = zellen.map((z) => {
    const chance = z.je_betrieb === null || z.je_betrieb === undefined
      ? 1 : rc(z.je_betrieb);
    const cluster = rk(z.betriebe_umfeld);
    const punkte = (g.chance * chance + g.dichte * rd(z.einwohner_umfeld)
      + Math.abs(g.cluster) * (g.cluster >= 0 ? cluster : 1 - cluster)) / summe;
    return { z, punkte };
  }).sort((a, b) => b.punkte - a.punkte).slice(0, 10);

  bewertet.forEach((b, i) => {
    const ring = b.z.ring.map((pt) => [pt[1], pt[0]]);
    const mitte = [
      ring.reduce((s, x) => s + x[0], 0) / ring.length,
      ring.reduce((s, x) => s + x[1], 0) / ring.length,
    ];
    const marker = L.marker(mitte, {
      icon: L.divIcon({
        className: 'finder-marker',
        html: `<div class="finder-nummer">${i + 1}</div>`,
        iconSize: [26, 26], iconAnchor: [13, 13],
      }),
      title: `Platz ${i + 1} — ${Math.round(b.punkte * 100)} von 100`,
    });
    marker.bindPopup(() => el('div', {},
      el('h4', {}, `Standort-Finder: Platz ${i + 1}`),
      el('table', {},
        el('tr', {}, el('td', {}, 'Komposit (eigene Gewichte)'),
          el('td', {}, el('b', {}, `${Math.round(b.punkte * 100)} / 100`))),
        el('tr', {}, el('td', {}, 'Einwohner je Betrieb'),
          el('td', {}, el('b', {}, b.z.je_betrieb === null
            ? 'kein Betrieb im Umfeld' : NF.format(b.z.je_betrieb)))),
        el('tr', {}, el('td', {}, 'Einwohner im 300-m-Umfeld'),
          el('td', {}, el('b', {}, NF.format(b.z.einwohner_umfeld)))),
        el('tr', {}, el('td', {}, 'Betriebe im 300-m-Umfeld'),
          el('td', {}, el('b', {}, NF.format(b.z.betriebe_umfeld))))),
      el('button', {
        style: 'margin-top:7px',
        onclick: () => { karte.closePopup(); setzePunkt(mitte[0], mitte[1], true); },
      }, 'Hier analysieren'),
      el('p', { class: 'hinweis-klein' },
        'Rangordnung nur aus den drei Scan-Kennzahlen (Perzentile im '
        + 'gescannten Ausschnitt) — kein Gesamt-Score. OSM-Betriebszahlen '
        + 'sind Untergrenzen.')), { maxWidth: 300 });
    state.ebenen.finder.addLayer(marker);
  });
  if (!karte.hasLayer(state.ebenen.finder)) {
    state.ebenen.finder.addTo(karte);
  }
}

function scanPopup(z, mitte) {
  return el('div', {},
    el('h4', {}, `Zensuszelle ${z.id || ''}`),
    el('table', {},
      el('tr', {}, el('td', {}, 'Einwohner (Zelle)'), el('td', {}, el('b', {}, NF.format(z.einwohner)))),
      el('tr', {}, el('td', {}, 'Einwohner im 300-m-Umfeld'), el('td', {}, el('b', {}, NF.format(z.einwohner_umfeld)))),
      el('tr', {}, el('td', {}, 'Betriebe im 300-m-Umfeld'), el('td', {}, el('b', {}, NF.format(z.betriebe_umfeld)))),
      el('tr', {}, el('td', {}, 'Einwohner je Betrieb'),
        el('td', {}, el('b', {}, z.je_betrieb === null ? 'kein Betrieb im Umfeld' : NF.format(z.je_betrieb))))),
    el('button', {
      style: 'margin-top:7px',
      onclick: () => { karte.closePopup(); setzePunkt(mitte[0], mitte[1], true); },
    }, 'Hier analysieren'),
    el('p', { class: 'hinweis-klein' },
      'Betriebszahl aus OSM (Untergrenze). Zulauf von Büros, Passanten und '
      + 'Touristen sieht die Kennzahl nicht.'));
}

async function ladeScan() {
  if (!karte.hasLayer(state.ebenen.scan)) return;
  if (karte.getZoom() < 13) {
    state.ebenen.scan.clearLayers();
    scanState.schluessel = null;
    scanState.status = null;
    zeigeScanLegende({
      hinweis: 'Zum Scannen bis mindestens Zoomstufe 13 hineinzoomen — der '
        + 'Scan arbeitet auf dem 100-m-Gitter. Für die große Fläche ist die '
        + 'Übersichtsebene (1/10 km) da.',
    });
    return;
  }
  const box = scanBox();
  if (!box) {
    zeigeScanLegende({ hinweis: 'Der Ausschnitt liegt außerhalb Deutschlands.' });
    return;
  }
  const schluessel = `${box.west.toFixed(3)}|${box.sued.toFixed(3)}|${box.ost.toFixed(3)}|${box.nord.toFixed(3)}`;
  if (scanState.laedt) return;
  if (schluessel === scanState.schluessel && scanState.status) {
    zeigeScanLegende(scanState.status);
    return;
  }
  scanState.laedt = true;
  zeigeScanLegende({
    hinweis: 'scannt — eine Zensus- und eine Overpass-Abfrage für den ganzen Ausschnitt …',
  });
  try {
    const d = await hole('/api/scan', box);
    if (!d.ok) {
      zeigeScanLegende({ hinweis: `Scan nicht möglich: ${d.error?.message || '?'}` });
      return;
    }
    scanState.schluessel = schluessel;
    scanState.daten = d.data;
    zeichneScan();
  } catch (e) {
    zeigeScanLegende({ hinweis: `Scan nicht möglich: ${e.message}` });
  } finally {
    scanState.laedt = false;
  }
}

/* Zeichnet den zuletzt geladenen Scan mit der gewählten Metrik — reine
   Umfärbung aus scanState.daten, keine neue Abfrage. */
function zeichneScan() {
  const daten = scanState.daten;
  if (!daten) return;
  const metrik = scanMetrik();
  const gruppe = state.ebenen.scan;
  gruppe.clearLayers();
  let gezeichnet = 0;
  for (const z of daten.zellen) {
    /* Niemand wohnt im Umfeld — dann trifft keine der Kennzahlen eine Aussage. */
    if (!z.einwohner_umfeld) continue;
    const latlngs = z.ring.map((pt) => [pt[1], pt[0]]);
    const mitte = [
      latlngs.reduce((s, x) => s + x[0], 0) / latlngs.length,
      latlngs.reduce((s, x) => s + x[1], 0) / latlngs.length,
    ];
    const poly = L.polygon(latlngs, {
      renderer: state.scanRenderer,
      color: '#ffffff', weight: 0.4,
      fillColor: scanFarbe(z, metrik),
      fillOpacity: 0.55 * state.deckkraft, opacity: 0.5 * state.deckkraft,
      _basisDeckkraft: 0.55, _basisRand: 0.5,
    });
    poly.bindPopup(() => scanPopup(z, mitte), { maxWidth: 300 });
    gruppe.addLayer(poly);
    gezeichnet += 1;
  }
  /* Gestrichelter Rahmen: das ist die gescannte Fläche — wichtig, wenn der
     Kartenausschnitt größer ist als das Scanfenster. */
  const [w, s, o, n] = daten.kachel;
  gruppe.addLayer(L.rectangle([[s, w], [n, o]], {
    color: '#2f712c', weight: 1.2, dashArray: '5 5', fill: false, opacity: 0.8,
  }));
  scanState.status = { zellen: gezeichnet, betriebe: daten.betriebe_gesamt };
  zeigeScanLegende(scanState.status);
}

/* Nach dem Schwenken wird NICHT automatisch neu gescannt — jeder Scan ist
   eine echte Overpass-Abfrage. Stattdessen bietet die Legende den Knopf an. */
function scanNachBewegung() {
  if (!karte.hasLayer(state.ebenen.scan) || scanState.laedt) return;
  if (karte.getZoom() < 13) { ladeScan(); return; }
  if (!scanState.status) { ladeScan(); return; }
  const box = scanBox();
  if (!box) return;
  const schluessel = `${box.west.toFixed(3)}|${box.sued.toFixed(3)}|${box.ost.toFixed(3)}|${box.nord.toFixed(3)}`;
  if (schluessel !== scanState.schluessel) {
    zeigeScanLegende({ ...scanState.status, veraltet: true });
  }
}

karte.on('moveend', () => scanNachBewegung());
karte.on('overlayadd', (ev) => {
  if (ev.layer === state.ebenen.scan) {
    scanLegende.addTo(karte);
    scanState.schluessel = null;
    scanState.status = null;
    ladeScan();
  }
});
karte.on('overlayremove', (ev) => {
  if (ev.layer === state.ebenen.scan) {
    state.ebenen.scan.clearLayers();
    scanState.schluessel = null;
    scanState.status = null;
    scanLegende.remove();
  }
});

/* ------------------------------------------- Gemerkte Punkte als Ebene */

/* Überschneidungen der Einzugsgebiete: Luftliniendistanz kleiner als die
   Summe der Radien. Reine Geometrie — ob die Überschneidung schlimm ist,
   hängt vom Konzept ab; der Hinweis sagt nur, DASS sie da ist. */
function ueberlappungen(zeilen) {
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

async function ladePunkteEbene() {
  if (!karte.hasLayer(state.ebenen.punkte)) return;
  const gruppe = state.ebenen.punkte;
  gruppe.clearLayers();
  let punkte = [];
  try {
    punkte = (await (await fetch('/api/points')).json()).punkte || [];
  } catch { return; }
  for (const p of punkte) {
    const kreis = L.circle([p.lat, p.lon], {
      radius: p.radius, color: '#7a4b8f', weight: 1.4, dashArray: '4 4',
      fillColor: '#9a6cb1', fillOpacity: 0.07,
    });
    const marker = L.circleMarker([p.lat, p.lon], {
      radius: 7, color: '#5a2f73', weight: 2, fillColor: '#9a6cb1', fillOpacity: 0.95,
    });
    marker.bindTooltip(p.label, { permanent: true, direction: 'top', offset: [0, -8],
      className: 'punkt-etikett' });
    marker.bindPopup(() => el('div', {},
      el('h4', {}, p.label),
      el('p', { class: 'hinweis-klein' },
        `Radius ${NF.format(p.radius)} m`
        + (p.bewertung ? ` · eigene Note ${p.bewertung}` : '')
        + (p.notiz ? ` · ${p.notiz}` : '')),
      el('button', {
        style: 'margin-right:6px',
        onclick: () => { karte.closePopup(); setzePunkt(p.lat, p.lon, true); },
      }, 'Punkt laden'),
      el('a', { class: 'knopf-link', href: `/bericht?punkt=${p.id}`, target: '_blank',
        rel: 'noopener' }, 'Bericht')));
    gruppe.addLayer(kreis);
    gruppe.addLayer(marker);
  }
}

karte.on('overlayadd', (ev) => {
  if (ev.layer === state.ebenen.punkte) ladePunkteEbene();
});
karte.on('overlayremove', (ev) => {
  if (ev.layer === state.ebenen.punkte) state.ebenen.punkte.clearLayers();
});

karte.on('click', (e) => setzePunkt(e.latlng.lat, e.latlng.lng));

/* Choroplethen-Metriken: Feldname -> Beschriftung, Einheit, Nachkommastellen */
const METRIKEN = {
  Einwohner: { titel: 'Einwohner je Zelle', einheit: 'Personen', nk: 0 },
  anteil18bis49: { titel: 'Anteil 18–49 Jahre', einheit: '%', nk: 1, berechnet: true },
  durchschnMieteQM: { titel: 'Nettokaltmiete', einheit: '€/m²', nk: 2 },
  Leerstandsquote: { titel: 'Leerstandsquote', einheit: '%', nk: 1 },
};

const FARBEN = ['#f2f7fb', '#cfe0ee', '#9dc3dd', '#649dc7', '#3576ab', '#164e77'];

function metrikWert(zelle, metrik) {
  if (metrik === 'anteil18bis49') {
    const ew = zelle.Einwohner;
    if (!ew) return null;
    const a = (zelle.a18bis29 ?? 0) + (zelle.a30bis49 ?? 0);
    return (a / ew) * 100;
  }
  const v = zelle[metrik];
  return v === null || v === undefined ? null : Number(v);
}

/** Klassengrenzen aus den tatsächlichen Werten (Quantile), nicht aus Annahmen. */
function grenzen(werte) {
  const s = [...werte].sort((a, b) => a - b);
  if (!s.length) return [];
  const g = [];
  for (let i = 1; i < FARBEN.length; i++) {
    g.push(s[Math.floor((i / FARBEN.length) * s.length)]);
  }
  return g;
}

function farbe(v, g) {
  if (v === null) return '#cccccc';
  let i = 0;
  while (i < g.length && v >= g[i]) i++;
  return FARBEN[i];
}

function zeichneZensus(zellen) {
  const gruppe = state.ebenen.zensus;
  gruppe.clearLayers();
  if (!zellen || !zellen.length) { zeigeLegende(null); return; }

  const m = METRIKEN[state.choroMetrik];
  const werte = zellen.map((z) => metrikWert(z, state.choroMetrik)).filter((v) => v !== null);
  const g = grenzen(werte);

  for (const z of zellen) {
    if (!z._ring) continue;
    const v = metrikWert(z, state.choroMetrik);
    const latlngs = z._ring.map((p) => [p[1], p[0]]);
    const basis = v === null ? 0.25 : 0.62;
    const poly = L.polygon(latlngs, {
      color: '#ffffff', weight: 0.6, fillColor: farbe(v, g),
      fillOpacity: basis * state.deckkraft, opacity: state.deckkraft,
      // Ausgangswerte merken, damit der Regler mehrfach greifen kann, ohne
      // sich selbst zu multiplizieren.
      _basisDeckkraft: basis, _basisRand: 1,
    });
    poly.bindPopup(() => zellenPopup(z), { maxWidth: 320 });
    gruppe.addLayer(poly);
  }
  zeigeLegende({ metrik: m, grenzen: g, werte });
}

/** Jede Zelle zeigt auf Klick ihre Rohwerte — Spec §5. */
function zellenPopup(z) {
  const zeilen = Object.entries(z)
    .filter(([k]) => !k.startsWith('_'))
    .map(([k, v]) => `<tr><td>${esc(k)}</td><td><b>${v === null ? 'keine Angabe' : esc(v)}</b></td></tr>`)
    .join('');
  return `<h4>Zensuszelle ${esc(z.GITTER_ID_100m || '')}</h4>
    <span class="rohwerte"><table>${zeilen}</table></span>
    <p class="hinweis-klein">Rohwerte, 100-m-Gitter, Stichtag 15.05.2022.
    Über den Werten liegt eine stochastische Überlagerung (Cell-Key-Methode).</p>`;
}

function zeigeLegende(cfg) {
  const box = document.getElementById('legende');
  if (!cfg || !cfg.werte.length) { box.hidden = true; return; }
  const { metrik, grenzen: g, werte } = cfg;
  const nk = metrik.nk;
  box.hidden = false;
  box.replaceChildren();

  const wahl = el('select', {
    onchange: (e) => { state.choroMetrik = e.target.value; zeichneZensus(state.daten.zensus?.data?.zellen); },
    style: 'width:100%;margin-bottom:6px;font-size:12px;padding:3px;',
  });
  for (const [key, m] of Object.entries(METRIKEN)) {
    wahl.append(el('option', { value: key, selected: key === state.choroMetrik }, m.titel));
  }
  box.append(el('h3', {}, 'Zensus-Ebene'), wahl);

  const skala = el('div', { class: 'skala' });
  for (const f of FARBEN) skala.append(el('span', { style: `background:${f}` }));
  box.append(skala);

  const min = Math.min(...werte), max = Math.max(...werte);
  box.append(el('div', { class: 'achse' },
    el('span', {}, zahl(min, nk)), el('span', {}, zahl(max, nk))));
  box.append(el('div', { class: 'einheit' },
    `Einheit: ${metrik.einheit} · ${werte.length} Zellen mit Wert · Klassen nach Quantilen`));
  if (g.length) {
    box.append(el('div', { class: 'einheit' }, `Grenzen: ${g.map((x) => zahl(x, nk)).join(' · ')}`));
  }
}

const POI_STIL = {
  gastronomie: { color: '#a32020', fill: '#d94b4b' },
  frequenzbringer: { color: '#1f5f8b', fill: '#4a8fbd' },
  oepnv: { color: '#2b6a3f', fill: '#4f9c68' },
  leerstand: { color: '#8a5a00', fill: '#c9922a' },
  overture: { color: '#4a2b8a', fill: '#8a6fd1' },
  maerkte: { color: '#0e6e6d', fill: '#2fa39d' },
  baustellen: { color: '#b34700', fill: '#e07b39' },
  airbnb: { color: '#8a1c52', fill: '#c2185b' },
};

/* Klick in einer Objektliste: Karte springt zum Objekt, blendet die passende
   Ebene ein und öffnet dessen Popup; zusätzlich ein kurzlebiger Ring, damit
   das Auge den Pin sofort findet. */
let sprungRing = null;
function springeZuPoi(p, ebene) {
  const gruppe = state.ebenen[ebene];
  if (gruppe && !karte.hasLayer(gruppe)) gruppe.addTo(karte);
  karte.setView([p.lat, p.lon], Math.max(karte.getZoom(), 18));
  if (sprungRing) { karte.removeLayer(sprungRing); sprungRing = null; }
  sprungRing = L.circleMarker([p.lat, p.lon], {
    radius: 16, color: '#c62828', weight: 3, fill: false, interactive: false,
  }).addTo(karte);
  setTimeout(() => {
    if (sprungRing) { karte.removeLayer(sprungRing); sprungRing = null; }
  }, 4000);
  // Das zugehörige Popup öffnen, wenn der Marker gezeichnet ist.
  gruppe?.eachLayer((m) => {
    const ll = m.getLatLng?.();
    if (ll && Math.abs(ll.lat - p.lat) < 1e-6 && Math.abs(ll.lng - p.lon) < 1e-6) {
      m.openPopup();
    }
  });
}

function zeichnePois(name, liste) {
  const gruppe = state.ebenen[name];
  gruppe.clearLayers();
  const stil = POI_STIL[name];
  for (const p of liste || []) {
    const m = L.circleMarker([p.lat, p.lon], {
      radius: 5, color: stil.color, weight: 1.5, fillColor: stil.fill,
      fillOpacity: 0.85 * state.deckkraft, opacity: state.deckkraft,
      _basisDeckkraft: 0.85, _basisRand: 1,
    });
    m.bindPopup(() => poiPopup(p, name), { maxWidth: 320 });
    gruppe.addLayer(m);
  }
}

function poiPopup(p, name) {
  const zeilen = [];
  const feld = (k, v) => { if (v !== null && v !== undefined && v !== '') zeilen.push(`<tr><td>${esc(k)}</td><td><b>${esc(v)}</b></td></tr>`); };
  feld('Typ', p.typ_label || p.art || name);
  feld('Küche', p.cuisine);
  feld('Marke', p.marke);
  feld('Netz', p.netz);
  feld('Früher', p.frueher);
  feld('Adresse', p.adresse);
  feld('Verlässlichkeit', p.confidence !== undefined ? NF2.format(p.confidence) : null);
  feld('Datenquellen', p.quellen);
  feld('Entfernung', `${NF.format(p.distanz_m)} m ${p.richtung}`);
  for (const [k, v] of Object.entries(p.tags || {})) feld(k, v);
  return `<h4>${esc(p.name || '(ohne Name)')}</h4><table>${zeilen.join('')}</table>
    ${p.distanz_hinweis ? `<p class="hinweis-klein">${esc(p.distanz_hinweis)}</p>` : ''}
    ${p.osm_url ? `<p class="hinweis-klein"><a href="${esc(p.osm_url)}" target="_blank" rel="noopener">In OpenStreetMap ansehen</a>
    — dort steht der Rohdatensatz.</p>` : ''}`;
}

/* -------------------------------------------------------------- Punkt */

function setzePunkt(lat, lon, zoomen = false) {
  state.lat = Number(lat.toFixed(6));
  state.lon = Number(lon.toFixed(6));

  if (!state.marker) {
    state.marker = L.marker([lat, lon], { draggable: true }).addTo(karte);
    state.marker.on('dragend', (e) => {
      const p = e.target.getLatLng();
      setzePunkt(p.lat, p.lng);
    });
  } else {
    state.marker.setLatLng([lat, lon]);
  }

  if (!state.kreis) {
    state.kreis = L.circle([lat, lon], {
      radius: state.radius, color: '#1f5f8b', weight: 1.5, fillOpacity: 0.05,
    }).addTo(karte);
  } else {
    state.kreis.setLatLng([lat, lon]).setRadius(state.radius);
  }

  if (zoomen || karte.getZoom() < 13) karte.setView([lat, lon], 15);
  lade();
}

async function hole(pfad, params) {
  const url = new URL(pfad, window.location.origin);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  const r = await fetch(url);
  if (!r.ok) {
    let detail = `HTTP ${r.status}`;
    try { const j = await r.json(); detail = j.detail || j.fehler || detail; } catch { /* egal */ }
    throw new Error(detail);
  }
  return r.json();
}

function lade(refresh = false) {
  const lauf = ++state.ladeLauf;
  const { lat, lon, radius } = state;
  const p = { lat, lon, r: radius };
  if (refresh) p.refresh = 'true';

  document.getElementById('start-hinweis')?.remove();
  baueGeruest();
  state.daten = {};
  // Markensuche gehört zum vorigen Punkt — beim Wechsel weg damit. Die
  // Overture-Pins ebenso: sonst behaupten alte Pins etwas über den neuen Punkt.
  state.ebenen.marke?.clearLayers();
  state.ebenen.overture?.clearLayers();
  state.ebenen.maerkte?.clearLayers();
  state.ebenen.baustellen?.clearLayers();
  state.ebenen.airbnb?.clearLayers();
  // Die POI- und Zensus-Ebenen werden sonst erst beim Zeichnen der neuen
  // Antwort geleert — scheitert Overpass oder der Zensus, blieben die Marker
  // und das Gitter des vorigen Punktes auf der Karte liegen.
  for (const name of ['gastronomie', 'frequenzbringer', 'oepnv', 'leerstand',
    'zensus']) {
    state.ebenen[name]?.clearLayers();
  }
  // Der Schätzungsreiter hängt an den Punktdaten. Ist er gerade offen, muss er
  // mitwandern statt die Werte des vorigen Punktes stehen zu lassen.
  if (!document.getElementById('panel-schaetzung').hidden) {
    schaetzState.fuerPunkt = null;
    zeigeSchaetzung();
  }

  const aktuell = () => lauf === state.ladeLauf;

  // Jede Quelle einzeln — Ausfall der einen hält die andere nicht auf.
  hole('/api/point/adresse', { lat, lon, ...(refresh ? { refresh: 'true' } : {}) })
    .then((d) => {
      if (aktuell()) {
        state.daten.adresse = d; zeigeKopf(); ladeLinks();
        ladeRegister(d.data?.plz, lauf);
      }
    })
    .catch((e) => {
      if (!aktuell()) return;
      state.daten.adresse = { ok: false, error: { message: e.message } };
      // Ohne Adresse gibt es keine PLZ — der Registerblock sagt das selbst.
      ladeRegister(null, lauf);
      zeigeKopf();
    });

  hole('/api/point/zensus', p)
    .then((d) => {
      if (aktuell()) {
        state.daten.zensus = d; zeigeZensus(d); zeigeKopf(); ladeLinks();
        ladeEinkommen(d.data?.ags, lauf);
        ladeKreisprofil(d.data?.ags, lauf);
        ladePendler(d.data?.ags, lauf);
        ladeLaerm(d.data?.bundesland_code, lauf);
        ladeGenesis(d.data?.ags, lauf);
        ladePks(d.data?.ags, lauf);
        ladeWahl(d.data?.ags, lauf);
        ladeKalender(d.data?.ags, lauf);
      }
    })
    .catch((e) => {
      if (!aktuell()) return;
      zeigeBlockFehler('bevoelkerung', e);
      zeigeBlockFehler('wohnen', e);
      // Auch im Fehlerfall vermerken: sonst wartet ladeLinks() ewig auf diesen
      // Block, und die weiterführenden Quellen samt Bodenrichtwerten blieben
      // dauerhaft im Ladezustand hängen.
      state.daten.zensus = { ok: false, error: { message: e.message } };
      zeigeKopf();
      ladeLinks();
      // Die Folgeblöcke hängen am Gemeindeschlüssel aus dieser Antwort. Ohne
      // den Aufruf hier blieben sie bei Zensus-Ausfall für immer auf „lädt …“.
      ladeEinkommen(null, lauf);
      ladeKreisprofil(null, lauf);
      ladePendler(null, lauf);
      ladeGenesis(null, lauf);
      ladePks(null, lauf);
      ladeWahl(null, lauf);
      ladeKalender(null, lauf);
      // Der Lärmblock braucht keinen Schlüssel — nur der Bundesland-Hinweis
      // entfällt, die Kartierung selbst lädt trotzdem.
      ladeLaerm(null, lauf);
    });

  hole('/api/point/osm', p)
    .then((d) => {
      if (aktuell()) {
        state.daten.osm = d; zeigeOsm(d);
        // Der Overture-Abgleich braucht die OSM-Gastronomie — deshalb danach.
        hole('/api/point/overture', { lat, lon, r: radius })
          .then((o) => { if (aktuell()) { state.daten.overture = o; zeigeOverture(o); } })
          .catch((e2) => aktuell() && zeigeBlockFehler('overture', e2));
      }
    })
    .catch((e) => {
      if (!aktuell()) return;
      for (const id of ['gastronomie', 'franchise', 'umfeld', 'verkehr', 'leerstand',
        'overture']) {
        zeigeBlockFehler(id, e);
      }
    });

  hole('/api/point/gtfs', p)
    .then((d) => { if (aktuell()) { state.daten.gtfs = d; zeigeGtfs(d); } })
    .catch((e) => aktuell() && zeigeBlockFehler('gtfs', e));

  hole('/api/point/radzaehlung', { lat, lon, r: radius })
    .then((d) => { if (aktuell()) { state.daten.radzaehlung = d; zeigeRadzaehlung(d); } })
    .catch((e) => aktuell() && zeigeBlockFehler('radzaehlung', e));

  hole('/api/point/verkehrsmenge', { lat, lon, r: radius })
    .then((d) => { if (aktuell()) { state.daten.verkehrsmenge = d; zeigeVerkehrsmenge(d); } })
    .catch((e) => aktuell() && zeigeBlockFehler('verkehrsmenge', e));

  hole('/api/point/planung', { lat, lon, r: radius })
    .then((d) => { if (aktuell()) { state.daten.planung = d; zeigePlanung(d); } })
    .catch((e) => aktuell() && zeigeBlockFehler('planung', e));

  hole('/api/point/klima', { lat, lon })
    .then((d) => { if (aktuell()) { state.daten.klima = d; zeigeKlima(d); } })
    .catch((e) => aktuell() && zeigeBlockFehler('klima', e));

  hole('/api/point/leerstandsmelder', p)
    .then((d) => { if (aktuell()) { state.daten.leerstandsmelder = d; zeigeLeerstandsmelder(d); } })
    .catch((e) => aktuell() && zeigeBlockFehler('leerstandsmelder', e));

  hole('/api/point/luft', { lat, lon, ...(refresh ? { refresh: 'true' } : {}) })
    .then((d) => { if (aktuell()) { state.daten.luft = d; zeigeLuft(d); } })
    .catch((e) => aktuell() && zeigeBlockFehler('luft', e));

  hole('/api/point/sonne', { lat, lon, ...(refresh ? { refresh: 'true' } : {}) })
    .then((d) => { if (aktuell()) { state.daten.sonne = d; zeigeSonne(d); } })
    .catch((e) => aktuell() && zeigeBlockFehler('sonne', e));

  hole('/api/point/frequenz', { lat, lon, ...(refresh ? { refresh: 'true' } : {}) })
    .then((d) => { if (aktuell()) { state.daten.frequenz = d; zeigeFrequenz(d); } })
    .catch((e) => aktuell() && zeigeBlockFehler('frequenz', e));

  hole('/api/point/baurecht', { lat, lon, ...(refresh ? { refresh: 'true' } : {}) })
    .then((d) => { if (aktuell()) { state.daten.baurecht = d; zeigeBaurecht(d); } })
    .catch((e) => aktuell() && zeigeBlockFehler('baurecht', e));

  hole('/api/point/dynamik', p)
    .then((d) => { if (aktuell()) { state.daten.dynamik = d; zeigeDynamik(d); } })
    .catch((e) => aktuell() && zeigeBlockFehler('dynamik', e));

  hole('/api/point/baustellen', p)
    .then((d) => { if (aktuell()) { state.daten.baustellen = d; zeigeBaustellen(d); } })
    .catch((e) => aktuell() && zeigeBlockFehler('baustellen', e));

  hole('/api/point/maerkte', p)
    .then((d) => { if (aktuell()) { state.daten.maerkte = d; zeigeMaerkte(d); } })
    .catch((e) => aktuell() && zeigeBlockFehler('maerkte', e));

  hole('/api/point/indikatoren', { lat, lon })
    .then((d) => { if (aktuell()) { state.daten.indikatoren = d; zeigeIndikatoren(d); } })
    .catch((e) => aktuell() && zeigeBlockFehler('indikatoren', e));

  hole('/api/point/airbnb', p)
    .then((d) => { if (aktuell()) { state.daten.airbnb = d; zeigeAirbnb(d); } })
    .catch((e) => aktuell() && zeigeBlockFehler('airbnb', e));

  hole('/api/point/messe', { lat, lon, ...(refresh ? { refresh: 'true' } : {}) })
    .then((d) => { if (aktuell()) { state.daten.messe = d; zeigeMesse(d); } })
    .catch((e) => aktuell() && zeigeBlockFehler('messe', e));

  hole('/api/point/tourismus', { lat, lon, ...(refresh ? { refresh: 'true' } : {}) })
    .then((d) => { if (aktuell()) { state.daten.tourismus = d; zeigeTourismus(d); } })
    .catch((e) => aktuell() && zeigeBlockFehler('tourismus', e));

  aktualisiereFuss();
}

let linksGeladen = false;
function ladeLinks() {
  // Braucht Gemeinde (Nominatim) und AGS/Bundesland (Zensus) — sobald beide da sind.
  if (linksGeladen || !state.daten.adresse || !state.daten.zensus) return;
  linksGeladen = true;
  const a = state.daten.adresse.data || {};
  const z = state.daten.zensus.data || {};
  hole('/api/point/links', {
    lat: state.lat, lon: state.lon, r: state.radius,
    gemeinde: a.gemeinde || '', plz: a.plz || '',
    ags: z.ags || '', bundesland_code: z.bundesland_code || '',
  }).then(zeigeLinks).catch((e) => zeigeBlockFehler('quellen', e));
}

function zeigeBlockFehler(id, err) {
  setStatus(id, 'fehler', 'nicht erreichbar');
  setInhalt(id, fehlerbox({ message: err.message || String(err) }));
}

function baueGeruest() {
  linksGeladen = false;
  document.getElementById('block-bodenrichtwert')?.remove();
  const panel = document.getElementById('panel');
  panel.replaceChildren(
    block('kopf', '1 · Standort'),
    block('score', '1b · Gesamt-Score (gewählte Anker, eigene Gewichte)'),
    block('bevoelkerung', '2 · Bevölkerung'),
    block('indikatoren', '2b · Viertel-Steckbrief (Stadtbezirk München)'),
    block('wohnen', '3 · Wohnen'),
    block('einkommen', '3b · Verfügbares Einkommen (Kreis)'),
    block('kreisprofil', '3c · Kreisprofil (Tourismus, Arbeit, Bevölkerung)'),
    block('pendler', '3d · Pendler (Gemeinde)'),
    block('genesis', '3e · Amtliche Gastro-Anker (Regionaldatenbank, Opt-in)'),
    block('tourismus', '3f · Tourismus-Saisonalität (München)'),
    block('pks', '3g · Sicherheitslage (Kriminalstatistik, Kreis)'),
    block('wahl', '3h · Wahlergebnis (Bundestagswahl 2025, Wahlkreis)'),
    block('gastronomie', '4 · Gastronomie'),
    block('gehweg', '4b · Erreichbarkeit zu Fuß'),
    block('liefergebiet', '4d · Rad-Liefergebiet'),
    block('franchise', '4c · Systemgastronomie & Marken'),
    block('dynamik', '4e · Gastro-Dynamik (OSM-Historie)'),
    block('overture', '4f · Wettbewerbs-Abgleich (Overture)'),
    block('ihkberlin', '4g · Gastro-Bestand der IHK (nur Berlin)'),
    block('umfeld', '5 · Umfeld'),
    block('klima', '5b · Klima für Außengastronomie (DWD)'),
    block('kalender', '5h · Feiertage und Schulferien (Kontext)'),
    block('maerkte', '5c · Städtische Märkte (München/Hamburg)'),
    block('airbnb', '5d · Kurzzeitvermietung (Inside Airbnb)'),
    block('messe', '5e · Messe-Kalender (Messe München)'),
    block('luft', '5f · Luftqualität (nächste Messstation)'),
    block('sonne', '5g · Sonne auf der Terrasse (Verschattung)'),
    block('verkehr', '6 · Verkehr'),
    block('gtfs', '6b · Abfahrten (GTFS)'),
    block('radzaehlung', '6c · Gemessene Radverkehrsfrequenz'),
    block('frequenz', '6i · Gemessene Passantenfrequenz (Tagesgang)'),
    block('verkehrsmenge', '6d · Verkehrsmenge (DTV)'),
    block('planung', '6e · Planungsrecht und Hochwasser'),
    block('baurecht', '6j · Baurecht am Punkt (BauNVO, Denkmal, Sanierung)'),
    block('laerm', '6f · Straßenlärm (EU-Umgebungslärmkartierung)'),
    block('baustellen', '6g · Baustellen (München/Hamburg/Berlin)'),
    block('oepnveinzug', '6h · ÖPNV-Einzugsgebiet (GTFS)'),
    block('leerstand', '7 · Leerstände'),
    block('leerstandsmelder', '7b · Leerstandsmelder (bürgerschaftlich gemeldet)'),
    block('register', '7c · Handelsregister-Umfeld (OffeneRegister, Stand 2019)'),
    block('quellen', '8 · Weiterführende Quellen'),
    block('grenzen', 'Bekannte Grenzen dieser Daten'),
  );
  setStatus('grenzen', 'ok', '');
  setInhalt('grenzen', el('ul', { class: 'liste' },
    GRENZEN.map((g) => el('li', {}, el('span', { class: 'haupt' }, g)))));
  zeigeGehwegAngebot();
  zeigeLieferAngebot();
  zeigeOepnvEinzugAngebot();
  zeigeIhkAngebot();
}

/* --- 6h ÖPNV-Einzugsgebiet: wie 4b/4d auf Anforderung — die Rechnung über
   den lokalen Fahrplan dauert etliche Sekunden (Runden-Router). */
function zeigeOepnvEinzugAngebot() {
  state.ebenen.oepnveinzug?.clearLayers();
  setStatus('oepnveinzug', 'ok', 'auf Anforderung');
  const minuten = el('select', { id: 'oepnv-minuten' },
    [15, 20, 30, 45].map((m) => {
      const o = el('option', { value: String(m) }, `${m} Minuten`);
      if (m === 30) o.selected = true;
      return o;
    }));
  setInhalt('oepnveinzug',
    el('p', { class: 'hinweis-klein' },
      'Wie weit trägt der ÖPNV? Der Runden-Router rechnet über den lokal '
      + 'importierten Fahrplan, welche Halte am Referenz-Dienstag ab 12:00 '
      + 'in der gewählten Zeit erreichbar sind (max. zwei Umstiege) — und '
      + 'näherungsweise, wie viele Menschen dort wohnen. Das ist das '
      + 'Einzugsgebiet für Gäste, die mit Bahn und Bus kommen.'),
    el('p', { class: 'hinweis-klein' },
      'Auf Anforderung, weil die Rechnung einige Sekunden dauert; das '
      + 'Ergebnis bleibt danach im Cache.'),
    el('div', {}, minuten, ' ',
      el('button', { id: 'btn-oepnv-einzug', onclick: ladeOepnvEinzug },
        'Einzugsgebiet berechnen')));
}

async function ladeOepnvEinzug() {
  const id = 'oepnveinzug';
  const lauf = state.ladeLauf;
  const minuten = Number(document.getElementById('oepnv-minuten')?.value || 30);
  setStatus(id, 'laedt', 'rechnet …');
  const knopf = document.getElementById('btn-oepnv-einzug');
  if (knopf) knopf.disabled = true;
  try {
    const d = await hole('/api/point/oepnv-einzug',
      { lat: state.lat, lon: state.lon, minuten });
    if (lauf !== state.ladeLauf) return;
    state.daten.oepnveinzug = d;
    zeigeOepnvEinzug(d, minuten);
  } catch (e) {
    if (lauf === state.ladeLauf) zeigeBlockFehler(id, e);
  } finally {
    if (knopf) knopf.disabled = false;
  }
}

function zeigeOepnvEinzug(d, minuten) {
  const id = 'oepnveinzug';
  state.ebenen.oepnveinzug.clearLayers();
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht berechenbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const z = d.data;
  if (!z) {
    setStatus(id, 'leer', 'kein Fahrplan importiert');
    setInhalt(id, ...warnungen(d.warnings || []),
      el('button', { id: 'btn-oepnv-einzug', onclick: zeigeOepnvEinzugAngebot },
        'zurück'));
    setQuelle(id, d.provenance);
    return;
  }
  setStatus(id, 'ok', `${NF.format((z.halte || []).length)} Halte`);

  // Halte auf die Karte, eingefärbt nach Fahrzeit-Dritteln.
  const farben = ['#1b7837', '#f5a623', '#c0392b'];
  const stufe = (m) => (m <= z.minuten / 3 ? 0 : m <= (2 * z.minuten) / 3 ? 1 : 2);
  for (const h of z.halte || []) {
    state.ebenen.oepnveinzug.addLayer(L.circleMarker([h.lat, h.lon], {
      radius: 4, color: farben[stufe(h.minuten)],
      fillColor: farben[stufe(h.minuten)],
      fillOpacity: 0.7 * state.deckkraft, opacity: state.deckkraft,
      weight: 1, _basisDeckkraft: 0.7, _basisRand: 1,
    }).bindTooltip(`${h.name} — ${h.minuten} min`));
  }
  if (!karte.hasLayer(state.ebenen.oepnveinzug)) {
    state.ebenen.oepnveinzug.addTo(karte);
  }

  const je = [0, 0, 0];
  for (const h of z.halte || []) je[stufe(h.minuten)] += 1;

  setInhalt(id,
    el('div', { class: 'kennzahlen' },
      kennzahl(`Erreichbare Halte (${z.minuten} min)`, (z.halte || []).length),
      kennzahl('Einwohner im Einzugsgebiet (Näherung)', z.einwohner_naeherung),
      kennzahl('Linien benutzt', z.linien),
      kennzahl('Fernster Halt (Luftlinie)', z.fernster_km, 'km', 1),
      kennzahl('Starthalte zu Fuß (≤ 600 m)', z.start_halte)),
    el('div', { class: 'notiz' },
      `Referenztag ${z.referenztag?.weekday_de || 'Dienstag'} `
      + `${z.referenztag?.date || ''}, Abfahrt ${z.abfahrt} Uhr. `
      + `Fahrzeit-Drittel: ${NF.format(je[0])} · ${NF.format(je[1])} · `
      + `${NF.format(je[2])} Halte (grün/gelb/rot auf der Karte).`),
    el('div', {},
      el('button', { id: 'btn-oepnv-einzug', onclick: zeigeOepnvEinzugAngebot },
        'neue Rechnung')),
    ...(z.hinweise || []).map((h) => hinweisZeile(h)),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* Der Gehwegblock lädt nicht von selbst: das Fußwegenetz ist mit 1–3 MB je Punkt
   die grösste Overpass-Antwort des Werkzeugs, und Overpass ist ein Spendendienst.
   Deshalb erst auf Knopfdruck — dafür bleibt das Ergebnis 14 Tage im Cache. */
function zeigeGehwegAngebot() {
  // Sonst bliebe die erreichbare Fläche des vorigen Punktes auf der Karte
  // liegen und behauptete etwas über den neuen.
  state.ebenen.gehflaeche?.clearLayers();
  setStatus('gehweg', 'ok', 'auf Anforderung');
  setInhalt('gehweg',
    el('p', { class: 'hinweis-klein' },
      'Der Umkreis ist ein Kreis auf der Karte — zu Fuß ist er das nicht. '
      + 'Flüsse, Gleise und Schnellstraßen zerschneiden ihn, und man kommt nur '
      + 'dort hinüber, wo eine Brücke steht. Diese Auswertung rechnet die '
      + 'tatsächliche Gehstrecke im OSM-Wegenetz.'),
    el('p', { class: 'hinweis-klein' },
      'Sie läuft nicht automatisch mit, weil das Wegenetz die größte Abfrage des '
      + 'Werkzeugs ist und Overpass ein Spendenprojekt. Das Ergebnis bleibt '
      + 'danach 14 Tage im Cache.'),
    el('button', { id: 'btn-gehweg', onclick: ladeGehweg }, 'Gehstrecken berechnen'));
}

/* --- 4d Rad-Liefergebiet: wie 4b nur auf Anforderung — das Radnetz für
   10 Minuten Fahrstrecke ist eine noch größere Overpass-Abfrage. */
function zeigeLieferAngebot() {
  state.ebenen.liefergebiet?.clearLayers();
  setStatus('liefergebiet', 'ok', 'auf Anforderung');
  const minuten = el('select', { id: 'liefer-minuten' },
    [5, 8, 10, 12, 15].map((m) => {
      const o = el('option', { value: String(m) }, `${m} Minuten`);
      if (m === 10) o.selected = true;
      return o;
    }));
  setInhalt('liefergebiet',
    el('p', { class: 'hinweis-klein' },
      'Für Lieferkonzepte ist nicht der Umkreis die Kernzahl, sondern: wie '
      + 'viele Menschen erreicht ein Lieferrad in der Lieferzeit? Gerechnet '
      + 'wird die kürzeste Strecke im OSM-Netz mit Radprofil und pauschal '
      + '15 km/h — ein gewählter Wert, kein gemessener.'),
    el('p', { class: 'hinweis-klein' },
      'Läuft nur auf Knopfdruck: das Wegenetz für 10 Minuten Rad ist eine '
      + 'große Overpass-Abfrage. Das Ergebnis bleibt 14 Tage im Cache.'),
    el('div', { class: 'pflegeleiste' },
      el('label', { for: 'liefer-minuten' }, 'Fahrzeit'),
      minuten,
      el('button', { id: 'btn-liefergebiet', onclick: ladeLiefergebiet },
        'Liefergebiet berechnen')));
}

function ladeLiefergebiet() {
  const lauf = state.ladeLauf;
  const { lat, lon } = state;
  const minuten = Number(document.getElementById('liefer-minuten')?.value || 10);
  setStatus('liefergebiet', 'laedt', 'lädt …');
  setInhalt('liefergebiet',
    el('div', { class: 'laden' }),
    el('p', { class: 'hinweis-klein' },
      'Wegenetz und Zensuszellen für das Liefergebiet werden geladen — der '
      + 'erste Abruf kann ein bis zwei Minuten dauern.'));
  hole('/api/point/liefergebiet', { lat, lon, minuten })
    .then((d) => {
      if (lauf !== state.ladeLauf) return;
      state.daten.liefergebiet = d;
      zeigeLiefergebiet(d);
    })
    .catch((e) => { if (lauf === state.ladeLauf) zeigeBlockFehler('liefergebiet', e); });
}

function zeigeLiefergebiet(d) {
  const id = 'liefergebiet';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error),
      el('button', { onclick: zeigeLieferAngebot }, 'Erneut versuchen'));
    setQuelle(id, d.provenance);
    return;
  }
  const g = d.data;
  if (!g) {
    setStatus(id, 'ok', 'ohne Ergebnis');
    setInhalt(id, ...warnungen(d.warnings || []),
      el('button', { onclick: zeigeLieferAngebot }, 'Erneut versuchen'));
    setQuelle(id, d.provenance);
    return;
  }
  setStatus(id, 'ok', 'geladen');
  zeichneLieferflaeche(g);

  const kz = el('div', { class: 'kennzahlen' },
    kennzahl(`Einwohner in ${g.minuten} min Radstrecke`, g.einwohner_liefergebiet),
    kennzahl('Fahrstrecke', g.radius_m, 'm'),
    kennzahl('Tempo (gewählt)', g.tempo_kmh, 'km/h', 1),
    kennzahl('Zensuszellen im Gebiet', g.zellen_im_liefergebiet));

  const netz = el('p', { class: 'hinweis-klein' },
    `Wegenetz: ${NF.format(g.knoten)} Knoten `
    + `(${NF.format(g.wege_gesperrt)} Wege als nicht befahrbar ausgeschlossen), `
    + `kürzeste Strecke je Knoten in ${g.rechenzeit_ms} ms berechnet. `
    + `Anbindung des Standorts: ${g.anbindung_m} m.`);

  setInhalt(id, kz, netz,
    el('button', { onclick: zeigeLieferAngebot }, 'andere Fahrzeit wählen'),
    ...(g.hinweise || []).map((h) => el('div', { class: 'notiz' }, h)),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

function zeichneLieferflaeche(g) {
  const gruppe = state.ebenen.liefergebiet;
  gruppe.clearLayers();
  const punkte = g?.flaeche || [];
  if (!punkte.length) return;
  const radius = g.radius_m || 1;
  for (const [lat, lon, meter] of punkte) {
    const anteil = meter / radius;
    const stufe = GEH_STUFEN.find((s) => anteil <= s.bis) || GEH_STUFEN[GEH_STUFEN.length - 1];
    const m = L.circleMarker([lat, lon], {
      renderer: state.gehwegRenderer,
      radius: 3,
      stroke: false,
      fillColor: stufe.farbe,
      fillOpacity: 0.45 * state.deckkraft,
      _basisDeckkraft: 0.45,
      _basisRand: 0,
    });
    m.bindPopup(() => `<h4>Mit dem Rad erreichbar</h4>
      <p>${NF.format(meter)} m Fahrstrecke
      (${NF1.format(meter / g.tempo_m_pro_min)} min bei ${g.tempo_kmh} km/h)</p>`);
    gruppe.addLayer(m);
  }
  if (!karte.hasLayer(gruppe)) gruppe.addTo(karte);
}

function ladeGehweg() {
  const lauf = state.ladeLauf;
  const { lat, lon, radius } = state;
  setStatus('gehweg', 'laedt', 'lädt …');
  setInhalt('gehweg',
    el('div', { class: 'laden' }),
    el('p', { class: 'hinweis-klein' },
      'Das Wegenetz umfasst je nach Lage 1–3 MB; der erste Abruf dauert '
      + 'typischerweise 10–70 Sekunden.'));
  hole('/api/point/gehweg', { lat, lon, r: radius })
    .then((d) => {
      if (lauf !== state.ladeLauf) return;
      state.daten.gehweg = d;
      zeigeGehweg(d);
      // Die Betriebsliste zeigt die Gehstrecke mit, sobald sie vorliegt.
      if (state.daten.osm?.ok) zeigeOsm(state.daten.osm);
    })
    .catch((e) => { if (lauf === state.ladeLauf) zeigeBlockFehler('gehweg', e); });
}

/* Wird beim Start vom Server geholt, damit die Texte nicht doppelt gepflegt werden. */
let GRENZEN = [];

/* ------------------------------------------------------------- Bloecke */

/* Die Kopfzeile führt zwei Quellen zusammen: Adresse und Ortsteil von Nominatim,
   Gemeindeschlüssel und Bundesland aus dem Zensus-Gitter (Nominatim liefert keinen
   AGS, Phase-0-Befund A-5). Beide treffen unabhängig ein, deshalb wird der Block
   bei jedem der beiden Ereignisse neu gezeichnet. */
function zeigeKopf() {
  const d = state.daten.adresse;
  const zRes = state.daten.zensus;
  if (!d && !zRes) return;

  const a = d?.data;
  const fertig = d && zRes;
  if (d && !d.ok && (!zRes || !zRes.ok)) {
    setStatus('kopf', 'fehler', 'nicht erreichbar');
    setInhalt('kopf', fehlerbox(d.error));
    setQuelle('kopf', d.provenance);
    return;
  }
  if (d && !d.ok) setStatus('kopf', 'leer', 'Adresse fehlt');
  else setStatus('kopf', fertig ? 'ok' : 'laedt', fertig ? 'geladen' : 'lädt …');
  const z = zRes?.data || {};
  const tab = el('table', { class: 'daten' });
  const zeile = (k, v) => tab.append(el('tr', {}, el('th', {}, k),
    el('td', {}, v ?? el('span', { class: 'hinweis-klein' }, 'keine Angabe'))));
  zeile('Adresse', a?.display_name);
  zeile('Gemeinde', a?.gemeinde);
  zeile('Ortsteil', a?.ortsteil);
  zeile('PLZ', a?.plz);
  zeile('Gemeindeschlüssel (AGS)', z.ags ? `${z.ags} (${z.ags_quelle})` : null);
  zeile('Bundesland', z.bundesland || a?.bundesland);
  zeile('Koordinaten', `${state.lat}, ${state.lon} · Radius ${state.radius} m`);

  const knoepfe = el('div', { style: 'margin-top:10px;display:flex;gap:6px;flex-wrap:wrap;' },
    el('a', {
      class: 'knopf-link',
      href: `/api/export/point.json?lat=${state.lat}&lon=${state.lon}&r=${state.radius}`,
    }, 'Export JSON'),
    el('a', {
      class: 'knopf-link',
      href: `/api/export/point.csv?lat=${state.lat}&lon=${state.lon}&r=${state.radius}`,
    }, 'Export CSV'),
    el('a', {
      class: 'knopf-link', target: '_blank', rel: 'noopener',
      href: `https://www.openstreetmap.org/#map=17/${state.lat}/${state.lon}`,
    }, 'In OSM öffnen'));

  setInhalt('kopf', tab, ...warnungen(d?.warnings || []),
    d && !d.ok ? fehlerbox(d.error) : null, knoepfe);
  setQuelle('kopf', d?.provenance);
}

function zeigeZensus(d) {
  for (const id of ['bevoelkerung', 'wohnen']) {
    setStatus(id, d.ok ? 'ok' : 'fehler', d.ok ? 'geladen' : 'nicht erreichbar');
  }
  if (!d.ok) {
    setInhalt('bevoelkerung', fehlerbox(d.error));
    setInhalt('wohnen', fehlerbox(d.error));
    return;
  }
  const z = d.data;
  zeichneZensus(z.zellen);

  if (!z.zellen_gefunden) {
    for (const id of ['bevoelkerung', 'wohnen']) {
      setStatus(id, 'leer', 'keine Zellen');
      setInhalt(id, el('div', { class: 'warnung' },
        'Keine Zensuszelle im Umkreis. Im Zensus 2022 fehlen unbewohnte Zellen '
        + 'vollständig — das ist eine Aussage über die Lage, kein Datenfehler.'),
        ...warnungen(d.warnings));
      setQuelle(id, d.provenance);
    }
    return;
  }

  const b = z.bevoelkerung;
  const kz = el('div', { class: 'kennzahlen' },
    kennzahl('Einwohner im Umkreis', b.einwohner),
    kennzahl('Durchschnittsalter', b.durchschnittsalter, 'J.', 1),
    kennzahl('Haushaltsgröße', b.haushaltsgroesse, 'Pers.', 2),
    kennzahl('Ausländeranteil', b.anteil_auslaender, '%', 1));

  const ew = b.einwohner?.wert || 0;
  const tab = el('table', { class: 'daten' },
    el('tr', {}, el('th', {}, 'Altersgruppe'), el('th', { class: 'num' }, 'Personen'),
      el('th', { class: 'num' }, 'Anteil')));
  for (const [label, agg] of Object.entries(b.altersgruppen)) {
    const v = agg?.wert;
    tab.append(el('tr', {},
      el('td', {}, label),
      el('td', { class: 'num' }, zahl(v) ?? '—'),
      el('td', { class: 'num' }, ew && v !== undefined && v !== null ? `${NF1.format((v / ew) * 100)} %` : '—')));
  }

  setInhalt('bevoelkerung', kz, tab, kundenprofilSatz(b, ew),
    ...(z.hinweise || []).map((h) => el('div', { class: 'notiz' }, h)),
    ...warnungen(d.warnings));
  setQuelle('bevoelkerung', d.provenance);

  const w = z.wohnen;
  const kzw = el('div', { class: 'kennzahlen' },
    kennzahl('Nettokaltmiete', w.miete_qm, '€/m²', 2),
    kennzahl('Eigentümerquote', w.eigentuemerquote, '%', 1),
    kennzahl('Leerstandsquote', w.leerstandsquote, '%', 1),
    kennzahl('Fläche je Wohnung', w.flaeche_je_wohnung, 'm²', 1));

  const bau = el('table', { class: 'daten' },
    el('tr', {}, el('th', {}, 'Baualtersklasse'), el('th', { class: 'num' }, 'Gebäude')));
  const gesamt = w.gebaeude?.wert || 0;
  for (const [label, agg] of Object.entries(w.baualter)) {
    bau.append(el('tr', {}, el('td', {}, label),
      el('td', { class: 'num' }, zahl(agg?.wert) ?? '—')));
  }
  if (gesamt) {
    bau.append(el('tr', {}, el('th', {}, 'Gebäude gesamt'),
      el('th', { class: 'num' }, zahl(gesamt))));
  }

  setInhalt('wohnen', kzw, bau, ...warnungen(d.warnings));
  setQuelle('wohnen', d.provenance);
  // Falls der Gastronomie-Block schon steht: Versorgungsgrad nachfüllen.
  fuelleVersorgungsgrad(null);
}

/* Snack-Verkauf: Ladengeschäfte (Bäckerei, Confiserie, Kaffeeausschank …),
   die um denselben Snack-Euro konkurrieren. Bewusst getrennt von der
   Gastro-Gesamtzahl — es sind Läden, keine Restaurants. */
function snackBereich(o, z) {
  const sn = z.snack_verkauf;
  if (!sn || !sn.gesamt) return [];
  const arten = Object.entries(sn.nach_art || {})
    .map(([art, n]) => `${art}: ${NF.format(n)}`).join(' · ');
  return [
    el('h3', { class: 'hinweis-klein' }, 'Snack-Verkauf (Ladengeschäfte)'),
    el('div', { class: 'kennzahlen', id: 'snack-verkauf' },
      kennzahl('Läden mit Snack-Angebot', sn.gesamt)),
    el('div', { class: 'hinweis-klein' },
      `${arten}. Konkurrieren um denselben Snack-Euro, zählen aber nicht in `
      + 'der Gastro-Gesamtzahl oben — es sind Ladengeschäfte. Bäckereien und '
      + 'Konditoreien stehen zusätzlich bei den Frequenzbringern.'),
  ];
}

/* Öffnungszeiten-Lücken: Sonntags- und Abendangebot des Umfelds — als
   Mindestzahlen, denn nur einfache Wochentag-Uhrzeit-Regeln werden bewertet.
   Eine Lücke kann eine Chance sein (niemand versorgt den Sonntag) oder ein
   Warnzeichen (der Sonntag lohnt hier für niemanden) — das entscheidet der
   Blick vor Ort, nicht das Werkzeug. */
function oeffnungsluecken(oz) {
  if (!oz || !oz.gesamt) return [];
  const teile = [
    el('h3', { class: 'hinweis-klein' }, 'Öffnungszeiten-Lücken (Mindestzahlen)'),
    el('div', { class: 'kennzahlen', id: 'oeffnungsluecken' },
      kennzahl('Sonntags geöffnet', { wert: oz.sonntag_offen }, `von ${oz.auswertbar} auswertbaren`),
      kennzahl('Sonntags zu', { wert: oz.sonntag_geschlossen }, `von ${oz.auswertbar} auswertbaren`),
      kennzahl(`Abends nach ${oz.nacht_ab} Uhr geöffnet`, { wert: oz.nach22_offen },
        `von ${oz.auswertbar} auswertbaren`),
      kennzahl('Angabe in OSM', { wert: oz.mit_angabe }, `von ${oz.gesamt} Betrieben`)),
    el('div', { class: 'hinweis-klein' },
      `${NF.format(oz.auswertbar)} von ${NF.format(oz.mit_angabe)} Angaben bestehen `
      + 'aus einfachen Wochentag-Uhrzeit-Regeln und wurden bewertet. '
      + oz.hinweis),
  ];
  return teile;
}

/* Kundenprofil: ein zusammenfassender Satz aus den angezeigten Zahlen —
   rein deskriptiv (größte Altersgruppe, Alter, Haushaltsgröße), ohne
   gewählte Schwellen und ohne Bewertung. Wer hier wohnt, ist nicht
   automatisch, wer hier isst — Einpendler und Passanten fehlen. */
function kundenprofilSatz(b, ew) {
  if (!ew) return null;
  let groesste = null;
  for (const [label, agg] of Object.entries(b.altersgruppen || {})) {
    const v = agg?.wert;
    if (typeof v === 'number' && (!groesste || v > groesste.wert)) {
      groesste = { label, wert: v };
    }
  }
  if (!groesste) return null;
  const teile = [
    `Größte Altersgruppe im Umkreis: ${groesste.label} `
    + `(${NF1.format((groesste.wert / ew) * 100)} % der Einwohner)`,
  ];
  const alter = b.durchschnittsalter?.wert;
  if (typeof alter === 'number') teile.push(`Durchschnittsalter ${NF1.format(alter)} Jahre`);
  const hh = b.haushaltsgroesse?.wert;
  if (typeof hh === 'number') teile.push(`Ø Haushalt ${NF2.format(hh)} Personen`);
  return el('div', { class: 'notiz', id: 'kundenprofil' },
    el('b', {}, 'Kundenprofil der Wohnbevölkerung: '), `${teile.join(' · ')}. `,
    'Rein deskriptiv aus den Zahlen oben — wer hier wohnt, ist nicht '
    + 'automatisch, wer hier einkehrt: Einpendler, Touristen und Passanten '
    + 'stehen nicht im Zensus-Gitter.');
}

function liste(eintraege, zeigeAnfangs = 12, zeichner) {
  const ul = el('ul', { class: 'liste' });
  const zeichne = (n) => {
    ul.replaceChildren(...eintraege.slice(0, n).map(zeichner));
    if (n < eintraege.length) {
      ul.append(el('li', {}, el('button', {
        class: 'mehr', onclick: () => zeichne(eintraege.length),
      }, `alle ${eintraege.length} anzeigen`)));
    }
  };
  zeichne(zeigeAnfangs);
  return ul;
}

/* ------------------------------------------------- Branchenprofile
   Für einen Imbiss sind 30 Cafés kein Wettbewerb. Ein Profil legt fest,
   welche OSM-Typen (amenity) als direkter Wettbewerb zählen — mehr nicht:
   es filtert vorhandene Daten, es lädt nichts nach und wertet nichts um.
   Grundlage ist bewusst nur der amenity-Typ; das cuisine-Feld ist Freitext
   und bleibt, wie überall im Werkzeug, unangetastet stehen. */
const BRANCHEN = [
  { key: 'alle', label: 'alle Gastronomie', typen: null },
  { key: 'schnellrestaurant', label: 'Schnellrestaurant / Imbiss',
    typen: ['fast_food', 'food_court'] },
  { key: 'restaurant', label: 'Restaurant', typen: ['restaurant'] },
  { key: 'cafe', label: 'Café', typen: ['cafe'] },
  { key: 'bar', label: 'Bar / Kneipe / Abendlokal',
    typen: ['bar', 'pub', 'biergarten', 'nightclub'] },
  { key: 'eisdiele', label: 'Eisdiele', typen: ['ice_cream'] },
];
const BRANCHE_SPEICHER = 'gastroviewer.branche';

function brancheKennzahlen(gastro, typen) {
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

function brancheBereich(o) {
  const inhalt = el('div', {});
  const zeichne = (key) => {
    const b = BRANCHEN.find((x) => x.key === key) || BRANCHEN[0];
    const k = brancheKennzahlen(o.gastronomie || [], b.typen);
    // .filter(Boolean): replaceChildren rendert null als sichtbaren Text.
    inhalt.replaceChildren(...[
      el('div', { class: 'kennzahlen' },
        kennzahl('Direkter Wettbewerb', k.anzahl),
        kennzahl('davon bis 300 m', k.bis300),
        kennzahl('nächster (m)', k.naechster),
        kennzahl('davon Ketten', k.ketten),
        kennzahl('je 1.000 Einwohner (berechnet)', k.je1000, '', 1)),
      b.typen ? el('div', { class: 'hinweis-klein' },
        `Gezählt werden die OSM-Typen: ${b.typen.join(', ')}. `
        + 'Das cuisine-Feld ist Freitext und wird nicht ausgewertet — ein '
        + 'Burger-Restaurant mit amenity=restaurant zählt hier nicht als '
        + 'Schnellrestaurant.') : null,
    ].filter(Boolean));
  };
  const auswahl = el('select', { onchange: (ev) => {
    localStorage.setItem(BRANCHE_SPEICHER, ev.target.value);
    zeichne(ev.target.value);
  } }, BRANCHEN.map((b) => {
    const opt = el('option', { value: b.key }, b.label);
    if (b.key === (localStorage.getItem(BRANCHE_SPEICHER) || 'alle')) opt.selected = true;
    return opt;
  }));
  zeichne(localStorage.getItem(BRANCHE_SPEICHER) || 'alle');
  return el('div', { class: 'branche' },
    el('h3', { class: 'hinweis-klein' }, 'Branchenprofil — was zählt als direkter Wettbewerb?'),
    auswahl,
    inhalt);
}

/* Versorgungsgrad: Betriebe je 1.000 Einwohner im Umkreis — berechnet aus
   zwei schon geladenen Blöcken (OSM-Betriebe, Zensus-Einwohner). Anker ist
   die amtlich zitierte DEHOGA-Schwelle: weniger als ein Betrieb je 1.000
   Einwohner gilt als „gastronomische Unterversorgung". Lädt der Zensus
   nach der Gastronomie, füllt zeigeZensus den Platzhalter nach. */
function versorgungsgrad() {
  const wrap = el('div', { id: 'gastro-versorgung' });
  fuelleVersorgungsgrad(wrap);
  return wrap;
}

function fuelleVersorgungsgrad(ziel) {
  const wrap = ziel || document.getElementById('gastro-versorgung');
  if (!wrap) return;
  const betriebe = state.daten.osm?.data?.zusammenfassung?.gastronomie?.gesamt;
  // Zensuswerte kommen als {wert, zellen, …} — es zählt der Wert.
  const einwohner = state.daten.zensus?.data?.bevoelkerung?.einwohner?.wert;
  if (betriebe === undefined || !einwohner) {
    wrap.replaceChildren();
    return;
  }
  const je1000 = betriebe / einwohner * 1000;
  const unterversorgt = je1000 < 1;
  wrap.replaceChildren(el('div', { class: unterversorgt ? 'notiz' : 'hinweis-klein' },
    el('b', {}, `Versorgungsgrad: ${NF1.format(je1000)} Betriebe je 1.000 Einwohner `),
    `im Umkreis (berechnet: ${NF.format(betriebe)} OSM-Betriebe ÷ `
    + `${NF.format(einwohner)} Zensus-Einwohner). `
    + (unterversorgt
      ? 'Unter der Schwelle von 1 je 1.000 — nach der in der amtlichen '
        + 'Statistik zitierten DEHOGA-Definition eine „gastronomische '
        + 'Unterversorgung": wenig Wettbewerb, aber auch wenig gelernte '
        + 'Gastro-Lauflage.'
      : 'Über der Schwelle von 1 je 1.000, unterhalb derer die amtliche '
        + 'Statistik von „gastronomischer Unterversorgung" spricht. '
        + 'Wohnbevölkerung ohne Büros und Touristen — in Innenstadtlagen '
        + 'sagt die Zahl wenig, im Wohnviertel viel.')));
}

function zeigeOsm(d) {
  const ids = ['gastronomie', 'franchise', 'umfeld', 'verkehr', 'leerstand'];
  for (const id of ids) setStatus(id, d.ok ? 'ok' : 'fehler', d.ok ? 'geladen' : 'nicht erreichbar');
  if (!d.ok) {
    for (const id of ids) { setInhalt(id, fehlerbox(d.error)); setQuelle(id, d.provenance); }
    return;
  }
  const o = d.data;
  const z = o.zusammenfassung;
  zeichnePois('gastronomie', o.gastronomie);
  zeichnePois('frequenzbringer', o.frequenzbringer);
  zeichnePois('oepnv', o.oepnv);
  zeichnePois('leerstand', o.leerstand);
  zeigeFranchise(o, d);

  /* --- 4 Gastronomie --- */
  const g = z.gastronomie;
  const kzg = el('div', { class: 'kennzahlen' },
    kennzahl('Betriebe gesamt', g.gesamt),
    kennzahl('davon Schnellrestaurants', g.nach_typ['Schnellrestaurant'] ?? 0),
    kennzahl('Ketten', g.ketten),
    kennzahl('Einzelbetriebe', g.einzelbetriebe));

  const typTab = el('table', { class: 'daten' },
    el('tr', {}, el('th', {}, 'Typ'), el('th', { class: 'num' }, 'Anzahl')));
  for (const [k, v] of Object.entries(g.nach_typ)) {
    typTab.append(el('tr', {}, el('td', {}, k), el('td', { class: 'num' }, NF.format(v))));
  }

  /* Kumulierte Zahl je Entfernungsstufe — ein Betrieb in 50 m wiegt anders als
     einer am Rand des Umkreises, die reine Umkreiszahl verwischt das. */
  const stufen = g.nach_entfernung || [];
  const ffStufen = new Map((g.schnellrestaurants_nach_entfernung || [])
    .map((s) => [s.bis_m, s.anzahl]));
  const entfTab = el('table', { class: 'daten' },
    el('tr', {}, el('th', {}, 'im Umkreis von'), el('th', { class: 'num' }, 'Betriebe'),
      el('th', { class: 'num' }, 'davon Schnellrest.')));
  for (const s of stufen) {
    entfTab.append(el('tr', {},
      el('td', {}, `${NF.format(s.bis_m)} m`),
      el('td', { class: 'num' }, NF.format(s.anzahl)),
      el('td', { class: 'num' }, NF.format(ffStufen.get(s.bis_m) ?? 0))));
  }
  if (g.naechster_m !== null && g.naechster_m !== undefined) {
    entfTab.append(el('tr', {},
      el('td', {}, el('em', {}, 'nächster Betrieb')),
      el('td', { class: 'num', colspan: '2' }, `${NF.format(g.naechster_m)} m`)));
  }

  const kueche = Object.entries(g.nach_kueche).slice(0, 12);
  const kuecheTab = el('table', { class: 'daten' },
    el('tr', {}, el('th', {}, 'Küche (OSM-Tag)'), el('th', { class: 'num' }, 'Anzahl')));
  for (const [k, v] of kueche) {
    kuecheTab.append(el('tr', {}, el('td', {}, k), el('td', { class: 'num' }, NF.format(v))));
  }
  if (g.ohne_kuechenangabe) {
    kuecheTab.append(el('tr', {}, el('td', {}, el('em', {}, 'ohne Küchenangabe in OSM')),
      el('td', { class: 'num' }, NF.format(g.ohne_kuechenangabe))));
  }

  /* Ist der Gehwegblock geladen, steht neben der Luftlinie die Gehstrecke. */
  const gehStrecken = state.daten.gehweg?.data?.gehstrecke_je_id || {};
  const gListe = liste(o.gastronomie, 12, (p) => el('li', {},
    el('span', { class: 'dist' },
      `${NF.format(p.distanz_m)} m`,
      gehStrecken[String(p.id)] !== undefined
        ? el('div', { class: 'basis' }, `${NF.format(gehStrecken[String(p.id)])} m zu Fuß`)
        : null),
    el('span', { class: 'haupt' },
      el('div', { class: 'name' }, p.name || '(ohne Name)'),
      el('div', { class: 'meta' },
        [p.typ_label, p.cuisine, p.marke ? `Marke ${p.marke}` : null,
          p.tags?.opening_hours].filter(Boolean).join(' · ')),
      el('div', { class: 'merkmale' },
        ['takeaway', 'delivery', 'outdoor_seating', 'drive_through', 'wheelchair']
          .filter((t) => p.tags?.[t])
          .map((t) => el('span', {
            class: `merkmal ${['no', 'limited'].includes(p.tags[t]) ? 'aus' : ''}`,
          }, `${t}: ${p.tags[t]}`))))));

  setInhalt('gastronomie', kzg,
    versorgungsgrad(),
    brancheBereich(o),
    el('h3', { class: 'hinweis-klein' }, 'Nach Typ'), typTab,
    el('h3', { class: 'hinweis-klein' }, 'Wettbewerbsdichte nach Entfernung'), entfTab,
    el('h3', { class: 'hinweis-klein' }, 'Küchenverteilung'), kuecheTab,
    el('h3', { class: 'hinweis-klein' }, 'Betriebe nach Entfernung'), gListe,
    ...snackBereich(o, z),
    ...oeffnungsluecken(g.oeffnungszeiten),
    ...warnungen(d.warnings));
  setQuelle('gastronomie', d.provenance);

  /* --- 5 Umfeld --- */
  const nachKat = {};
  for (const f of o.frequenzbringer) (nachKat[f.kategorie] ||= []).push(f);
  const umfeld = [el('div', { class: 'kennzahlen' },
    kennzahl('Frequenzbringer gesamt', z.frequenzbringer.gesamt))];
  for (const [kat, eintraege] of Object.entries(nachKat).sort((a, b) => b[1].length - a[1].length)) {
    umfeld.push(el('h3', { class: 'hinweis-klein' }, `${kat} (${eintraege.length})`));
    umfeld.push(liste(eintraege, 6, (p) => el('li', {},
      el('span', { class: 'dist' }, `${NF.format(p.distanz_m)} m`),
      el('span', { class: 'haupt' },
        el('div', { class: 'name' }, p.name || '(ohne Name)'),
        el('div', { class: 'meta' },
          p.art + (p.mittelpunkt_ausserhalb ? ' · Fläche reicht in den Umkreis hinein' : ''))))));
  }
  if (!o.frequenzbringer.length) {
    setStatus('umfeld', 'leer', 'keine Treffer');
    umfeld.push(el('div', { class: 'warnung' },
      'Keine Frequenzbringer in OSM im Umkreis. Im ländlichen Raum ist das plausibel.'));
  }
  setInhalt('umfeld', ...umfeld, ...warnungen(d.warnings));
  setQuelle('umfeld', d.provenance);

  /* --- 6 Verkehr --- */
  const v = z.oepnv;
  const kzv = el('div', { class: 'kennzahlen' },
    kennzahl('Haltestellen', v.haltestellen),
    kennzahl('Linien (eindeutig)', v.linien_eindeutig),
    kennzahl('Routenrelationen', v.linien_gesamt));
  const linienTab = el('table', { class: 'daten' },
    el('tr', {}, el('th', {}, 'Verkehrsmittel'), el('th', {}, 'Linien')));
  for (const [art, refs] of Object.entries(v.linien_refs)) {
    linienTab.append(el('tr', {}, el('td', {}, art), el('td', {}, refs.join(', '))));
  }
  const haltListe = liste(o.oepnv, 10, (p) => el('li', {},
    el('span', { class: 'dist' }, `${NF.format(p.distanz_m)} m`),
    el('span', { class: 'haupt' },
      el('div', { class: 'name' }, p.name || '(ohne Name)'),
      el('div', { class: 'meta' }, [p.art, p.netz].filter(Boolean).join(' · ')))));
  if (!o.oepnv.length) setStatus('verkehr', 'leer', 'keine Haltestellen');
  setInhalt('verkehr', kzv,
    v.linien_gesamt ? el('h3', { class: 'hinweis-klein' }, 'Linien im Umkreis') : null,
    v.linien_gesamt ? linienTab : null,
    el('h3', { class: 'hinweis-klein' }, 'Haltestellen'), haltListe,
    el('div', { class: 'notiz' },
      'Routenrelationen zählen Hin- und Rückrichtung getrennt. „Linien (eindeutig)" '
      + 'zählt die Liniennummern.'),
    ...warnungen(d.warnings));
  setQuelle('verkehr', d.provenance);

  /* --- 7 Leerstand --- */
  if (!o.leerstand.length) {
    setStatus('leerstand', 'leer', 'keine Treffer');
    setInhalt('leerstand', el('div', { class: 'notiz' },
      'Keine als leerstehend getaggten Objekte in OSM. Das heißt nicht, dass es keine '
      + 'gibt — Leerstand wird in OSM nur selten gepflegt. Für eine belastbare Aussage: '
      + 'Leerstandsmelder, Leerstandskataster der Kommune, Begehung.'));
  } else {
    setInhalt('leerstand',
      el('div', { class: 'kennzahlen' }, kennzahl('Leerstände in OSM', z.leerstand.gesamt)),
      liste(o.leerstand, 10, (p) => el('li', {
        class: 'springbar',
        title: 'Klick: Karte springt zu diesem Leerstand',
        onclick: () => springeZuPoi(p, 'leerstand'),
      },
        el('span', { class: 'dist' }, `${NF.format(p.distanz_m)} m`,
          el('div', { class: 'basis' }, p.richtung || '')),
        el('span', { class: 'haupt' },
          el('div', { class: 'name' }, p.name || p.adresse || '(ohne Name)'),
          el('div', { class: 'meta' },
            [p.adresse, p.art, p.frueher ? `früher: ${p.frueher}` : null]
              .filter(Boolean).join(' · '))))),
      el('div', { class: 'hinweis-klein' },
        'Klick auf einen Eintrag: die Karte springt dorthin und markiert den '
        + 'Leerstand. Straße/Hausnummer erscheinen, soweit sie in OSM hinterlegt sind.'),
      el('div', { class: 'notiz' },
        'OSM-Leerstand ist lückenhaft gepflegt. Die Zahl ist eine Untergrenze.'));
  }
  setQuelle('leerstand', d.provenance);
}

/* Block 7b — Leerstandsmelder.de: zweite Untergrenze neben dem OSM-Leerstand,
   unabhängig erhoben (Bürgermeldungen). Auf ausdrücklichen Wunsch mit
   Lizenz-Warnung eingebaut — die Plattform weist keine Datenlizenz aus. */
function zeigeLeerstandsmelder(d) {
  const id = 'leerstandsmelder';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const m = d.data || {};
  const eintraege = m.meldungen || [];
  setStatus(id, eintraege.length ? 'ok' : 'leer',
    eintraege.length
      ? `${NF.format(m.gesamt_im_umfeld)} Meldungen`
      : 'keine Meldung');

  const inhalt = [];
  if (eintraege.length) {
    inhalt.push(el('div', { class: 'kennzahlen' },
      kennzahl(`Meldungen im Umfeld (${NF.format(m.max_distanz_m)} m)`, m.gesamt_im_umfeld),
      kennzahl('davon ohne Ende-Datum', m.offen_im_umfeld),
      kennzahl('im gewählten Radius', m.im_radius)));
    inhalt.push(el('ul', { class: 'liste' },
      eintraege.map((x) => el('li', {},
        el('span', { class: 'haupt' },
          el('a', { href: x.url, target: '_blank', rel: 'noopener',
            title: 'Meldung auf leerstandsmelder.de öffnen' },
          x.titel || x.strasse || 'Meldung'),
          x.beendet_am ? ' — beendet ' + fmtIsoDatum(x.beendet_am) : ''),
        el('span', { class: 'neben' },
          `gemeldet ${fmtIsoDatum(x.gemeldet_am)} · `
          + `${NF.format(x.distanz_m)} m ${x.richtung}`)))));
  }
  setInhalt(id,
    ...inhalt,
    ...(m.hinweise || []).map((h) => el('div', { class: 'warnung' }, h)),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* Block 7c — Handelsregister-Umfeld aus der OffeneRegister-Datenspende.
   Rein lokal (einmal importiert); der Datenstand 2019 steht an allem dran. */
async function ladeRegister(plz, lauf) {
  try {
    const d = await hole('/api/register', plz ? { plz } : {});
    if (lauf !== state.ladeLauf) return;
    state.daten.register = d;
    zeigeRegister(d);
  } catch (e) {
    if (lauf === state.ladeLauf) zeigeBlockFehler('register', e);
  }
}

function zeigeRegister(d) {
  const id = 'register';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht lesbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const r = d.data;
  if (!r) {
    setStatus(id, 'leer', 'keine Postleitzahl');
    setInhalt(id, ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  if (!r.importiert) {
    setStatus(id, 'leer', 'nicht importiert');
    setInhalt(id,
      el('div', { class: 'notiz' },
        'Die Handelsregister-Datenspende (OffeneRegister.de, Stand 2019) '
        + 'liegt noch nicht lokal vor. ' + (r.anleitung || '')),
      el('div', { class: 'notiz' },
        el('a', { href: r.portal, target: '_blank', rel: 'noopener' },
          'Über die Datenspende (offeneregister.de)')));
    setQuelle(id, d.provenance);
    return;
  }
  setStatus(id, 'ok', `${NF.format(r.firmen_gesamt)} Firmen (2019)`);

  const auszug = (r.gastro_auszug || []).length
    ? el('ul', { class: 'liste' },
      r.gastro_auszug.map((x) => el('li', {},
        el('span', { class: 'haupt' },
          x.name + (x.aktiv_2019 ? '' : ' — 2019 bereits gelöscht')),
        el('span', { class: 'neben' },
          [x.register, x.adresse].filter(Boolean).join(' · ')))))
    : el('div', { class: 'notiz' },
      'Kein Firmenname in dieser PLZ passt auf die Gastro-Stichworte — '
      + 'Betreibergesellschaften heißen oft neutral.');

  setInhalt(id,
    el('div', { class: 'kennzahlen' },
      kennzahl(`Firmen mit Sitz in ${r.plz}`, r.firmen_gesamt),
      kennzahl('davon 2019 eingetragen', r.aktiv_2019),
      kennzahl('Namens-Treffer Gastronomie', r.gastro_gesamt)),
    el('h3', { class: 'hinweis-klein' }, 'Gastro-Auszug (Namensheuristik)'),
    auszug,
    ...(r.hinweise || []).map((h) => el('div', { class: 'warnung' }, h)),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* ------------------------------------ Franchise: Systemgastronomie & Marke */

/* Für einen Franchisenehmer zählen zwei Fragen, die der Gastronomieblock nur
   nebenbei beantwortet: Welche Systeme sitzen schon hier (deren Präsenz ist
   professionell geprüfte Frequenz — und direkte Konkurrenz), und wo ist der
   nächste Betrieb der EIGENEN Marke (Gebietsschutz, Kannibalisierung)?
   Alles aus den bereits geladenen OSM-Daten; nur die Markensuche fragt auf
   Knopfdruck einen größeren Umkreis ab. */

function zeigeFranchise(o, d) {
  const id = 'franchise';
  const g = (o.zusammenfassung || {}).gastronomie || {};
  const gesamt = g.gesamt || 0;

  /* Marken aus der Betriebsliste: je Marke Anzahl und nächste Entfernung. */
  const marken = new Map();
  for (const p of o.gastronomie || []) {
    if (!p.marke) continue;
    const e = marken.get(p.marke) || { anzahl: 0, naechster: Infinity, typ: p.typ_label };
    e.anzahl += 1;
    if (p.distanz_m < e.naechster) { e.naechster = p.distanz_m; e.typ = p.typ_label; }
    marken.set(p.marke, e);
  }

  const kz = el('div', { class: 'kennzahlen' },
    kennzahl('Kettenbetriebe im Umkreis', g.ketten),
    kennzahl('Einzelbetriebe', g.einzelbetriebe),
    kennzahl('Marken (eindeutig)', marken.size),
    kennzahl('Kettenanteil', gesamt ? (g.ketten / gesamt) * 100 : null, '%', 1));

  const markenTab = el('table', { class: 'daten' },
    el('tr', {}, el('th', {}, 'Marke'), el('th', {}, 'Typ'),
      el('th', { class: 'num' }, 'Betriebe'), el('th', { class: 'num' }, 'nächster (m)')));
  for (const [name, e] of [...marken.entries()].sort((a, b) => b[1].anzahl - a[1].anzahl)) {
    markenTab.append(el('tr', {},
      el('td', {}, name), el('td', {}, e.typ || '—'),
      el('td', { class: 'num' }, NF.format(e.anzahl)),
      el('td', { class: 'num' }, NF.format(e.naechster))));
  }

  /* Gebietsschutz: eigene Marke im großen Umkreis suchen — auf Knopfdruck,
     weil es eine eigene Overpass-Abfrage ist. */
  const ergebnis = el('div', { id: 'marke-ergebnis' });
  const form = el('div', { class: 'marke-form' },
    el('input', {
      type: 'text', id: 'marke-name', maxlength: '60',
      placeholder: 'deine Marke, z. B. BURGER KING',
      'aria-label': 'Eigene Marke',
      onkeydown: (ev) => { if (ev.key === 'Enter') ladeMarke(); },
    }),
    el('select', { id: 'marke-radius', 'aria-label': 'Suchradius' },
      el('option', { value: '5000' }, '5 km'),
      el('option', { value: '10000', selected: true }, '10 km'),
      el('option', { value: '20000' }, '20 km')),
    el('button', { id: 'btn-marke', onclick: ladeMarke }, 'Eigene Marke suchen'));

  setStatus(id, gesamt ? 'ok' : 'leer', gesamt ? 'geladen' : 'keine Betriebe');
  setInhalt(id, kz,
    marken.size
      ? el('h3', { class: 'hinweis-klein' }, 'Systeme im Umkreis')
      : el('div', { class: 'notiz' },
        'Keine Kettenbetriebe (brand-Tag) im Umkreis. Entweder ist die Lage für '
        + 'Systemgastronomie unerschlossen — oder OSM kennt die Marken hier nicht.'),
    marken.size ? markenTab : null,
    el('div', { class: 'notiz' },
      'Systemgastronomie prüft Standorte professionell: ihre Präsenz ist ein '
      + 'Indiz für tragfähige Frequenz — und zugleich direkte Konkurrenz. Ihr '
      + 'Fehlen kann eine Lücke sein oder ein Warnsignal; diese Zahl entscheidet '
      + 'das nicht.'),
    el('h3', { class: 'hinweis-klein' }, 'Gebietsschutz: eigene Marke im Umkreis'),
    el('p', { class: 'hinweis-klein' },
      'Sucht Betriebe deiner Marke (brand- und Namenssuche) in einem größeren '
      + 'Umkreis — Gebietsschutz wird in Kilometern gedacht, nicht in Gehminuten. '
      + 'Die erste Suche je Punkt lädt alle Betriebe im Umkreis (gemessen für '
      + '10 km Innenstadt: 4.631 Betriebe, 2,6 MB, ~30 s); jede weitere Marke am '
      + 'selben Punkt kommt dann aus dem Cache.'),
    form, ergebnis);
  setQuelle(id, d.provenance);
}

async function ladeMarke() {
  const name = document.getElementById('marke-name')?.value?.trim();
  const radius = Number(document.getElementById('marke-radius')?.value || 10000);
  const ziel = document.getElementById('marke-ergebnis');
  if (!ziel) return;
  if (!name || name.length < 2) {
    ziel.replaceChildren(el('div', { class: 'warnung' }, 'Erst einen Markennamen eingeben.'));
    return;
  }
  ziel.replaceChildren(el('div', { class: 'laden' }));
  state.ebenen.marke.clearLayers();
  const lauf = state.ladeLauf;
  try {
    const d = await hole('/api/point/marke',
      { lat: state.lat, lon: state.lon, marke: name, r: radius });
    if (lauf !== state.ladeLauf) return;
    if (!d.ok) { ziel.replaceChildren(fehlerbox(d.error)); return; }
    const m = d.data;

    for (const t of m.treffer) {
      const kreis = L.circleMarker([t.lat, t.lon], {
        radius: 7, color: '#4b2a7b', weight: 2, fillColor: '#8257c4',
        fillOpacity: 0.9 * state.deckkraft, opacity: state.deckkraft,
        _basisDeckkraft: 0.9, _basisRand: 1,
      });
      kreis.bindPopup(`<h4>${esc(t.name || '(ohne Name)')}</h4>
        <p>${esc(t.typ || '')} · ${NF.format(t.distanz_m)} m ${esc(t.richtung || '')}
        ${t.nur_namensgleich ? '<br><em>nur namensgleich — kein brand-Tag</em>' : ''}</p>
        <p class="hinweis-klein"><a href="${esc(t.osm_url)}" target="_blank" rel="noopener">In OpenStreetMap ansehen</a></p>`);
      state.ebenen.marke.addLayer(kreis);
    }
    if (m.treffer.length && !karte.hasLayer(state.ebenen.marke)) {
      state.ebenen.marke.addTo(karte);
    }

    const teile = [el('div', { class: 'kennzahlen' },
      kennzahl(`Betriebe „${m.marke}“ in ${NF.format(m.radius_m / 1000)} km`, m.anzahl),
      kennzahl('Nächster eigener Betrieb', m.naechster_m, 'm'),
      kennzahl('durchsuchte Betriebe', m.basis_betriebe))];
    if (m.treffer.length) {
      teile.push(liste(m.treffer, 8, (t) => el('li', {},
        el('span', { class: 'dist' }, `${NF.format(t.distanz_m)} m`),
        el('span', { class: 'haupt' },
          el('div', { class: 'name' }, t.name || '(ohne Name)'),
          el('div', { class: 'meta' },
            [t.typ, t.richtung, t.nur_namensgleich ? 'nur namensgleich' : null]
              .filter(Boolean).join(' · '))))));
      teile.push(el('div', { class: 'notiz' },
        'Die violetten Marker auf der Karte zeigen die Treffer.'));
    }
    for (const h of m.hinweise || []) teile.push(el('div', { class: 'hinweis-klein' }, h));
    teile.push(...warnungen(d.warnings || []));
    ziel.replaceChildren(...teile);
  } catch (e) {
    ziel.replaceChildren(fehlerbox({ message: e.message }));
  }
}

/* --------------------------- Verfügbares Einkommen (Kreisebene, VGRdL) */

/* Kleinräumige Kaufkraft ist ein kommerzielles Datenprodukt. Was es amtlich
   und frei gibt, ist das verfügbare Einkommen je Einwohner auf Kreisebene —
   der Block sagt beides ehrlich dazu. Braucht den Gemeindeschlüssel aus dem
   Zensus, lädt deshalb erst nach diesem Block. */
async function ladeEinkommen(ags, lauf) {
  if (!ags) {
    setStatus('einkommen', 'leer', 'kein Gemeindeschlüssel');
    setInhalt('einkommen', el('div', { class: 'notiz' },
      'Ohne Gemeindeschlüssel (aus dem Zensusblock) lässt sich kein Kreiswert '
      + 'zuordnen.'));
    return;
  }
  try {
    const d = await hole('/api/einkommen', { ags });
    if (lauf !== state.ladeLauf) return;
    state.daten.einkommen = d;
    zeigeEinkommen(d);
  } catch (e) {
    if (lauf === state.ladeLauf) zeigeBlockFehler('einkommen', e);
  }
}

function zeigeEinkommen(d) {
  const id = 'einkommen';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const e = d.data;
  if (!e) {
    setStatus(id, 'leer', 'kein Wert');
    setInhalt(id, ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  setStatus(id, 'ok', 'geladen');

  const kz = el('div', { class: 'kennzahlen' },
    kennzahl(e.kreis?.name || 'Kreis', e.kreis?.wert_eur, '€/Einw.'),
    kennzahl(e.land?.name || 'Land', e.land?.wert_eur, '€/Einw.'),
    kennzahl(e.bund?.name || 'Deutschland', e.bund?.wert_eur, '€/Einw.'));

  const verlauf = e.verlauf_kreis || [];
  const tab = el('table', { class: 'daten' },
    el('tr', {}, el('th', {}, 'Jahr'), el('th', { class: 'num' }, '€ je Einwohner')));
  for (const v of verlauf.slice(-5)) {
    tab.append(el('tr', {}, el('td', {}, v.jahr),
      el('td', { class: 'num' }, NF.format(v.wert_eur))));
  }

  setInhalt(id, kz,
    verlauf.length > 1 ? el('h3', { class: 'hinweis-klein' }, 'Verlauf des Kreises') : null,
    verlauf.length > 1 ? tab : null,
    el('div', { class: 'warnung' },
      'Kreiswert — innerhalb einer Großstadt unterscheidet er keine Viertel. '
      + 'Kleinräumige Anzeiger sind Nettokaltmiete und Eigentümerquote aus dem '
      + 'Zensusblock. Und verfügbares Einkommen ist kein Kaufkraftindex.'),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* Block 3g — Sicherheitslage des Kreises (PKS-Kreistabelle des BKA).
   Für Nachtgastronomie relevant; die BKA-Interpretationshilfe zur
   eingeschränkten Vergleichbarkeit steht als Hinweis am Block. */
async function ladePks(ags, lauf) {
  if (!ags) {
    setStatus('pks', 'leer', 'kein Gemeindeschlüssel');
    setInhalt('pks', el('div', { class: 'notiz' },
      'Ohne Gemeindeschlüssel (aus dem Zensusblock) lässt sich kein '
      + 'Kreiswert zuordnen.'));
    return;
  }
  try {
    const d = await hole('/api/pks', { ags });
    if (lauf !== state.ladeLauf) return;
    state.daten.pks = d;
    zeigePks(d);
  } catch (e) {
    if (lauf === state.ladeLauf) zeigeBlockFehler('pks', e);
  }
}

function zeigePks(d) {
  const id = 'pks';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const k = d.data;
  if (!k) {
    setStatus(id, 'leer', 'Kreis nicht in der Tabelle');
    setInhalt(id, ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  const insgesamt = (k.delikte || []).find((x) => x.schluessel === '------');
  setStatus(id, 'ok', insgesamt?.vergleich
    ? `Rang ${insgesamt.vergleich.rang} von ${insgesamt.vergleich.von}`
    : 'geladen');

  const tab = el('table', { class: 'daten' },
    el('tr', {},
      el('th', {}, 'Straftaten(gruppe)'),
      el('th', { class: 'num' }, 'Fälle'),
      el('th', { class: 'num' }, 'HZ je 100.000'),
      el('th', { class: 'num' }, 'Median 400 Kreise'),
      el('th', { class: 'num' }, 'Rang'),
      el('th', { class: 'num' }, 'Aufklärung')));
  for (const x of k.delikte || []) {
    tab.append(el('tr', {},
      el('td', {}, x.name),
      el('td', { class: 'num' }, x.faelle === null ? '–' : NF.format(x.faelle)),
      el('td', { class: 'num' }, x.hz === null ? '–' : NF.format(x.hz)),
      el('td', { class: 'num' },
        x.vergleich ? NF.format(x.vergleich.median_hz) : '–'),
      el('td', { class: 'num' },
        x.vergleich ? `${x.vergleich.rang}.` : '–'),
      el('td', { class: 'num' },
        x.aufklaerungsquote === null ? '–' : `${NF.format(x.aufklaerungsquote)} %`)));
  }

  setInhalt(id,
    el('div', { class: 'notiz' },
      `${k.kreis} (${k.kreisart}), Berichtsjahr ${k.jahr}. `
      + 'Rang 1 = höchste Häufigkeitszahl unter den 400 Kreisen; '
      + 'HZ = Fälle je 100.000 Einwohner.'),
    tab,
    el('div', { class: 'notiz' },
      el('a', { href: k.portal, target: '_blank', rel: 'noopener' },
        'Alle Kreistabellen beim BKA')),
    ...(k.hinweise || []).map((h) => el('div', { class: 'warnung' }, h)),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* Block 3h — Wahlergebnis (BTW 2025) auf Wahlkreisebene. Struktur-Marker
   mit deutlicher Deutungs-Warnung — auf ausdrücklichen Wunsch eingebaut. */
async function ladeWahl(ags, lauf) {
  if (!ags) {
    setStatus('wahl', 'leer', 'kein Gemeindeschlüssel');
    setInhalt('wahl', el('div', { class: 'notiz' },
      'Ohne Gemeindeschlüssel (aus dem Zensusblock) lässt sich kein '
      + 'Wahlkreis zuordnen.'));
    return;
  }
  try {
    const d = await hole('/api/wahl', { ags });
    if (lauf !== state.ladeLauf) return;
    state.daten.wahl = d;
    zeigeWahl(d);
  } catch (e) {
    if (lauf === state.ladeLauf) zeigeBlockFehler('wahl', e);
  }
}

function zeigeWahl(d) {
  const id = 'wahl';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const w = d.data;
  if (!w) {
    setStatus(id, 'leer', 'keine Zuordnung');
    setInhalt(id, ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  const wk = (w.wahlkreise || []).map((x) => `${x.nr} ${x.name}`).join(' · ');
  setStatus(id, 'ok', w.mehrere_wahlkreise
    ? `${w.wahlkreise.length} Wahlkreise` : `WK ${w.wahlkreise[0]?.nr}`);

  const tab = el('table', { class: 'daten' },
    el('tr', {},
      el('th', {}, 'Partei'),
      el('th', { class: 'num' }, 'Zweitstimmen'),
      el('th', { class: 'num' }, 'Anteil'),
      el('th', { class: 'num' }, 'ggü. 2021')));
  for (const p of w.parteien || []) {
    tab.append(el('tr', {},
      el('td', {}, p.partei),
      el('td', { class: 'num' }, NF.format(p.zweitstimmen)),
      el('td', { class: 'num' },
        p.prozent === null ? '—' : `${NF1.format(p.prozent)} %`),
      el('td', { class: 'num' },
        p.diff_prozentpunkte === null || p.diff_prozentpunkte === undefined
          ? '—'
          : `${p.diff_prozentpunkte > 0 ? '+' : ''}${NF1.format(p.diff_prozentpunkte)} Pkt.`)));
  }

  setInhalt(id,
    el('div', { class: 'notiz' },
      `${w.wahl}, ${w.mehrere_wahlkreise ? 'Summe der Wahlkreise' : 'Wahlkreis'} `
      + `${wk}.`
      + (w.beteiligung_prozent !== null && w.beteiligung_prozent !== undefined
        ? ` Wahlbeteiligung ${NF1.format(w.beteiligung_prozent)} %`
          + (w.mehrere_wahlkreise ? ' (gewichtet berechnet)' : '') + '.'
        : '')),
    tab,
    ...(w.hinweise || []).map((h) => el('div', { class: 'warnung' }, h)),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* Block 5f — Luftqualität der nächsten Messstation (UBA/Länder): der
   gemessene Begleiter zum Lärmblock für Außengastronomie an Achsen. */
function zeigeLuft(d) {
  const id = 'luft';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const l = d.data;
  if (!l) {
    setStatus(id, 'leer', 'keine Station in der Nähe');
    setInhalt(id, ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  setStatus(id, 'ok', l.index_label || 'geladen');

  const komp = el('div', { class: 'kennzahlen' },
    ...(l.komponenten || []).map((k) => el('div', { class: 'kennzahl' },
      el('div', { class: 'titel' }, k.komponente),
      el('div', { class: 'wert' },
        k.wert === null || k.wert === undefined
          ? 'keine Angabe' : `${NF.format(k.wert)} ${k.einheit || ''}`),
      el('div', { class: 'basis' }, k.teilindex_label || ''))));

  setInhalt(id,
    el('div', { class: 'kennzahlen' },
      el('div', { class: 'kennzahl' },
        el('div', { class: 'titel' }, 'Luftqualitätsindex'),
        el('div', { class: `wert${l.index_label ? '' : ' fehlt'}` },
          l.index_label || 'keine Angabe'),
        el('div', { class: 'basis' }, `Stundenwert bis ${l.stand || '?'}`))),
    komp,
    el('div', { class: 'notiz' },
      `Station: ${l.station?.name || '?'} (${l.station?.code || '?'}) — `
      + `${NF.format(l.station?.distanz_m ?? 0)} m ${l.station?.richtung || ''}. `,
      el('a', { href: l.portal, target: '_blank', rel: 'noopener' },
        'Luftdaten-Portal des UBA')),
    ...(l.hinweise || []).map((h) => hinweisZeile(h)),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* Block 5h — Feiertage und Schulferien. Bewusst ein Kontextband ohne
   Kennzahl: Für die Standortwahl zählt allein, wie die Ferienlage zum
   Kundenprofil passt — und das entscheidet der Tourismus- bzw.
   Studierendenblock, nicht dieser hier. */
async function ladeKalender(ags, lauf) {
  const id = 'kalender';
  if (!ags) {
    setStatus(id, 'leer', 'kein Gemeindeschlüssel');
    setInhalt(id, el('div', { class: 'notiz' },
      'Ohne Gemeindeschlüssel (aus dem Zensusblock) lässt sich kein '
      + 'Bundesland zuordnen.'));
    return;
  }
  try {
    const d = await hole('/api/kalender', { ags });
    if (lauf !== state.ladeLauf) return;
    state.daten.kalender = d;
    zeigeKalender(d);
  } catch (e) {
    if (lauf === state.ladeLauf) zeigeBlockFehler(id, e);
  }
}

function zeigeKalender(d) {
  const id = 'kalender';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const k = d.data;
  if (!k) {
    setStatus(id, 'leer', 'kein Bundesland');
    setInhalt(id, ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  setStatus(id, 'ok', k.bundesland);
  const ftab = el('table', { class: 'daten' },
    el('tr', {}, el('th', {}, 'Ferien'), el('th', {}, 'Zeitraum'),
      el('th', { class: 'num' }, 'Tage')));
  for (const f of k.ferien || []) {
    ftab.append(el('tr', {},
      el('td', {}, f.name || '—'),
      el('td', {}, `${datumKurz(f.von)} – ${datumKurz(f.bis)}`),
      el('td', { class: 'num' }, f.tage === null ? '—' : NF.format(f.tage))));
  }
  const s = k.sommerferien;
  setInhalt(id,
    el('div', { class: 'kennzahlen' },
      el('div', { class: 'kennzahl' },
        el('div', { class: 'titel' }, 'Sommerferien'),
        el('div', { class: `wert${s ? '' : ' fehlt'}` },
          s ? `${NF.format(s.tage)} Tage` : 'keine Angabe'),
        el('div', { class: 'basis' },
          s ? `${datumKurz(s.von)} – ${datumKurz(s.bis)}` : '')),
      kennzahl(`Gesetzliche Feiertage ${k.jahr}`, k.feiertage_gesamt),
      kennzahl('davon nur in diesem Land', k.feiertage_landesspezifisch)),
    ftab,
    ...(k.hinweise || []).map((h) => hinweisZeile(h)),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

function datumKurz(iso) {
  if (!iso) return '—';
  const t = String(iso).split('-');
  return t.length === 3 ? `${t[2]}.${t[1]}.${t[0]}` : iso;
}

/* Block 4g — IHK-Gewerbedaten Berlin. Auf Anforderung, weil der erste
   Abruf eine rund 125 MB große Datei lädt (Git LFS). Danach 30 Tage im
   Cache — die Datei wird ohnehin nur monatlich fortgeschrieben. */
function zeigeIhkAngebot() {
  const inBerlin = state.lat !== null
    && state.lat >= 52.33 && state.lat <= 52.68
    && state.lon >= 13.08 && state.lon <= 13.77;
  if (!inBerlin) {
    setStatus('ihkberlin', 'leer', 'nur Berlin');
    setInhalt('ihkberlin', el('p', { class: 'hinweis-klein' },
      'Die IHK Berlin veröffentlicht ihren Mitgliederbestand als offene '
      + 'Daten (CC0) — mit Koordinate, Betriebsalter und '
      + 'Beschäftigtenklasse. Andere Industrie- und Handelskammern tun '
      + 'das nicht, deshalb gilt dieser Block nur für Berlin.'));
    return;
  }
  setStatus('ihkberlin', 'ok', 'auf Anforderung');
  setInhalt('ihkberlin',
    el('p', { class: 'hinweis-klein' },
      'Der amtliche Gegenwert zur OSM-Zählung: Die IHK kennt jeden '
      + 'Mitgliedsbetrieb, OpenStreetMap nur den eingetragenen. Dazu '
      + 'Betriebsalter und Beschäftigtenklasse je Betrieb.'),
    el('p', { class: 'hinweis-klein' },
      'Läuft nicht automatisch mit: Der erste Abruf lädt rund 125 MB. '
      + 'Danach bleibt die Auswertung 30 Tage im Cache.'),
    el('button', { id: 'btn-ihk', onclick: ladeIhkBerlin },
      'IHK-Bestand laden (125 MB)'));
}

async function ladeIhkBerlin() {
  const id = 'ihkberlin';
  const lauf = state.ladeLauf;
  setStatus(id, 'laedt', 'lädt …');
  setInhalt(id, el('div', { class: 'laden' }),
    el('p', { class: 'hinweis-klein' },
      'Die IHK-Datei wird geladen — beim ersten Mal einige Minuten.'));
  const knopf = document.getElementById('btn-ihk');
  if (knopf) knopf.disabled = true;
  try {
    const d = await hole('/api/point/ihk-berlin',
      { lat: state.lat, lon: state.lon, r: state.radius });
    if (lauf !== state.ladeLauf) return;
    state.daten.ihkberlin = d;
    zeigeIhkBerlin(d);
  } catch (e) {
    if (lauf === state.ladeLauf) zeigeBlockFehler(id, e);
  } finally {
    if (knopf) knopf.disabled = false;
  }
}

function zeigeIhkBerlin(d) {
  const id = 'ihkberlin';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const k = d.data;
  if (!k) {
    setStatus(id, 'leer', 'nur Berlin');
    setInhalt(id, ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  setStatus(id, 'ok', `${NF.format(k.gastronomie)} Betriebe`);

  const btab = el('table', { class: 'daten' },
    el('tr', {}, el('th', {}, 'Branche'), el('th', { class: 'num' }, 'Betriebe')));
  for (const b of k.nach_branche || []) {
    btab.append(el('tr', {},
      el('td', {}, b.branche),
      el('td', { class: 'num' }, NF.format(b.anzahl))));
  }

  setInhalt(id,
    el('div', { class: 'kennzahlen' },
      kennzahl(`Gastronomie im ${NF.format(k.radius_m)}-m-Umkreis`, k.gastronomie),
      kennzahl('Beherbergung', k.beherbergung),
      kennzahl('Median-Betriebsalter', k.median_alter_jahre, 'Jahre', 1),
      el('div', { class: 'kennzahl' },
        el('div', { class: 'titel' }, 'jung / alteingesessen'),
        el('div', { class: 'wert' },
          `${NF.format(k.junge_betriebe)} / ${NF.format(k.alte_betriebe)}`),
        el('div', { class: 'basis' }, 'bis 3 Jahre / ab 20 Jahre'))),
    k.planungsraum ? el('div', { class: 'notiz' },
      el('strong', {}, 'Lage: '),
      `${k.planungsraum} · Bezirk ${k.bezirk || '—'}`) : null,
    btab,
    ...(k.hinweise || []).map((h) => hinweisZeile(h)),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* Block 6j — Baurecht. Die Frage, die jede Umsatzprognose schlägt: Darf
   hier überhaupt Gastronomie betrieben werden? Punktgenau beantwortbar ist
   das bundesweit fast nirgends — der Block sagt offen, auf welcher Stufe
   die Antwort steht. */
function zeigeBaurecht(d) {
  const id = 'baurecht';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const b = d.data;
  const STUFEN = {
    gebietsart: 'Gebietsart bekannt',
    umring: 'Plan bekannt, Gebietsart nicht',
    kein_plan: 'kein Bebauungsplan (§ 34 BauGB)',
    kein_dienst: 'kein offener Dienst',
  };
  setStatus(id, b.stufe === 'gebietsart' ? 'ok' : 'leer',
    STUFEN[b.stufe] || '');

  const teile = [];
  for (const f of b.baugebiete || []) {
    const dt = f.deutung || {};
    teile.push(el('div', { class: 'notiz' },
      el('strong', {},
        `${f.art || 'Gebietsart unbekannt'}`
        + (dt.kuerzel ? ` (${dt.kuerzel})` : '')),
      el('div', {}, dt.gastronomie || ''),
      el('div', { class: 'hinweis-klein' },
        [`Plan: ${f.plan || '—'}`,
          f.rechtsstand ? `Rechtsstand: ${f.rechtsstand}` : null,
          f.grz ? `GRZ ${f.grz}` : null,
          f.gfz ? `GFZ ${f.gfz}` : null].filter(Boolean).join(' · ')),
      f.text ? el('div', { class: 'hinweis-klein' },
        el('em', {}, f.text)) : null));
  }
  if ((b.plaene || []).length) {
    const ptab = el('table', { class: 'daten' },
      el('tr', {},
        el('th', {}, 'Plan'),
        el('th', {}, 'Rechtsstand'),
        el('th', {}, 'Inhalt (planweit)'),
        el('th', {}, 'Dokument')));
    for (const p of b.plaene) {
      ptab.append(el('tr', {},
        el('td', {}, p.plan || '—'),
        el('td', {}, p.rechtsstand || '—'),
        el('td', {}, (p.inhalt_planweit || '—').slice(0, 90)),
        el('td', {}, p.pdf
          ? el('a', { href: p.pdf, target: '_blank', rel: 'noopener' }, 'PDF')
          : '—')));
    }
    teile.push(ptab);
  }
  for (const s of b.sanierungsgebiete || []) {
    teile.push(el('div', { class: 'notiz' },
      el('strong', {}, `Sanierungsgebiet: ${s.name}`),
      el('div', { class: 'hinweis-klein' },
        `${s.verfahren || ''} · seit ${s.in_kraft_seit || '—'} · `
        + `${s.flaeche_ha || '—'} ha · Bezirk ${s.bezirk || '—'}`)));
  }
  if ((b.denkmale || []).length) {
    teile.push(el('div', { class: 'notiz' },
      el('strong', {}, `Denkmalschutz: ${b.denkmale.length} Objekt(e)`),
      el('ul', { class: 'liste' },
        b.denkmale.slice(0, 5).map((x) => el('li', {},
          el('span', { class: 'haupt' },
            el('a', { href: x.link, target: '_blank', rel: 'noopener' },
              `${x.typ || 'Denkmal'} ${x.id || ''}`)))))));
  }

  setInhalt(id, ...teile.filter(Boolean),
    ...(b.hinweise || []).map((h) => hinweisZeile(h)),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* Block 6i — gemessene Passantenfrequenz. Die einzige Stelle im Werkzeug,
   an der echte Zählungen von Menschen stehen statt Näherungen. Es gibt sie
   nur an sieben Straßenabschnitten in drei Städten — überall sonst sagt der
   Block das offen, statt Unbekanntes als Null auszugeben. */
function zeigeFrequenz(d) {
  const id = 'frequenz';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const f = d.data;
  if (!f) {
    setStatus(id, 'leer', 'keine Zählstelle in der Nähe');
    setInhalt(id, ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  setStatus(id, 'ok', `${f.zaehlstelle} · ${NF.format(f.distanz_m)} m`);

  // Tagesgang als Balken — die Kurve ist die Aussage, nicht die Summe.
  const max = Math.max(1, ...f.kurve.map((k) => k.passanten));
  const balken = el('table', { class: 'daten' },
    el('tr', {},
      el('th', {}, 'Stunde'),
      el('th', { class: 'num' }, 'Passanten/h'),
      el('th', {}, 'Verlauf')));
  for (const k of f.kurve) {
    if (k.stunde < 6 || k.stunde > 23) continue;
    const breite = Math.round(100 * k.passanten / max);
    balken.append(el('tr', {},
      el('td', {}, `${String(k.stunde).padStart(2, '0')}:00`),
      el('td', { class: 'num' }, NF.format(k.passanten)),
      el('td', {},
        el('div', {
          class: 'balken',
          style: `width:${breite}%;min-width:2px`,
          title: `${NF.format(k.passanten)} Passanten je Stunde`,
        }))));
  }

  setInhalt(id,
    el('div', { class: 'kennzahlen' },
      el('div', { class: 'kennzahl' },
        el('div', { class: 'titel' }, 'Spitzenstunde'),
        el('div', { class: 'wert' },
          `${String(f.spitzenstunde).padStart(2, '0')}:00`),
        el('div', { class: 'basis' },
          `${NF.format(f.spitze_passanten)} Passanten je Stunde`)),
      kennzahl('Mittags (12–14 Uhr)', f.mittags, '/h'),
      kennzahl('Abends (18–20 Uhr)', f.abends, '/h'),
      el('div', { class: 'kennzahl' },
        el('div', { class: 'titel' }, 'Anteil ab 18 Uhr'),
        el('div', { class: `wert${f.abendanteil_prozent === null ? ' fehlt' : ''}` },
          f.abendanteil_prozent === null
            ? 'keine Angabe' : `${NF1.format(f.abendanteil_prozent)} %`),
        el('div', { class: 'basis' }, 'vom gesamten Tagesaufkommen'))),
    balken,
    el('div', { class: 'notiz' },
      el('strong', {}, 'Zählstelle: '),
      `${f.zaehlstelle} in ${f.stadt}, ${NF.format(f.distanz_m)} m entfernt · `
      + `${f.traeger} · Stand: ${f.stand}`),
    ...(f.hinweise || []).map((h) => hinweisZeile(h)),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* Block 5g — Besonnung. Für Außengastronomie der Unterschied zwischen
   Abendsonne und Dauerschatten, und bisher nur durch tagelanges eigenes
   Beobachten zu ermitteln. Gerechnet aus Sonnenstand (Astronomie) und
   OSM-Gebäudehöhen; die Abdeckung der Höhenangaben steht dabei, weil das
   Ergebnis ohne sie eine Obergrenze ist. */
function zeigeSonne(d) {
  const id = 'sonne';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const s = d.data;
  const sommer = (s.tage || {}).sommer || {};
  setStatus(id, 'ok', `${NF1.format(sommer.stunden || 0)} h im Hochsommer`);

  const tab = el('table', { class: 'daten' },
    el('tr', {},
      el('th', {}, 'Stichtag'),
      el('th', { class: 'num' }, 'Sonne'),
      el('th', { class: 'num' }, 'davon ab 17 Uhr'),
      el('th', {}, 'Fenster')));
  for (const k of ['sommer', 'uebergang', 'winter']) {
    const t = (s.tage || {})[k];
    if (!t) continue;
    const fenster = (t.fenster || []).length
      ? (t.fenster || []).map((f) => `${f.von}–${f.bis}`).join(', ')
      : 'kein Fenster ab 30 Minuten';
    tab.append(el('tr', {},
      el('td', {}, t.beschriftung),
      el('td', { class: 'num' },
        `${NF1.format(t.stunden)} h von ${NF1.format(t.moeglich_stunden)} h`),
      el('td', { class: 'num' }, `${NF1.format(t.abendsonne_stunden)} h`),
      el('td', {}, fenster)));
  }

  setInhalt(id,
    el('div', { class: 'kennzahlen' },
      kennzahl('Sonne zur Sommersonnenwende', sommer.stunden, 'h', 1),
      kennzahl('davon Abendsonne (ab 17 Uhr)', sommer.abendsonne_stunden, 'h', 1),
      kennzahl('Sonne zur Wintersonnenwende',
        ((s.tage || {}).winter || {}).stunden, 'h', 1),
      el('div', { class: 'kennzahl' },
        el('div', { class: 'titel' }, 'Höchstes Hindernis'),
        el('div', { class: 'wert' },
          `${NF1.format(s.hoechstes_hindernis_grad)}°`),
        el('div', { class: 'basis' },
          `Richtung ${s.hoechstes_hindernis_richtung} · `
          + `${s.umkreis_m} m Umkreis`))),
    tab,
    el('div', { class: 'notiz' },
      el('strong', {}, 'Datengrundlage: '),
      `${NF.format(s.gebaeude_mit_hoehe)} von ${NF.format(s.gebaeude_gesamt)} `
      + `Gebäuden im Umkreis haben eine Höhenangabe in OpenStreetMap`
      + (s.hoehen_abdeckung_prozent !== null
        ? ` (${NF.format(s.hoehen_abdeckung_prozent)} %)` : '')
      + `. Die übrigen ${NF.format(s.gebaeude_ohne_hoehe)} werfen hier keinen `
      + 'Schatten — die Sonnenzeiten sind deshalb eine Obergrenze.'),
    ...(s.hinweise || []).map((h) => hinweisZeile(h)),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* Block 3d — Pendlerverflechtungen der Gemeinde (Pendlerrechnung der
   Länder). Die Tagesbevölkerungs-Frage: Wer ist tagsüber wirklich da?
   Braucht wie 3b/3c den Gemeindeschlüssel aus dem Zensusblock. */
async function ladePendler(ags, lauf) {
  if (!ags || String(ags).length < 8) {
    setStatus('pendler', 'leer', 'kein Gemeindeschlüssel');
    setInhalt('pendler', el('div', { class: 'notiz' },
      'Ohne 8-stelligen Gemeindeschlüssel (aus dem Zensusblock) lässt sich '
      + 'keine Gemeinde zuordnen.'));
    return;
  }
  try {
    const d = await hole('/api/pendler', { ags });
    if (lauf !== state.ladeLauf) return;
    state.daten.pendler = d;
    zeigePendler(d);
  } catch (e) {
    if (lauf === state.ladeLauf) zeigeBlockFehler('pendler', e);
  }
}

function zeigePendler(d) {
  const id = 'pendler';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const p = d.data;
  if (!p) {
    setStatus(id, 'leer', 'kein Wert');
    setInhalt(id, ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  setStatus(id, 'ok', 'geladen');

  const kz = el('div', { class: 'kennzahlen' },
    kennzahl('Einpendler', p.einpendler),
    kennzahl('Auspendler', p.auspendler),
    kennzahl('Pendlersaldo', p.saldo),
    kennzahl('Einpendlerquote', p.einpendler_quote, '%'),
    kennzahl('Auspendlerquote', p.auspendler_quote, '%'),
    kennzahl('Binnenpendler (wohnen + arbeiten hier)', p.binnenpendler));

  const deutung = [];
  if (p.saldo !== null && p.saldo !== undefined) {
    deutung.push(el('div', { class: 'notiz' },
      p.saldo > 0
        ? `${p.gemeinde?.name || 'Die Gemeinde'} gewinnt tagsüber per Saldo `
          + `${NF.format(p.saldo)} Menschen dazu — Publikum, das der Zensus `
          + '(Wohnbevölkerung) nicht zeigt. Gut für Mittagsgeschäft.'
        : `${p.gemeinde?.name || 'Die Gemeinde'} verliert tagsüber per Saldo `
          + `${NF.format(-p.saldo)} Menschen an andere Arbeitsorte — mittags `
          + 'ist hier weniger Publikum, als die Einwohnerzahl vermuten lässt.'));
  }

  const verflTabellen = [];
  const verfl = p.verflechtung || {};
  const vTab = (titel, liste, spalte) => {
    if (!liste || !liste.length) return null;
    const tab = el('table', { class: 'daten' },
      el('tr', {}, el('th', {}, titel), el('th', { class: 'num' }, spalte),
        el('th', { class: 'num' }, 'Entfernung')));
    for (const z of liste) {
      tab.append(el('tr', {},
        el('td', {}, z.name),
        el('td', { class: 'num' }, NF.format(z.anzahl)),
        el('td', { class: 'num' },
          z.km === null || z.km === undefined ? '—' : `${NF1.format(z.km)} km`)));
    }
    return tab;
  };
  const herkunft = vTab('Wichtigste Herkünfte der Einpendler', verfl.herkunft,
    'Einpendler');
  const ziele = vTab('Wichtigste Ziele der Auspendler', verfl.ziele, 'Auspendler');
  if (herkunft) verflTabellen.push(herkunft);
  if (ziele) verflTabellen.push(ziele);

  setInhalt(id, kz, ...deutung, ...verflTabellen,
    el('div', { class: 'warnung' },
      `Gemeindewert (Berichtsjahr ${p.jahr}) — für eine Großstadt die ganze `
      + 'Stadt, kein Viertel. Erwerbstätigen-Konzept nach gemeldeten Orten; '
      + 'Homeoffice- und Zweitwohnungs-Konstellationen tauchen deshalb mit '
      + 'großen Entfernungen auf — die km-Spalte macht sie erkennbar.'),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* Block 5b — Klimanormalwerte 1991–2020 der jeweils nächsten DWD-Station.
   Für Biergarten/Terrasse/Eisdiele: Sommertage, Sonne, Niederschlag. Jede
   Kennzahl nennt ihre Station samt Entfernung — jeder Parameter hat sein
   eigenes Stationsnetz, die Stationen können sich also unterscheiden. */
function zeigeKlima(d) {
  const id = 'klima';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const k = d.data;
  if (!k || !(k.kennzahlen || []).length) {
    setStatus(id, 'leer', 'kein Wert');
    setInhalt(id, ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  setStatus(id, 'ok', 'geladen');

  const tab = el('table', { class: 'daten' },
    el('tr', {},
      el('th', {}, 'Kennzahl'),
      el('th', { class: 'num' }, 'Wert (Normalperiode 1991–2020)'),
      el('th', {}, 'Station')));
  for (const z of k.kennzahlen) {
    const st = z.station || {};
    tab.append(el('tr', {},
      el('td', {}, z.titel),
      el('td', { class: 'num' },
        `${nfFest(z.stellen ?? 1).format(z.wert)} ${z.einheit}`),
      el('td', {},
        `${st.name || '—'} (${NF.format(Math.round((st.distanz_m || 0) / 100) / 10)} km`
        + (st.hoehe_m !== null && st.hoehe_m !== undefined
          ? `, ${NF.format(Math.round(st.hoehe_m))} m ü. NN)` : ')'))));
  }

  // Saisonverlauf der Sommertage: die Monatswerte zeigen, wie lang die
  // Draußen-Saison wirklich ist — Jahreszahl allein verdeckt das.
  const so = k.kennzahlen.find((z) => z.schluessel === 'sommertage');
  let saison = null;
  if (so && Array.isArray(so.monate) && so.monate.some((m) => m)) {
    const max = Math.max(1, ...so.monate.map((m) => m || 0));
    saison = el('div', {},
      el('h3', { class: 'hinweis-klein' },
        `Sommertage je Monat (Station ${so.station?.name || ''})`),
      el('div', { style: 'display:flex;align-items:flex-end;gap:2px;height:60px;margin:6px 0 2px;' },
        so.monate.map((m, i) => el('div', {
          title: `${['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'][i]} — ${NF1.format(m || 0)} Tage`,
          style: `flex:1;background:#c98f2c;border-radius:2px 2px 0 0;height:${Math.max(2, ((m || 0) / max) * 100)}%;`,
        }))),
      el('div', { style: 'display:flex;justify-content:space-between;font-size:11px;color:#5b6570;' },
        el('span', {}, 'Jan'), el('span', {}, 'Jun'), el('span', {}, 'Dez')));
  }

  setInhalt(id, tab, saison,
    el('div', { class: 'warnung' },
      'Stationswerte der Normalperiode 1991–2020 — kein aktuelles Jahr, keine '
      + 'Prognose, und der Wert der Station, nicht des Punktes. Am Alpenrand '
      + 'kann die Stationshöhe den Unterschied machen.'),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* Block 4f — Wettbewerbs-Abgleich mit Overture Places (lokaler Import).
   OSM ist die Untergrenze; Overture (Facebook/Instagram-Profile, Foursquare,
   Ketten-Filiallisten) kontrolliert sie nach oben. Nur-Overture-Treffer
   kommen als eigene Pins auf die Karte — lila, damit sie sich von den
   OSM-Pins unterscheiden. */
function zeigeOverture(d) {
  const id = 'overture';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht verfügbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const o = d.data || {};
  if (!o.importiert) {
    setStatus(id, 'leer', 'kein Import');
    setInhalt(id,
      el('p', { class: 'hinweis-klein' },
        'OSM zählt Betriebe unvollständig — gerade in Einkaufszentren. Die '
        + 'offenen Overture-Daten (u. a. Facebook/Instagram-Unternehmensprofile) '
        + 'kontrollieren diese Untergrenze nach oben. Einmalig einrichten:'),
      el('div', { class: 'formel' },
        'pip install overturemaps\ngastroviewer import-overture --region muenchen'),
      el('p', { class: 'hinweis-klein' },
        'Danach zeigt dieser Block je Punkt, wie viele Betriebe OSM fehlen — '
        + 'mit Namen, Adresse und eigenen Karten-Pins.'),
      ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }

  zeichnePois('overture', o.nur_overture);
  setStatus(id, 'ok', 'geladen');

  const kz = el('div', { class: 'kennzahlen' },
    kennzahl('OSM (Untergrenze)', o.osm_gesamt),
    kennzahl('Overture', o.anzahl_overture, `ab Verlässlichkeit ${NF1.format(o.schwelle)}`),
    kennzahl('in beiden Quellen', o.beide),
    kennzahl('nur in Overture', o.nur_overture.length),
    kennzahl('kombiniert', o.kombiniert_gesamt, 'OSM + nur-Overture', 0));

  const teile = [kz];
  if (o.nur_overture.length) {
    teile.push(
      el('h3', { class: 'hinweis-klein' },
        'Betriebe, die in OSM fehlen (Klick: Karte springt hin)'),
      liste(o.nur_overture, 10, (p) => el('li', {
        class: 'springbar',
        title: 'Klick: Karte springt zu diesem Betrieb',
        onclick: () => springeZuPoi(p, 'overture'),
      },
        el('span', { class: 'dist' }, `${NF.format(p.distanz_m)} m`,
          el('div', { class: 'basis' }, p.richtung || '')),
        el('span', { class: 'haupt' },
          el('div', { class: 'name' }, p.name),
          el('div', { class: 'meta' },
            [p.gruppe_label, p.adresse,
              `Verlässlichkeit ${NF2.format(p.confidence)}`,
              p.quellen].filter(Boolean).join(' · '))))));
  } else {
    teile.push(el('div', { class: 'notiz' },
      'Overture kennt hier keinen Betrieb, der in OSM fehlt — die '
      + 'OSM-Zählung ist an diesem Punkt ungewöhnlich vollständig.'));
  }

  setInhalt(id, ...teile,
    ...(o.hinweise || []).map((h) => hinweisZeile(h)),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* Block 6f — Straßenlärm am Punkt (Umgebungslärmkartierung, LfU Bayern).
   Berechnete Pegel an Hauptverkehrsstraßen; „nicht kartiert" heißt „keine
   kartierte Hauptverkehrsstraße am Punkt", nicht „leise". */
async function ladeLaerm(bundeslandCode, lauf) {
  try {
    const d = await hole('/api/point/laerm', {
      lat: state.lat, lon: state.lon,
      bundesland_code: bundeslandCode || '',
    });
    if (lauf !== state.ladeLauf) return;
    state.daten.laerm = d;
    zeigeLaerm(d);
  } catch (e) {
    if (lauf !== state.ladeLauf) return;
    zeigeBlockFehler('laerm', e);
  }
}

function zeigeLaerm(d) {
  const id = 'laerm';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const l = d.data;
  if (!l) {
    setStatus(id, 'leer', 'keine Kartierung');
    setInhalt(id, ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  if (!l.kartiert) {
    setStatus(id, 'ok', 'nicht kartiert');
    setInhalt(id,
      el('div', { class: 'notiz' },
        'Am Punkt liegt keine kartierte Hauptlärmquelle — für '
        + 'Außengastronomie meist die gute Nachricht.'),
      ...(l.hinweise || []).map((h) => hinweisZeile(h)),
      ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  setStatus(id, 'ok', l.dienst === 'uba' ? 'bundesweit (Klassen)' : 'geladen');
  // LfU (Bayern) liefert Rasterwerte mit Nachkommastelle, der
  // UBA-Bundesdienst 5-dB-Klassen — beide Formen ehrlich beschriftet.
  const zelle = (p, titel) => el('div', { class: 'kennzahl' },
    el('div', { class: 'titel' }, titel),
    el('div', { class: 'wert' },
      p.wert_db !== null && p.wert_db !== undefined
        ? `${NF1.format(p.wert_db)} dB(A)`
        : (p.klasse || 'nicht kartiert')),
    el('div', { class: 'basis' },
      p.wert_db !== null && p.wert_db !== undefined
        ? `Band ${p.klasse} · Kartierung ${p.kartierung}`
        : (p.klasse
          ? `Pegelklasse · Kartierung ${p.kartierung}`
            + (p.abdeckung ? ` · ${p.abdeckung}` : '')
          : 'keine kartierte Hauptlärmquelle am Punkt')));
  const extra = [];
  const wq = l.weitere_quellen || {};
  if (wq.schiene || wq.flug) {
    const teile = [];
    if (wq.schiene) teile.push(`Schienenlärm ${wq.schiene}`);
    if (wq.flug) teile.push(`Fluglärm ${wq.flug}`);
    extra.push(el('div', { class: 'notiz' },
      `Zusätzlich kartiert am Punkt: ${teile.join(' · ')} (LDEN).`));
  }
  setInhalt(id,
    el('div', { class: 'kennzahlen' },
      zelle(l.lden, 'LDEN (Tag-Abend-Nacht-Pegel)'),
      zelle(l.lnight, 'LNight (Nachtpegel 22–6 Uhr)')),
    ...extra,
    ...(l.hinweise || []).map((h) => hinweisZeile(h)),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* Block 1b — Gesamt-Score. Die Logik (Kennzahlen, Anker, Formel) liegt in
   score.js und wird auch vom Bericht genutzt. Hier nur die Anzeige: eine
   Gesamtzahl, je Kennzahl ein Balken mit Wert, Ankern und Gewichtsregler.
   Der Score rechnet nach, sobald irgendein Block neue Daten rendert
   (entprellt über setInhalt). */
let scoreTimer = null;
function planeScoreUpdate() {
  if (typeof berechneScore !== 'function') return;
  clearTimeout(scoreTimer);
  scoreTimer = setTimeout(zeigeScore, 400);
}

function zeigeScore() {
  if (!document.getElementById('inhalt-score')) return;
  const gewichte = ladeScoreGewichte();
  const s = berechneScore(state.daten || {}, gewichte);

  if (!s.teile.length) {
    setStatus('score', 'laedt', 'wartet auf Blöcke');
    setInhalt('score', el('p', { class: 'hinweis-klein' },
      'Der Score rechnet, sobald die ersten Blöcke geladen sind.'));
    return;
  }
  setStatus('score', 'ok',
    s.gesamt === null ? 'alle Gewichte 0' : `${s.gesamt} / 100`);

  const kopf = el('div', { class: 'kennzahlen' },
    el('div', { class: 'kennzahl' },
      el('div', { class: 'titel' }, 'Gesamt-Score'),
      el('div', { class: 'wert' },
        s.gesamt === null ? '—' : `${NF.format(s.gesamt)} / 100`),
      el('div', { class: 'basis' },
        `${s.teile.length} Kennzahlen · Gewichtssumme ${NF1.format(s.gewichtSumme)}`)));

  const zeilen = s.teile.map((t) => {
    const regler = el('input', {
      type: 'range', min: '0', max: '3', step: '0.5',
      value: String(t.gewicht), title: 'Gewicht dieser Kennzahl (0 = zählt nicht)',
    });
    regler.addEventListener('input', () => {
      const g = ladeScoreGewichte();
      g[t.key] = Number(regler.value);
      speichereScoreGewichte(g);
      zeigeScore();
    });
    const wertText = t.text
      || `${NF.format(Math.round(t.wert))}${t.einheit ? ' ' + t.einheit : ''}`;
    const [schlecht, gut] = t.anker;
    return el('div', { class: 'score-zeile', title: t.begruendung || '' },
      el('div', { class: 'score-kopf' },
        el('span', { class: 'haupt' }, t.label),
        el('span', { class: 'neben' },
          ` ${wertText} → ${NF.format(t.punkte)} P. · ${t.quelle}`)),
      el('div', { class: 'score-balken', style: 'height:8px;background:#e8ecef;border-radius:4px;overflow:hidden;' },
        el('div', {
          style: `width:${t.punkte}%;height:100%;background:var(--akzent);opacity:.8;`,
        })),
      el('div', { class: 'score-fuss', style: 'display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:11px;color:#5b6570;' },
        el('span', {},
          `Anker (gewählt): ${NF.format(schlecht)} → 0 P. · ${NF.format(gut)} → 100 P.`),
        el('label', { style: 'display:flex;align-items:center;gap:4px;' },
          `Gewicht ${NF1.format(t.gewicht)}`, regler)));
  });

  setInhalt('score',
    kopf,
    el('div', { class: 'score-liste', style: 'display:flex;flex-direction:column;gap:10px;margin-top:6px;' }, zeilen),
    s.fehlend.length
      ? el('div', { class: 'warnung' },
        'Nicht eingeflossen (liegt für diesen Punkt nicht vor): '
        + s.fehlend.join(', ') + '. Fehlende Kennzahlen verkleinern die '
        + 'Gewichtssumme, statt still als 0 zu zählen.')
      : null,
    el('div', { class: 'hinweis-klein' },
      'Der Score ist eine Einordnung, keine Prognose: Anker sind gewählte '
      + 'Werte (an jeder Zeile ausgewiesen), Gewichte deine eigene Setzung — '
      + 'lokal gespeichert, gleich auch im Bericht. Vergleichbar sind nur '
      + 'Punkte mit gleichem Radius.'));
}

/* Block 6g — Baustellen (Stadt München). Vier-Wochen-Vorschau der
   Servicekarte: was jetzt läuft oder demnächst beginnt, mit Umriss auf der
   Karte. Eine Gehwegsperrung vor der Tür ist für Laufkundschaft der
   kurzfristige Ernstfall — deshalb wird sie eigens gezählt. */
function zeigeBaustellen(d) {
  const id = 'baustellen';
  state.ebenen.baustellen?.clearLayers();
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const b = d.data;
  if (!b) {
    setStatus(id, 'leer', 'nur München');
    setInhalt(id, ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  if (!b.gesamt) {
    setStatus(id, 'ok', 'keine im Radius');
    setInhalt(id,
      el('div', { class: 'notiz' },
        `Im Umkreis von ${NF.format(b.radius_m)} m ist aktuell keine Baustelle `
        + 'und kein Haltverbot gemeldet (Stichtag '
        + `${b.stichtag}, Vorschau vier Wochen).`),
      ...(b.hinweise || []).map((h) => hinweisZeile(h)),
      ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  setStatus(id, 'ok', `${b.gesamt} im Radius`);

  // Karte: Umriss plus Mittelpunkt-Pin (der Pin trägt das Popup und macht
  // die Liste springbar).
  const stil = POI_STIL.baustellen;
  for (const e of b.liste || []) {
    if (e.umriss && e.umriss.length >= 3) {
      state.ebenen.baustellen.addLayer(L.polygon(e.umriss, {
        color: e.gehweg_betroffen ? '#c62828' : stil.color,
        weight: 2, fillColor: stil.fill,
        fillOpacity: 0.25 * state.deckkraft, opacity: state.deckkraft,
        _basisDeckkraft: 0.25, _basisRand: 1,
      }));
    }
    if (e.lat !== null && e.lon !== null) {
      const m = L.circleMarker([e.lat, e.lon], {
        radius: 5, color: stil.color, weight: 1.5, fillColor: stil.fill,
        fillOpacity: 0.85 * state.deckkraft, opacity: state.deckkraft,
        _basisDeckkraft: 0.85, _basisRand: 1,
      });
      m.bindPopup(() => `<h4>${esc(e.ort)}</h4><table>
        <tr><td>Art</td><td><b>${esc(e.art)}</b></td></tr>
        <tr><td>Status</td><td><b>${esc(e.status)}</b></td></tr>
        <tr><td>Zeitraum</td><td><b>${esc(e.beginn || '?')} – ${esc(e.ende || '?')}</b></td></tr>
        ${e.beeintraechtigung ? `<tr><td>Beeinträchtigung</td><td><b>${esc(e.beeintraechtigung)}</b></td></tr>` : ''}
        </table>${e.beschreibung ? `<p class="hinweis-klein">${esc(e.beschreibung)}</p>` : ''}
        ${e.link ? `<p class="hinweis-klein"><a href="${esc(e.link)}" target="_blank" rel="noopener">Baustellen-Info der Stadt</a></p>` : ''}`,
      { maxWidth: 320 });
      state.ebenen.baustellen.addLayer(m);
    }
  }

  const kz = el('div', { class: 'kennzahlen' },
    kennzahl('Laufend', b.laufend),
    kennzahl('Geplant (Vorschau)', b.geplant),
    el('div', { class: 'kennzahl' + (b.gehweg_betroffen ? ' warn' : '') },
      el('div', { class: 'titel' }, 'Gehweg betroffen'),
      el('div', { class: 'wert' }, NF.format(b.gehweg_betroffen)),
      el('div', { class: 'basis' }, 'Sperrung/Einengung laut Stadt')),
    el('div', { class: 'kennzahl' },
      el('div', { class: 'titel' }, 'Baumaßnahmen / Haltverbote'),
      el('div', { class: 'wert' }, `${NF.format(b.baumassnahmen)} / ${NF.format(b.haltverbote)}`),
      el('div', { class: 'basis' }, 'Haltverbote meist nur wenige Tage')));

  const liste = el('ul', { class: 'liste' },
    (b.liste || []).map((e) => {
      const teile = [
        `${e.status === 'geplant' ? 'ab ' + (e.beginn || '?') : 'bis ' + (e.ende || '?')}`,
        e.beeintraechtigung || null,
        `${NF.format(e.distanz_m)} m${e.richtung ? ' ' + e.richtung : ''}`,
      ].filter(Boolean).join(' · ');
      return el('li', {},
        el('span', { class: 'haupt' },
          (e.lat !== null
            ? el('a', {
              href: '#', title: 'Auf der Karte zeigen',
              onclick: (ev) => { ev.preventDefault(); springeZuPoi(e, 'baustellen'); },
            }, e.ort)
            : e.ort),
          ` — ${e.art}${e.gehweg_betroffen ? ' · Gehweg!' : ''}`),
        el('span', { class: 'neben' }, teile));
    }));

  setInhalt(id, kz, liste,
    ...(b.hinweise || []).map((h) => hinweisZeile(h)),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* Block 5c — Städtische Märkte München. Wochen- und Bauernmärkte bringen an
   ihren Markttagen Laufkundschaft; die Öffnungszeiten stehen direkt im
   städtischen Datensatz. */
function zeigeMaerkte(d) {
  const id = 'maerkte';
  state.ebenen.maerkte?.clearLayers();
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const m = d.data;
  if (!m) {
    setStatus(id, 'leer', 'nur München');
    setInhalt(id, ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  const nah = m.in_reichweite || [];
  if (!nah.length) {
    setStatus(id, 'ok', 'keiner in Reichweite');
    setInhalt(id,
      el('div', { class: 'notiz' },
        `Kein städtischer Markt innerhalb von ${NF.format(m.max_distanz_m)} m `
        + `(gewählter Wert) — stadtweit sind es ${NF.format(m.stadtweit)}.`),
      ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  setStatus(id, 'ok', `${nah.length} in Reichweite`);

  zeichnePois('maerkte', nah.map((x) => ({
    ...x, typ_label: x.rubrik,
    tags: x.oeffnungszeiten ? { Öffnungszeiten: x.oeffnungszeiten } : {},
  })));

  const naechster = m.naechster;
  const kz = el('div', { class: 'kennzahlen' },
    kennzahl('Im Umkreis', m.im_radius),
    kennzahl(`In Reichweite (${NF.format(m.max_distanz_m)} m)`, nah.length),
    el('div', { class: 'kennzahl' },
      el('div', { class: 'titel' }, 'Nächster'),
      el('div', { class: 'wert' }, naechster ? naechster.name : '—'),
      el('div', { class: 'basis' },
        naechster ? `${naechster.rubrik} · ${NF.format(naechster.distanz_m)} m ${naechster.richtung}` : '')));

  const liste = el('ul', { class: 'liste' },
    nah.map((x) => el('li', {},
      el('span', { class: 'haupt' },
        el('a', {
          href: '#', title: 'Auf der Karte zeigen',
          onclick: (ev) => { ev.preventDefault(); springeZuPoi(x, 'maerkte'); },
        }, x.name),
        ` — ${x.rubrik}`),
      el('span', { class: 'neben' },
        [x.oeffnungszeiten, x.adresse,
          `${NF.format(x.distanz_m)} m ${x.richtung}`]
          .filter(Boolean).join(' · ')))));

  setInhalt(id, kz, liste,
    ...(m.hinweise || []).map((h) => hinweisZeile(h)),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* Block 5d — Kurzzeitvermietung (Inside Airbnb). Wo Gäste schlafen, zeigt
   kleinräumig nur dieser Datensatz — die amtliche Übernachtungszahl gibt es
   erst auf Kreisebene. Positionen plattformseitig um bis zu ~150 m versetzt;
   der Block sagt das dazu. */
function zeigeAirbnb(d) {
  const id = 'airbnb';
  state.ebenen.airbnb?.clearLayers();
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const a = d.data;
  if (!a) {
    setStatus(id, 'leer', 'keine Datenstadt');
    setInhalt(id, ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  setStatus(id, 'ok', `${NF.format(a.im_radius)} Inserate`);
  zeichnePois('airbnb', a.marker || []);

  const kz = el('div', { class: 'kennzahlen' },
    kennzahl(`Inserate im Umkreis (${NF.format(a.radius_m)} m)`, a.im_radius),
    kennzahl('davon ganze Unterkünfte', a.ganze_unterkuenfte),
    kennzahl('Bewertungen 12 Monate (Summe)', a.bewertungen_12m),
    el('div', { class: 'kennzahl' },
      el('div', { class: 'titel' }, 'Median-Preis je Nacht'),
      el('div', { class: `wert${a.preis_median_eur === null ? ' fehlt' : ''}` },
        a.preis_median_eur === null ? 'keine Angabe' : `${NF.format(a.preis_median_eur)} €`),
      el('div', { class: 'basis' },
        `${NF.format(a.preis_basis)} von ${NF.format(a.im_radius)} Inseraten mit Preis`)),
    kennzahl(`Stadtweit (${a.stadt})`, a.stadtweit));

  const typen = Object.entries(a.nach_typ || {});
  const typZeile = typen.length
    ? el('div', { class: 'notiz' },
      'Zimmertypen: ' + typen.map(([k, v]) => `${k}: ${NF.format(v)}`).join(' · '))
    : null;

  const liste = (a.liste || []).length
    ? el('ul', { class: 'liste' },
      a.liste.map((x) => el('li', {},
        el('span', { class: 'haupt' },
          el('a', {
            href: '#', title: 'Auf der Karte zeigen (Position ~150 m ungenau)',
            onclick: (ev) => { ev.preventDefault(); springeZuPoi(x, 'airbnb'); },
          }, x.name),
          x.tags && x.tags['Preis je Nacht'] ? ` — ${x.tags['Preis je Nacht']}` : ''),
        el('span', { class: 'neben' },
          `${NF.format((x.tags || {})['Bewertungen 12 Monate'] || 0)} Bew./12 M. · `
          + `${NF.format(x.distanz_m)} m ${x.richtung}`))))
    : null;

  setInhalt(id,
    el('div', { class: 'notiz' },
      `${a.stadt}, Sammellauf vom ${a.stichtag || 'unbekannt'} — die `
      + `${NF.format(a.liste?.length || 0)} nächsten in der Liste.`),
    kz, typZeile, liste,
    ...(a.hinweise || []).map((h) => hinweisZeile(h)),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* Block 5e — Messe-Kalender München. Messetage sind planbare Frequenzspitzen;
   sie wirken über Hotels und die U2, nicht über Laufkundschaft am Gelände. */
function fmtIsoDatum(iso) {
  if (!iso || iso.length !== 10) return iso || '?';
  return `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`;
}

function zeigeMesse(d) {
  const id = 'messe';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const m = d.data;
  if (!m) {
    setStatus(id, 'leer', 'zu weit vom Gelände');
    setInhalt(id, ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  const kommend = m.kommend || [];
  const laufend = m.laufend || [];
  setStatus(id, 'ok',
    laufend.length ? `${laufend.length} laufend` : `${kommend.length} kommend`);

  const g = m.naechstes_gelaende || {};
  const jahr = (m.jahresreihe || []).filter((j) => j.besucher !== null).slice(-1)[0];
  const kz = el('div', { class: 'kennzahlen' },
    el('div', { class: 'kennzahl' },
      el('div', { class: 'titel' }, 'Nächstes Gelände'),
      el('div', { class: 'wert' }, g.name || '—'),
      el('div', { class: 'basis' },
        g.distanz_m !== undefined
          ? `${NF.format(g.distanz_m)} m ${g.richtung} (Gelände-Koordinate: gewählter Wert)` : '')),
    kennzahl('Laufende Veranstaltungen', laufend.length),
    kennzahl('Kommende Termine im Datensatz', kommend.length),
    jahr
      ? el('div', { class: 'kennzahl' },
        el('div', { class: 'titel' }, `Besucher ${jahr.jahr}`),
        el('div', { class: 'wert' }, NF.format(jahr.besucher)),
        el('div', { class: 'basis' },
          `Summe aus ${NF.format(jahr.mit_besucherzahl)} von `
          + `${NF.format(jahr.veranstaltungen)} Veranstaltungen mit Zahl`))
      : null);

  const termin = (e) => el('li', {},
    el('span', { class: 'haupt' }, e.titel,
      e.besucher !== null ? ` — ${NF.format(e.besucher)} Besucher` : ''),
    el('span', { class: 'neben' },
      [`${fmtIsoDatum(e.start)}–${fmtIsoDatum(e.ende)}`, e.gelaende,
        e.turnus, e.messetyp].filter(Boolean).join(' · ')));

  const listeLaufend = laufend.length
    ? el('div', {},
      el('div', { class: 'notiz' }, 'Gerade laufend:'),
      el('ul', { class: 'liste' }, laufend.map(termin)))
    : null;
  const listeKommend = kommend.length
    ? el('div', {},
      el('div', { class: 'notiz' }, `Kommende Termine (Stand ${fmtIsoDatum(m.stand_heute)}):`),
      el('ul', { class: 'liste' }, kommend.map(termin)))
    : null;

  const groesste = (m.groesste || []).length
    ? el('div', {},
      el('div', { class: 'notiz' }, 'Größte aufgezeichnete Veranstaltungen (seit 2018):'),
      el('ul', { class: 'liste' }, m.groesste.map((e) => el('li', {},
        el('span', { class: 'haupt' }, e.titel, ` — ${NF.format(e.besucher)} Besucher`),
        el('span', { class: 'neben' },
          [e.start.slice(0, 4), e.gelaende, e.turnus].filter(Boolean).join(' · '))))))
    : null;

  const reihe = (m.jahresreihe || []).length
    ? el('table', { class: 'mini-tabelle' },
      el('tr', {}, el('th', {}, 'Jahr'), el('th', {}, 'Veranstaltungen'),
        el('th', {}, 'Besucher (Summe)')),
      m.jahresreihe.map((j) => el('tr', {},
        el('td', {}, String(j.jahr)),
        el('td', {}, NF.format(j.veranstaltungen)),
        el('td', {}, j.besucher === null ? '—'
          : `${NF.format(j.besucher)} (${NF.format(j.mit_besucherzahl)} mit Zahl)`))))
    : null;

  setInhalt(id, kz, listeLaufend, listeKommend, groesste, reihe,
    ...(m.hinweise || []).map((h) => hinweisZeile(h)),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* Block 3f — Tourismus-Saisonalität München. Stadtweite Monatszahlen des
   Statistischen Amts: wie tief ist der Januar, wie hoch der Oktober. Die
   Jahressumme je Kreis steht bundesweit im Kreisprofil (3c). */
function zeigeTourismus(d) {
  const id = 'tourismus';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const t = d.data;
  if (!t) {
    setStatus(id, 'leer', 'nur München');
    setInhalt(id, ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  setStatus(id, 'ok', `${NF.format(t.uebernachtungen_12m)} Übern./12 M.`);

  const s = t.saison;
  const kz = el('div', { class: 'kennzahlen' },
    kennzahl('Übernachtungen 12 Monate', t.uebernachtungen_12m),
    el('div', { class: 'kennzahl' },
      el('div', { class: 'titel' }, 'Zum Vorjahreszeitraum'),
      el('div', { class: `wert${t.veraenderung_vorjahr_prozent === null ? ' fehlt' : ''}` },
        t.veraenderung_vorjahr_prozent === null ? 'keine Angabe'
          : `${t.veraenderung_vorjahr_prozent > 0 ? '+' : ''}${NF1.format(t.veraenderung_vorjahr_prozent)} %`),
      el('div', { class: 'basis' }, 'gleiche 12 Monate, ein Jahr früher')),
    t.ausland_anteil_prozent !== null
      ? el('div', { class: 'kennzahl' },
        el('div', { class: 'titel' }, 'Auslandsanteil'),
        el('div', { class: 'wert' }, `${NF1.format(t.ausland_anteil_prozent)} %`),
        el('div', { class: 'basis' }, 'an den Übernachtungen, letzte 12 Monate'))
      : null,
    t.aufenthaltsdauer_naechte !== null
      ? el('div', { class: 'kennzahl' },
        el('div', { class: 'titel' }, 'Aufenthaltsdauer'),
        el('div', { class: 'wert' }, `${NF1.format(t.aufenthaltsdauer_naechte)} Nächte`),
        el('div', { class: 'basis' }, 'abgeleitet: Übernachtungen ÷ Gäste'))
      : null);

  let saisonTeil = null;
  if (s && (s.index || []).length === 12) {
    const max = Math.max(1, ...s.index.map((x) => x.index));
    saisonTeil = el('div', {},
      el('div', { class: 'notiz' },
        `Saisonkurve (Mittel der Jahre ${s.jahre.join(', ')}; 100 = Jahresdurchschnitt): `
        + `stärkster Monat ${s.staerkster.monat} (${NF.format(s.staerkster.index)}), `
        + `schwächster ${s.schwaechster.monat} (${NF.format(s.schwaechster.index)}).`),
      el('div', { style: 'display:flex;align-items:flex-end;gap:2px;height:60px;margin:6px 0 2px;' },
        s.index.map((x) => el('div', {
          title: `${x.monat}: Index ${NF.format(x.index)} (100 = Jahresdurchschnitt)`,
          style: 'flex:1;border-radius:2px 2px 0 0;'
            + `background:var(--akzent);opacity:.75;height:${Math.max(3, (x.index / max) * 100)}%;`,
        }))),
      el('div', { style: 'display:flex;justify-content:space-between;font-size:11px;color:#5b6570;' },
        el('span', {}, 'Jan'), el('span', {}, 'Jun'), el('span', {}, 'Dez')));
  }

  const reihe = (t.jahresreihe || []).length
    ? el('table', { class: 'mini-tabelle' },
      el('tr', {}, el('th', {}, 'Jahr'), el('th', {}, 'Übernachtungen (Jahressumme)')),
      t.jahresreihe.map((j) => el('tr', {},
        el('td', {}, String(j.jahr)),
        el('td', {}, NF.format(j.uebernachtungen)))))
    : null;

  setInhalt(id,
    el('div', { class: 'notiz' },
      'Stadtweite amtliche Beherbergungszahlen — der Wert hängt nicht vom '
      + 'gewählten Punkt ab.'),
    kz, saisonTeil, reihe,
    ...(t.hinweise || []).map((h) => hinweisZeile(h)),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* Block 3e — Amtliche Gastro-Anker aus der Regionaldatenbank. Das einzige
   Opt-in des Werkzeugs: der maschinelle Abruf verlangt eine (kostenlose)
   Kennung bei regionalstatistik.de. Ohne Kennung erklärt der Block den Weg
   und bietet das Eintragen direkt an; gespeichert wird nur lokal. */
async function ladeGenesis(ags, lauf) {
  const id = 'genesis';
  if (!ags) {
    setStatus(id, 'leer', 'kein Gemeindeschlüssel');
    setInhalt(id, el('p', { class: 'hinweis-klein' },
      'Ohne Gemeindeschlüssel (aus dem Zensusblock) lässt sich kein '
      + 'Kreiswert abrufen.'));
    return;
  }
  try {
    const d = await hole('/api/genesis', { ags });
    if (lauf !== state.ladeLauf) return;
    state.daten.genesis = d;
    if (d.ok && d.data === null) {
      const zugang = await hole('/api/genesis/zugang', {});
      if (lauf !== state.ladeLauf) return;
      zeigeGenesisOptIn(d, zugang, ags);
    } else {
      zeigeGenesis(d, ags);
    }
  } catch (e) {
    if (lauf === state.ladeLauf) zeigeBlockFehler(id, e);
  }
}

function zeigeGenesisOptIn(d, zugang, ags) {
  const id = 'genesis';
  if (zugang && zugang.konfiguriert) {
    // Kennung da, aber trotzdem keine Daten (z. B. kein Kreisschlüssel).
    setStatus(id, 'leer', 'keine Kreisdaten');
    setInhalt(id, ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  setStatus(id, 'leer', 'Opt-in');
  setInhalt(id,
    el('p', { class: 'hinweis-klein' },
      'Diese amtlichen Anker gibt es nur über die Regionaldatenbank der '
      + 'Statistischen Ämter (regionalstatistik.de): den steuerbaren '
      + 'Umsatz je Umsatzsteuerpflichtigem im Gastgewerbe des Kreises '
      + '(Prüfstein für die eigene Umsatzschätzung), die '
      + 'Gewerbean-/-abmeldungen (Gründungsdynamik) — und drei '
      + 'Gemeindewerte für ganz Deutschland: Beschäftigte am Arbeitsort '
      + '(die Tagesbevölkerung fürs Mittagsgeschäft), '
      + 'Gästeübernachtungen und Arbeitslose der Gemeinde.'),
    el('p', { class: 'hinweis-klein' },
      'Der maschinelle Abruf verlangt eine kostenlose Kennung — das '
      + 'einzige Konto, das dieses Werkzeug überhaupt kennt, und nur als '
      + 'Opt-in: Ohne Eintrag bleibt der Block leer, alles andere läuft '
      + 'ohne Konto weiter. Kennung und Passwort werden ausschließlich '
      + 'lokal gespeichert (Datenverzeichnis) und nur an '
      + 'regionalstatistik.de gesendet.'),
    el('p', { class: 'hinweis-klein' },
      el('a', { href: (zugang && zugang.registrierung) || '#', target: '_blank', rel: 'noopener' },
        'Kostenlose Registrierung bei regionalstatistik.de'),
      ' — danach Kennung (Nutzername) und Passwort hier eintragen.'),
    el('div', { class: 'pflegeleiste' },
      el('label', { for: 'genesis-kennung' }, 'Kennung'),
      el('input', { id: 'genesis-kennung', type: 'text', autocomplete: 'off' }),
      el('label', { for: 'genesis-passwort' }, 'Passwort'),
      el('input', { id: 'genesis-passwort', type: 'password', autocomplete: 'off' }),
      el('button', {
        id: 'btn-genesis-speichern',
        onclick: () => speichereGenesisZugang(ags),
      }, 'Speichern & prüfen')),
    el('div', { class: 'hinweis-klein', id: 'genesis-meldung' }, ''));
}

async function speichereGenesisZugang(ags) {
  const kennung = document.getElementById('genesis-kennung')?.value.trim();
  const passwort = document.getElementById('genesis-passwort')?.value || '';
  const meldung = document.getElementById('genesis-meldung');
  if (!kennung || !passwort) {
    if (meldung) meldung.textContent = 'Bitte Kennung und Passwort eintragen.';
    return;
  }
  if (meldung) meldung.textContent = 'Kennung wird beim Dienst geprüft …';
  try {
    const r = await fetch('/api/genesis/zugang', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kennung, passwort }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      if (meldung) meldung.textContent = j.detail || j.fehler || `HTTP ${r.status}`;
      return;
    }
    if (meldung) {
      meldung.textContent = 'Kennung geprüft und lokal gespeichert — '
        + 'Kreisdaten werden geladen …';
    }
    ladeGenesis(ags, state.ladeLauf);
  } catch (e) {
    if (meldung) meldung.textContent = String(e);
  }
}

async function entferneGenesisZugang(ags) {
  if (!window.confirm('Gespeicherte Kennung wirklich entfernen? Der Block '
    + 'zeigt danach wieder das Eintrag-Formular.')) return;
  try {
    await fetch('/api/genesis/zugang', { method: 'DELETE' });
  } catch { /* Der Neuaufbau unten zeigt den echten Zustand. */ }
  ladeGenesis(ags, state.ladeLauf);
}

function zeigeGenesis(d, ags) {
  const id = 'genesis';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error),
      el('p', { class: 'hinweis-klein' },
        'Falls die Kennung nicht mehr stimmt: unten entfernen und neu '
        + 'eintragen.'),
      el('button', { onclick: () => entferneGenesisZugang(ags) },
        'Gespeicherte Kennung entfernen'));
    setQuelle(id, d.provenance);
    return;
  }
  const g = d.data || {};
  const u = (g.umsatz || {}).aktuell;
  const w = (g.gewerbe || {}).aktuell;
  setStatus(id, 'ok', g.kreis || 'Kreiswerte');

  const kz = el('div', { class: 'kennzahlen' },
    el('div', { class: 'kennzahl' },
      el('div', { class: 'titel' }, 'Umsatz je USt-Pflichtigem Gastgewerbe'),
      el('div', { class: `wert${u ? '' : ' fehlt'}` },
        u ? `${NF.format(u.je_pflichtigem_eur)} €` : 'keine Angabe'),
      el('div', { class: 'basis' },
        u ? `Jahr ${u.jahr} · berechnet aus Umsatz ÷ Pflichtige` : '')),
    kennzahl(u ? `USt-Pflichtige Gastgewerbe (${u.jahr})` : 'USt-Pflichtige Gastgewerbe',
      u ? u.pflichtige : null),
    kennzahl('Anteil Gastgewerbe am Kreisumsatz',
      (g.umsatz || {}).anteil_am_gesamtumsatz_prozent, '%', 1),
    kennzahl(w ? `Gewerbeanmeldungen (${w.jahr})` : 'Gewerbeanmeldungen',
      w ? w.anmeldungen : null),
    kennzahl(w ? `Gewerbeabmeldungen (${w.jahr})` : 'Gewerbeabmeldungen',
      w ? w.abmeldungen : null),
    el('div', { class: 'kennzahl' },
      el('div', { class: 'titel' }, 'Saldo An-/Abmeldungen'),
      el('div', { class: `wert${w && w.saldo !== null ? '' : ' fehlt'}` },
        w && w.saldo !== null
          ? (w.saldo > 0 ? `+${NF.format(w.saldo)}` : NF.format(w.saldo))
          : 'keine Angabe'),
      el('div', { class: 'basis' },
        w ? `darunter Neuerrichtungen ${NF.format(w.neuerrichtungen ?? 0)}, `
          + `Betriebsaufgaben ${NF.format(w.betriebsaufgaben ?? 0)}` : '')));

  // Bestand und Bildung (AA-Runde): der amtliche Gastgewerbe-Nenner und
  // die beiden Frequenztreiber Studierende/Schüler.
  const nl = (g.niederlassungen || {}).aktuell;
  const nlEnt = (g.niederlassungen || {}).entwicklung;
  const st = (g.studierende || {}).aktuell;
  const sch = (g.schueler || {}).aktuell;
  const kreisTeile = [];
  if (nl || st || sch) {
    kreisTeile.push(el('h4', {}, 'Bestand und Bildung im Kreis'));
    kreisTeile.push(el('div', { class: 'kennzahlen' },
      el('div', { class: 'kennzahl' },
        el('div', { class: 'titel' },
          nl ? `Gastgewerbe-Betriebe (${nl.jahr})` : 'Gastgewerbe-Betriebe'),
        el('div', { class: `wert${nl ? '' : ' fehlt'}` },
          nl && nl.gastgewerbe !== null
            ? NF.format(nl.gastgewerbe) : 'keine Angabe'),
        el('div', { class: 'basis' }, nl && nl.anteil_prozent !== null
          ? `${NF1.format(nl.anteil_prozent)} % aller Niederlassungen`
          : '')),
      el('div', { class: 'kennzahl' },
        el('div', { class: 'titel' }, 'Bestandsentwicklung'),
        el('div', { class: `wert${nlEnt ? '' : ' fehlt'}` },
          nlEnt
            ? `${nlEnt.differenz > 0 ? '+' : ''}${NF.format(nlEnt.differenz)}`
            : 'keine Angabe'),
        el('div', { class: 'basis' }, nlEnt
          ? `${nlEnt.von_jahr}–${nlEnt.bis_jahr} · `
            + `${nlEnt.prozent > 0 ? '+' : ''}${NF1.format(nlEnt.prozent)} %`
          : '')),
      kennzahl(st ? `Studierende (WS ${st.jahr}/${String(st.jahr + 1).slice(2)})`
        : 'Studierende', st ? st.studierende : null),
      kennzahl(sch ? `Schülerinnen und Schüler (${sch.jahr})`
        : 'Schülerinnen und Schüler', sch ? sch.schueler : null)));

    const faecher = (g.studierende || {}).faechergruppen || [];
    if (faecher.length) {
      const ftab = el('table', { class: 'daten' },
        el('tr', {},
          el('th', {}, 'Fächergruppe'),
          el('th', { class: 'num' }, 'Studierende')));
      for (const f of faecher.slice(0, 6)) {
        ftab.append(el('tr', {},
          el('td', {}, f.fach),
          el('td', { class: 'num' }, NF.format(f.studierende))));
      }
      kreisTeile.push(ftab);
    }
  }

  const reihe = (g.umsatz || {}).reihe || [];
  let tab = null;
  if (reihe.length > 1) {
    tab = el('table', { class: 'daten' },
      el('tr', {},
        el('th', {}, 'Jahr'),
        el('th', { class: 'num' }, 'USt-Pflichtige Gastgewerbe'),
        el('th', { class: 'num' }, 'Umsatz je Pflichtigem (€)')));
    for (const z of reihe.slice(-8)) {
      tab.append(el('tr', {},
        el('td', {}, String(z.jahr)),
        el('td', { class: 'num' },
          z.pflichtige === null ? '—' : NF.format(z.pflichtige)),
        el('td', { class: 'num' },
          z.je_pflichtigem_eur === null ? '—' : NF.format(z.je_pflichtigem_eur))));
    }
  }

  // Gemeindewerte (bundesweit): Beschäftigte am Arbeitsort,
  // Übernachtungen, Arbeitslose — je Gemeinde statt je Kreis.
  const gem = g.gemeinde || null;
  const gemTeile = [];
  if (gem) {
    const b = (gem.beschaeftigte || {}).aktuell;
    const t = (gem.tourismus || {}).aktuell;
    const a = (gem.arbeitslose || {}).aktuell;
    gemTeile.push(el('h4', {},
      `Gemeindewerte: ${gem.name || gem.ags}`
      + (gem.ebene === 'kreisfreie Stadt' ? ' (kreisfreie Stadt)' : '')
      + (gem.ebene === 'Kreis (Rückfall)' ? ' (ganzer Landkreis — Rückfall)' : '')));
    gemTeile.push(el('div', { class: 'kennzahlen' },
      el('div', { class: 'kennzahl' },
        el('div', { class: 'titel' }, 'Beschäftigte am Arbeitsort'),
        el('div', { class: `wert${b ? '' : ' fehlt'}` },
          b ? NF.format(b.beschaeftigte) : 'keine Angabe'),
        el('div', { class: 'basis' }, b
          ? `Stichtag 30.06.${b.jahr}`
            + ((gem.beschaeftigte || {}).veraenderung_5j_prozent !== null
               && (gem.beschaeftigte || {}).veraenderung_5j_prozent !== undefined
              ? ` · ${gem.beschaeftigte.veraenderung_5j_prozent > 0 ? '+' : ''}`
                + `${gem.beschaeftigte.veraenderung_5j_prozent} % in 5 Jahren`
              : '')
          : '')),
      kennzahl(t ? `Übernachtungen (${t.jahr})` : 'Übernachtungen',
        t ? t.uebernachtungen : null),
      kennzahl(t ? `Beherbergungsbetriebe (${t.jahr})` : 'Beherbergungsbetriebe',
        t ? t.betriebe : null),
      kennzahl(a ? `Arbeitslose (Ø ${a.jahr})` : 'Arbeitslose',
        a ? a.arbeitslose : null)));
    // Bau-Pipeline: genehmigte gegen fertiggestellte Wohnungen — die
    // kommende Nachfrage, die der eingefrorene Zensus-Neubauhinweis
    // nicht mehr sehen kann.
    const bg = (gem.baugenehmigungen || {}).aktuell;
    const bf = (gem.baufertigstellungen || {}).aktuell;
    if (bg || bf) {
      gemTeile.push(el('div', { class: 'kennzahlen' },
        kennzahl(bg ? `Genehmigte Wohnungen (${bg.jahr})` : 'Genehmigte Wohnungen',
          bg ? bg.wohnungen : null),
        kennzahl(bf ? `Fertiggestellte Wohnungen (${bf.jahr})` : 'Fertiggestellte Wohnungen',
          bf ? bf.wohnungen : null),
        el('div', { class: 'kennzahl' },
          el('div', { class: 'titel' }, 'Bau-Pipeline (genehmigt − fertig)'),
          el('div', {
            class: `wert${bg && bf && bg.wohnungen !== null && bf.wohnungen !== null ? '' : ' fehlt'}`,
          }, bg && bf && bg.wohnungen !== null && bf.wohnungen !== null && bg.jahr === bf.jahr
            ? `${bg.wohnungen - bf.wohnungen > 0 ? '+' : ''}${NF.format(bg.wohnungen - bf.wohnungen)}`
            : 'keine Angabe'),
          el('div', { class: 'basis' },
            bg && bf && bg.jahr === bf.jahr
              ? `Jahr ${bg.jahr} · berechnet, Wohngebäude inkl. Wohnheime`
              : 'nur bei gleichem Berichtsjahr berechnet'))));
      const breihe = ((gem.baugenehmigungen || {}).reihe || []);
      const freihe = ((gem.baufertigstellungen || {}).reihe || []);
      if (breihe.length > 1 || freihe.length > 1) {
        const fmap = Object.fromEntries(freihe.map((z) => [z.jahr, z]));
        const btab = el('table', { class: 'daten' },
          el('tr', {},
            el('th', {}, 'Jahr'),
            el('th', { class: 'num' }, 'Wohnungen genehmigt'),
            el('th', { class: 'num' }, 'Wohnungen fertiggestellt')));
        for (const z of breihe.slice(-8)) {
          const f = fmap[z.jahr];
          btab.append(el('tr', {},
            el('td', {}, String(z.jahr)),
            el('td', { class: 'num' },
              z.wohnungen === null ? '—' : NF.format(z.wohnungen)),
            el('td', { class: 'num' },
              f && f.wohnungen !== null ? NF.format(f.wohnungen) : '—')));
        }
        gemTeile.push(btab);
      }
    }
    // Hebesätze: der einzige harte Kostenfaktor, der gemeindescharf ist.
    const hs = (gem.hebesaetze || {}).aktuell;
    const hv = (gem.hebesaetze || {}).vergleich;
    if (hs) {
      gemTeile.push(el('h4', {}, 'Steuerlast der Gemeinde'));
      gemTeile.push(el('div', { class: 'kennzahlen' },
        el('div', { class: 'kennzahl' },
          el('div', { class: 'titel' }, `Gewerbesteuer-Hebesatz (${hs.jahr})`),
          el('div', { class: `wert${hs.gewerbesteuer_hebesatz === null ? ' fehlt' : ''}` },
            hs.gewerbesteuer_hebesatz === null
              ? 'keine Angabe' : `${NF.format(hs.gewerbesteuer_hebesatz)} %`),
          el('div', { class: 'basis' }, hv
            ? `Bund ${hv.bund} % (${hv.bund_jahr}) · `
              + `${hv.differenz_punkte > 0 ? '+' : ''}${hv.differenz_punkte} Punkte`
            : '')),
        kennzahl(`Grundsteuer B (${hs.jahr})`, hs.grundsteuer_b_hebesatz, '%'),
        kennzahl('Steuereinnahmekraft', hs.steuereinnahmekraft_eur, '€')));
      const hreihe = (gem.hebesaetze || {}).reihe || [];
      if (hreihe.length > 1) {
        const htab = el('table', { class: 'daten' },
          el('tr', {},
            el('th', {}, 'Jahr'),
            el('th', { class: 'num' }, 'Gewerbesteuer'),
            el('th', { class: 'num' }, 'Grundsteuer B')));
        for (const z of hreihe.slice(-8)) {
          htab.append(el('tr', {},
            el('td', {}, String(z.jahr)),
            el('td', { class: 'num' }, z.gewerbesteuer_hebesatz === null
              ? '—' : `${NF.format(z.gewerbesteuer_hebesatz)} %`),
            el('td', { class: 'num' }, z.grundsteuer_b_hebesatz === null
              ? '—' : `${NF.format(z.grundsteuer_b_hebesatz)} %`)));
        }
        gemTeile.push(htab);
      }
    }
    const br = (gem.beschaeftigte || {}).reihe || [];
    if (br.length > 1) {
      const btab = el('table', { class: 'daten' },
        el('tr', {},
          el('th', {}, 'Stichtag 30.06.'),
          el('th', { class: 'num' }, 'Beschäftigte am Arbeitsort')));
      for (const z of br.slice(-8)) {
        btab.append(el('tr', {},
          el('td', {}, String(z.jahr)),
          el('td', { class: 'num' },
            z.beschaeftigte === null ? '—' : NF.format(z.beschaeftigte))));
      }
      gemTeile.push(btab);
    }
    for (const h of gem.hinweise || []) {
      gemTeile.push(el('div', { class: 'hinweis-klein' }, h));
    }
  }

  setInhalt(id, kz, tab, ...kreisTeile, ...gemTeile,
    ...(g.hinweise || []).map((h) => hinweisZeile(h)),
    ...warnungen(d.warnings || []),
    el('div', { class: 'pflegeleiste' },
      el('button', { onclick: () => entferneGenesisZugang(ags) },
        'Gespeicherte Kennung entfernen')));
  setQuelle(id, d.provenance);
}

/* Block 2b — Viertel-Steckbrief (Indikatorenatlas München). Der Zensus zeigt
   das Umfeld fein, aber als Momentaufnahme 2022 — hier steht die Entwicklung
   des Stadtbezirks über die Jahre, jeweils gegen den Stadtwert. */
function zeigeIndikatoren(d) {
  const id = 'indikatoren';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const dat = d.data;
  if (!dat) {
    setStatus(id, 'leer', 'nur München');
    setInhalt(id, ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  const zeilen = dat.indikatoren || [];
  if (!zeilen.length) {
    setStatus(id, 'leer', 'keine Reihen');
    setInhalt(id, ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  setStatus(id, 'ok', dat.bezirk || 'Stadtwerte');

  const vorz = (x, f) => (x > 0 ? `+${f.format(x)}` : f.format(x));
  const fmtWert = (z, t) => {
    if (!t) return '—';
    const f = z.einheit === 'Ew. je km²' ? NF : NF1;
    return `${f.format(t.wert)}`;
  };
  const fmtTrend = (z, t) => {
    if (!t || t.delta === null || t.delta === undefined) return '—';
    const f = z.einheit === 'Ew. je km²' ? NF : NF1;
    return `${vorz(t.delta, f)} seit ${t.von_jahr}`;
  };

  const tab = el('table', { class: 'daten' },
    el('tr', {},
      el('th', {}, 'Kennzahl'),
      el('th', { class: 'num' }, dat.bezirk || 'Bezirk'),
      el('th', { class: 'num' }, 'Trend (~5 J.)'),
      el('th', { class: 'num' }, 'Stadt München'),
      el('th', { class: 'num' }, 'Jahr')));
  for (const z of zeilen) {
    const t = z.bezirk;
    tab.append(el('tr', { title: z.deutung || '' },
      el('td', {},
        el('span', { class: 'haupt' }, `${z.label}`),
        el('span', { class: 'neben' }, ` (${z.einheit})`)),
      el('td', { class: 'num' }, fmtWert(z, t)),
      el('td', { class: 'num' }, fmtTrend(z, t)),
      el('td', { class: 'num' }, fmtWert(z, z.stadt)),
      el('td', { class: 'num' },
        t ? String(t.jahr) : (z.stadt ? String(z.stadt.jahr) : '—'))));
  }

  // Die Gastro-Übersetzung der auffälligsten Zeile: Einpersonenhaushalte.
  const einp = zeilen.find((z) => z.schluessel === 'einpersonenhaushalte');
  const deutung = [];
  if (einp && einp.bezirk && einp.stadt) {
    const diff = einp.bezirk.wert - einp.stadt.wert;
    deutung.push(el('div', { class: 'notiz' },
      `${NF1.format(einp.bezirk.wert)} % der Haushalte im Bezirk sind `
      + 'Einpersonenhaushalte'
      + (Math.abs(diff) >= 1
        ? ` — ${NF1.format(Math.abs(diff))} Punkte ${diff > 0 ? 'über' : 'unter'} dem Stadtwert. `
        : ' — nahe am Stadtwert. ')
      + (diff > 0
        ? 'Singles essen häufiger auswärts: tendenziell mehr Ausgeh-Publikum.'
        : 'Eher Familien-Viertel: Mittagsgeschäft und Familientauglichkeit zählen mehr.')));
  }

  setInhalt(id,
    dat.bezirk
      ? el('div', { class: 'notiz' },
        `Stadtbezirk ${dat.bezirk} — Werte im Zeitverlauf, Spalte „Trend" `
        + 'gegen den Stand vor ~5 Jahren (gewählter Wert).')
      : null,
    tab, ...deutung,
    ...(dat.hinweise || []).map((h) => hinweisZeile(h)),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* Block 4e — Gastro-Dynamik aus der OSM-Historie (ohsome). Jahresreihe der
   Gastro-Objekte im Umkreis, jeweils zum 1. Januar. Die eine Grenze über
   allem: die Kurve misst die OSM-Datenbank, nicht direkt die Wirklichkeit —
   als Mehrjahres-Trend brauchbar, als Absolutzahl je Jahr nicht. */
function zeigeDynamik(d) {
  const id = 'dynamik';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const dat = d.data || {};
  const reihe = dat.reihe || [];
  if (!reihe.length) {
    setStatus(id, 'leer', 'keine Reihe');
    setInhalt(id, ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  setStatus(id, 'ok', `${reihe[0].jahr}–${reihe[reihe.length - 1].jahr}`);

  const v = dat.veraenderung;
  const vorz = (x, f) => (x > 0 ? `+${f.format(x)}` : f.format(x));
  const kz = v ? el('div', { class: 'kennzahlen' },
    kennzahl(`Gastro-Objekte 1.1.${v.von_jahr}`, v.von),
    kennzahl(`Gastro-Objekte 1.1.${v.bis_jahr}`, v.bis),
    el('div', { class: 'kennzahl' },
      el('div', { class: 'titel' }, 'Veränderung'),
      el('div', { class: 'wert' }, vorz(v.absolut, NF)
        + (v.prozent !== null && v.prozent !== undefined
          ? ` (${vorz(v.prozent, NF1)} %)` : '')),
      el('div', { class: 'basis' }, 'OSM-Objekte, nicht zwingend Betriebe'))) : null;

  const max = Math.max(1, ...reihe.map((r) => r.gastro));
  const balken = el('div', { id: 'dynamik-balken', style: 'display:flex;align-items:flex-end;gap:3px;height:80px;margin:8px 0 2px;' },
    reihe.map((r) => el('div', {
      title: `1.1.${r.jahr}: ${NF.format(r.gastro)} Gastro-Objekte`
        + (r.schnellgastronomie !== null && r.schnellgastronomie !== undefined
          ? `, davon ${NF.format(r.schnellgastronomie)} Schnellgastronomie` : ''),
      style: `flex:1;background:var(--akzent);opacity:.75;border-radius:2px 2px 0 0;`
        + `height:${Math.max(3, (r.gastro / max) * 100)}%;`,
    })));
  const achse = el('div', { style: 'display:flex;justify-content:space-between;font-size:11px;color:#5b6570;' },
    el('span', {}, String(reihe[0].jahr)), el('span', {}, String(reihe[reihe.length - 1].jahr)));

  const tab = el('table', { class: 'daten' },
    el('tr', {}, el('th', {}, 'Stichtag 1. Januar'),
      el('th', { class: 'num' }, 'Gastro gesamt'),
      el('th', { class: 'num' }, 'davon Schnellgastronomie')));
  for (const r of reihe) {
    tab.append(el('tr', {}, el('td', {}, String(r.jahr)),
      el('td', { class: 'num' }, NF.format(r.gastro)),
      el('td', { class: 'num' },
        r.schnellgastronomie === null || r.schnellgastronomie === undefined
          ? '—' : NF.format(r.schnellgastronomie))));
  }

  setInhalt(id, kz, balken, achse, tab,
    ...(dat.hinweise || []).map((h) => el('div', { class: 'warnung' }, h)),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* Block 3c — Kreisprofil aus dem Regionalatlas: Tourismus, Erwerbstätige am
   Arbeitsort (Tagesbevölkerungs-Näherung), Arbeitsmarkt, Bevölkerungsbewegung.
   Kreiswerte mit je eigenem Datenjahr; Land und Bund als Maßstab daneben. */
async function ladeKreisprofil(ags, lauf) {
  if (!ags) {
    setStatus('kreisprofil', 'leer', 'kein Gemeindeschlüssel');
    setInhalt('kreisprofil', el('div', { class: 'notiz' },
      'Ohne Gemeindeschlüssel (aus dem Zensusblock) lässt sich kein Kreiswert '
      + 'zuordnen.'));
    return;
  }
  try {
    const d = await hole('/api/kreisprofil', { ags });
    if (lauf !== state.ladeLauf) return;
    state.daten.kreisprofil = d;
    zeigeKreisprofil(d);
  } catch (e) {
    if (lauf === state.ladeLauf) zeigeBlockFehler('kreisprofil', e);
  }
}

function zeigeKreisprofil(d) {
  const id = 'kreisprofil';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const k = d.data;
  if (!k || !(k.indikatoren || []).length) {
    setStatus(id, 'leer', 'kein Wert');
    setInhalt(id, ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  setStatus(id, 'ok', 'geladen');

  const fmt = (v, stellen) => (v === null || v === undefined
    ? '—' : nfFest(stellen ?? 1).format(v));
  const gb = k.gebiete || {};
  const tab = el('table', { class: 'daten' },
    el('tr', {},
      el('th', {}, 'Kennzahl'),
      el('th', { class: 'num' }, gb.kreis?.name || 'Kreis'),
      el('th', { class: 'num' }, gb.land?.name || 'Land'),
      el('th', { class: 'num' }, gb.bund?.name || 'Deutschland'),
      el('th', { class: 'num' }, 'Jahr')));
  let letztesThema = null;
  for (const i of k.indikatoren) {
    if (i.thema !== letztesThema) {
      letztesThema = i.thema;
      tab.append(el('tr', { class: 'gruppe' },
        el('th', { colspan: 5 }, i.thema)));
    }
    const einheit = i.einheit ? ` ${i.einheit}` : '';
    tab.append(el('tr', {},
      el('td', {}, i.titel),
      el('td', { class: 'num' }, fmt(i.kreis, i.stellen) + einheit),
      el('td', { class: 'num' }, fmt(i.land, i.stellen) + einheit),
      el('td', { class: 'num' }, fmt(i.bund, i.stellen) + einheit),
      el('td', { class: 'num' }, i.jahr)));
  }

  // Die eine Zahl, die den Charakter des Kreises am schnellsten erklärt:
  // über 1.000 Erwerbstätige je 1.000 Erwerbsfähige = Einpendler-Magnet.
  const et = k.indikatoren.find((i) => i.schluessel === 'et_je_1000_ew');
  const deutung = [];
  if (et && et.kreis !== null && et.kreis !== undefined) {
    deutung.push(el('div', { class: 'notiz' },
      et.kreis > 1000
        ? `Im Kreis kommen ${NF.format(Math.round(et.kreis))} Erwerbstätige am `
          + 'Arbeitsort auf 1.000 Erwerbsfähige — mehr Arbeitsplätze als '
          + 'Erwerbsfähige, also Einpendler: tagsüber ist hier mehr Publikum, '
          + 'als der Zensus (Wohnbevölkerung) zeigt.'
        : `Im Kreis kommen ${NF.format(Math.round(et.kreis))} Erwerbstätige am `
          + 'Arbeitsort auf 1.000 Erwerbsfähige — ein Teil der Wohnbevölkerung '
          + 'arbeitet also außerhalb und fehlt tagsüber als Publikum.'));
  }

  setInhalt(id, tab, ...deutung,
    el('div', { class: 'warnung' },
      'Kreiswerte — innerhalb einer Großstadt unterscheiden sie keine Viertel. '
      + 'Jede Kennzahl trägt ihr eigenes Datenjahr (rechte Spalte).'),
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

function zeigeGtfs(d) {
  const g = d.data;
  if (!g) {
    setStatus('gtfs', 'leer', 'nicht importiert');
    setInhalt('gtfs', ...warnungen(d.warnings));
    setQuelle('gtfs', d.provenance);
    return;
  }
  setStatus('gtfs', 'ok', 'geladen');
  const kz = el('div', { class: 'kennzahlen' },
    kennzahl(`Abfahrten am ${g.referenzdatum}`, g.abfahrten_gesamt),
    kennzahl('davon 6–24 Uhr', g.abfahrten_06_24),
    kennzahl(`davon ${g.mittagsfenster || '11–14 Uhr'}`, g.abfahrten_mittag),
    kennzahl(`davon ${g.abendfenster || '17–22 Uhr'}`, g.abfahrten_abend),
    kennzahl(`davon ${g.nachtfenster || '22–1 Uhr'}`, g.abfahrten_nacht),
    kennzahl('bediente Haltestellen', g.haltestellen_gesamt),
    kennzahl('Spitzenstunde', g.spitzenstunde ? g.spitzenstunde.abfahrten : null));

  // Balken 6–24 Uhr, Spec §4.4
  const werte = Object.entries(g.abfahrten_je_stunde).filter(([h]) => +h >= 6 && +h < 24);
  const max = Math.max(1, ...werte.map(([, v]) => v));
  const balken = el('div', { style: 'display:flex;align-items:flex-end;gap:2px;height:90px;margin:10px 0 2px;' });
  for (const [h, v] of werte) {
    balken.append(el('div', {
      title: `${h}:00 Uhr — ${NF.format(v)} Abfahrten`,
      style: `flex:1;background:#4a8fbd;border-radius:2px 2px 0 0;height:${Math.max(2, (v / max) * 100)}%;`,
    }));
  }
  const achse = el('div', { style: 'display:flex;justify-content:space-between;font-size:11px;color:#5b6570;' },
    el('span', {}, '6 Uhr'), el('span', {}, '15 Uhr'), el('span', {}, '23 Uhr'));

  const haltTab = el('table', { class: 'daten' },
    el('tr', {}, el('th', {}, 'Haltestelle'), el('th', { class: 'num' }, 'm'),
      el('th', { class: 'num' }, 'Abfahrten')));
  for (const h of g.haltestellen.filter((h) => h.abfahrten > 0).slice(0, 12)) {
    haltTab.append(el('tr', {},
      el('td', {}, `${h.name}${h.linien.length ? ` (${h.linien.slice(0, 8).join(', ')})` : ''}`),
      el('td', { class: 'num' }, NF.format(h.distanz_m)),
      el('td', { class: 'num' }, NF.format(h.abfahrten))));
  }

  setInhalt('gtfs', kz,
    el('h3', { class: 'hinweis-klein' }, `Verteilung über den Tag (${g.referenz_wochentag})`),
    balken, achse, haltTab, ...warnungen(d.warnings));
  setQuelle('gtfs', d.provenance);
}

function zeigeLinks(d) {
  setStatus('quellen', 'ok', 'geladen');
  const teile = [];

  const b = d.bodenrichtwerte;
  setzeBrwEbene(b.bundesland_code);
  setzeZusatzebenen(b.bundesland_code);
  const brw = brwBlock(b);
  document.getElementById('block-quellen')?.before(brw);

  teile.push(el('h3', { class: 'hinweis-klein' }, 'Bodenrichtwert-Portale'));
  if (b.hinweis) teile.push(el('div', { class: 'notiz' }, b.hinweis));
  teile.push(el('ul', { class: 'liste' }, b.links.map((l) => el('li', {},
    el('span', { class: 'haupt' },
      el('a', { href: l.url, target: '_blank', rel: 'noopener' }, l.titel),
      el('div', { class: 'meta' }, l.status))))));
  teile.push(el('div', { class: 'notiz' }, b.quelle));

  for (const gruppe of d.weiterfuehrend) {
    teile.push(el('h3', { class: 'hinweis-klein' }, gruppe.gruppe));
    if (gruppe.hinweis) teile.push(el('div', { class: 'notiz' }, gruppe.hinweis));
    teile.push(el('ul', { class: 'liste' }, gruppe.eintraege.map((e) => el('li', {},
      el('span', { class: 'haupt' },
        el('a', { href: e.url, target: '_blank', rel: 'noopener' }, e.titel),
        e.beschreibung ? el('div', { class: 'meta' }, e.beschreibung) : null,
        e.warnung ? el('div', { class: 'warnung' }, e.warnung) : null)))));
  }
  setInhalt('quellen', ...teile);
  setQuelle('quellen', {
    source: 'Linksammlung aus spec-standort-datenterminal.md §4.6 und notizen-standort-flaeche.md',
    license: 'Verweise; es werden keine Daten dieser Anbieter abgerufen oder gespeichert.',
  });
}

/* ---------------------------------------------------------- Vergleich */

async function merken() {
  if (state.lat === null) { alert('Erst einen Punkt in der Karte wählen.'); return; }
  const vorschlag = state.daten.adresse?.data?.display_name?.split(',').slice(0, 2).join(',')
    || `${state.lat}, ${state.lon}`;
  const label = prompt('Bezeichnung für diesen Standort:', vorschlag);
  if (!label) return;
  const btn = document.getElementById('btn-merken');
  btn.disabled = true; btn.textContent = 'speichert …';
  try {
    const r = await fetch('/api/points', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label, lat: state.lat, lon: state.lon, radius: state.radius }),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    await zeigeVergleich();
  } catch (e) {
    alert(`Konnte den Punkt nicht merken: ${e.message}`);
  } finally {
    btn.disabled = false; btn.textContent = 'Punkt merken';
  }
}

/* Spalten, bei denen ein hoher Wert im Vergleich hervorgehoben wird.
   Bewusst neutral: hervorgehoben wird nur der Höchstwert, es wird nicht bewertet.
   „Wettbewerber je 1.000 Einwohner" steht absichtlich nicht hier — dort wäre der
   Höchstwert die dichteste Konkurrenz, und die zu markieren liest sich wie ein Lob. */
const HOCH_IST_AUFFAELLIG = new Set([
  'einwohner', 'frequenzbringer', 'haltestellen', 'linien', 'abfahrten',
  'abfahrten_je_einwohner', 'abfahrten_mittag', 'mittagsanteil',
]);

/* Sichtbare Spaltengruppen. Die Tabelle ist auf 36 Spalten gewachsen; ohne
   Gruppen scrollt man an der Bezeichnung vorbei und findet nichts wieder.
   Abgeschaltet werden nur ganze Gruppen — einzelne Spalten würden die Tabelle
   in beliebig viele Zustände zerfallen lassen. */
const GRUPPEN_SPEICHER = 'gastroviewer.vergleichsgruppen';
let sichtbareGruppen = null;

function ladeGruppenwahl(gruppen) {
  if (sichtbareGruppen) return sichtbareGruppen;
  let gemerkt = null;
  try {
    gemerkt = JSON.parse(localStorage.getItem(GRUPPEN_SPEICHER) || 'null');
  } catch { gemerkt = null; }
  const gueltig = new Set(gruppen.map((g) => g.key));
  sichtbareGruppen = new Set(
    Array.isArray(gemerkt) && gemerkt.every((k) => gueltig.has(k))
      ? gemerkt
      : gruppen.filter((g) => g.vorgabe).map((g) => g.key),
  );
  // Feste Gruppen lassen sich nicht abwählen — ohne Bezeichnung ist die
  // Tabelle nicht lesbar.
  for (const g of gruppen) if (g.fest) sichtbareGruppen.add(g.key);
  return sichtbareGruppen;
}

function merkeGruppenwahl() {
  localStorage.setItem(GRUPPEN_SPEICHER, JSON.stringify([...sichtbareGruppen]));
}

/* Eigene Note und Notiz. Das Werkzeug bewertet bewusst nicht und stellt keine
   Rangfolge auf — der Nutzer darf und soll das aber. Gespeichert wird beim
   Verlassen des Feldes, nicht bei jedem Tastendruck. */
async function speichereEigenes(id, zeile) {
  try {
    const r = await fetch(`/api/points/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        notiz: zeile.notiz || null,
        bewertung: zeile.bewertung === '' || zeile.bewertung === null
          ? null : Number(zeile.bewertung),
      }),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
  } catch (e) {
    // Sonst ginge eine eingetippte Notiz bei Server-Schluckauf kommentarlos verloren.
    alert(`Notiz/Note konnte nicht gespeichert werden: ${e.message}`);
  }
}

function eigenesFeld(z, key) {
  if (key === 'bewertung') {
    const aus = el('select', {
      'aria-label': 'Eigene Note',
      onchange: (ev) => {
        z.bewertung = ev.target.value === '' ? null : Number(ev.target.value);
        speichereEigenes(z.id, z);
      },
    });
    for (const [wert, beschriftung] of [['', '—'], ['1', '1 sehr gut'], ['2', '2 gut'],
      ['3', '3 mittel'], ['4', '4 schwach'], ['5', '5 ungeeignet']]) {
      aus.append(el('option', {
        value: wert, selected: String(z.bewertung ?? '') === wert,
      }, beschriftung));
    }
    return aus;
  }
  return el('input', {
    type: 'text',
    value: z.notiz || '',
    maxlength: '2000',
    placeholder: 'eigene Notiz …',
    'aria-label': 'Eigene Notiz',
    onchange: (ev) => { z.notiz = ev.target.value; speichereEigenes(z.id, z); },
  });
}

async function zeigeVergleich() {
  const ziel = document.getElementById('vergleich-inhalt');
  let d;
  try {
    const r = await fetch('/api/points/vergleich');
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    d = await r.json();
  } catch (e) {
    ziel.replaceChildren(fehlerbox({ message: e.message }));
    document.getElementById('vergleich-dialog').showModal();
    return;
  }
  const gruppen = d.gruppen || [];
  const sichtbar = ladeGruppenwahl(gruppen);

  if (!d.zeilen.length) {
    ziel.replaceChildren(el('p', { class: 'hinweis-klein' },
      'Noch kein Punkt gemerkt. „Punkt merken" legt den aktuellen Standort ab.'));
    document.getElementById('vergleich-dialog').showModal();
    return;
  }

  const spalten = d.spalten.filter((c) => sichtbar.has(c.gruppe));

  /* Schalterleiste: je Gruppe ein Häkchen mit der Zahl ihrer Spalten. */
  const schalter = el('div', { class: 'gruppenwahl' },
    el('span', { class: 'gruppenwahl-titel' }, 'Spalten:'),
    gruppen.map((g) => {
      const anzahl = d.spalten.filter((c) => c.gruppe === g.key).length;
      const box = el('input', {
        type: 'checkbox',
        checked: sichtbar.has(g.key),
        disabled: !!g.fest,
        id: `gruppe-${g.key}`,
        onchange: (ev) => {
          if (ev.target.checked) sichtbar.add(g.key); else sichtbar.delete(g.key);
          merkeGruppenwahl();
          zeigeVergleich();
        },
      });
      return el('label', { class: g.fest ? 'fest' : '', for: `gruppe-${g.key}` },
        box, ` ${g.titel} (${anzahl})`);
    }),
    el('span', { class: 'gruppenwahl-zahl' },
      `${spalten.length} von ${d.spalten.length} Spalten · CSV enthält immer alle`));

  const beste = {};
  for (const key of HOCH_IST_AUFFAELLIG) {
    const werte = d.zeilen.map((z) => z[key]).filter((v) => typeof v === 'number');
    if (werte.length > 1) beste[key] = Math.max(...werte);
  }

  const tab = el('table', { class: 'vergleich-tabelle' });

  /* Gruppenzeile über den Spaltenköpfen — sonst weiß man nach dem dritten
     Scrollschritt nicht mehr, worauf man schaut. */
  const gruppenzeile = el('tr', { class: 'gruppenzeile' });
  for (const g of gruppen) {
    const n = spalten.filter((c) => c.gruppe === g.key).length;
    if (n) gruppenzeile.append(el('th', { colspan: String(n), class: `gr-${g.key}` }, g.titel));
  }
  gruppenzeile.append(el('th', {}, ''));
  tab.append(gruppenzeile);

  tab.append(el('tr', {}, spalten.map((c) => el('th', {}, c.titel)), el('th', {}, '')));

  for (const z of d.zeilen) {
    const tr = el('tr', {});
    for (const c of spalten) {
      /* Die beiden einzigen Felder, die der Nutzer selbst füllt. Sie werden
         direkt in der Tabelle bearbeitet — ein Dialog dafür wäre ein Umweg. */
      if (c.key === 'bewertung' || c.key === 'notiz') {
        tr.append(el('td', { class: 'eigen' }, eigenesFeld(z, c.key)));
        continue;
      }
      const v = z[c.key];
      const num = typeof v === 'number';
      const klassen = [num ? 'num' : 'text'];
      if (beste[c.key] !== undefined && v === beste[c.key]) klassen.push('best');
      tr.append(el('td', {
        class: klassen.join(' '),
        title: v === null || v === undefined ? '' : String(v),
      }, v === null || v === undefined ? '—'
         : num ? (c.stellen === undefined ? NF1 : nfFest(c.stellen)).format(v)
         : String(v)));
    }
    tr.append(el('td', { class: 'aktionen' },
      el('a', {
        class: 'knopf-link', href: `/bericht?punkt=${z.id}`,
        target: '_blank', rel: 'noopener',
        title: 'Druckbarer Bericht zu diesem Punkt — PDF über die Druckfunktion des Browsers',
      }, 'Bericht'),
      el('button', {
        title: 'Alle Quellen erneut abfragen (am Cache vorbei) und Veränderungen zeigen',
        onclick: () => neuPruefen(z),
      }, 'neu prüfen'),
      el('button', {
        title: 'Nur die OSM-Gastronomie gegen den gespeicherten Stand halten — '
          + 'schnell, ohne den Punkt zu verändern',
        onclick: () => waechterPruefen(z),
      }, 'Wächter'),
      el('button', {
        onclick: async () => {
          try {
            await fetch(`/api/points/${z.id}`, { method: 'DELETE' });
          } catch { /* Der Neuaufbau unten zeigt den echten Zustand. */ }
          zeigeVergleich();
        },
      }, 'löschen')));
    tab.append(tr);
  }

  /* Überschneidende Einzugsgebiete sind keine unabhängigen Optionen. */
  const paare = ueberlappungen(d.zeilen);
  const ueberlappungsBox = paare.length
    ? el('div', { class: 'warnung' },
      el('strong', {}, 'Einzugsgebiete überschneiden sich: '),
      ...paare.map((p) => el('div', { class: 'legende-zeile' },
        `${p.a} ↔ ${p.b} (Abstand ${NF.format(p.distanz_m)} m, Kreise `
        + `überlappen um ${NF.format(p.um_m)} m) `,
        el('button', {
          class: 'kein-druck',
          title: 'Einwohner in beiden Umkreisen über das Zensusgitter zählen',
          onclick: (ev) => kannibalisierungRechnen(p, ev.target),
        }, 'Gemeinsame Einwohner rechnen'))),
      el('div', { class: 'hinweis-klein' },
        'Diese Kandidaten teilen sich einen Teil derselben Einwohner — die '
        + 'Kartenebene „Gemerkte Punkte" zeigt es. Ob das stört, hängt vom '
        + 'Konzept ab; die Geometrie sagt nur, dass es so ist.'))
    : null;

  // .filter(Boolean): rankingBereich() liefert unter zwei Punkten null, und
  // replaceChildren würde daraus das sichtbare Wort „null" machen.
  ziel.replaceChildren(...[
    schalter,
    pflegeleiste(d.zeilen),
    ueberlappungsBox,
    el('div', { class: 'tabelle-rahmen' }, tab),
    rankingBereich(d),
  ].filter(Boolean));
  // Die Kartenebene „Gemerkte Punkte" spiegelt den Bestand — nach Merken
  // oder Löschen (beides landet hier) wird sie nachgeführt.
  ladePunkteEbene();
  document.getElementById('vergleich-dialog').showModal();
}

/* ------------------------------------- Datensicherung und Pflegelauf */

/* Sichern lädt alle Punkte samt Verlauf als eine JSON-Datei herunter;
   Einspielen liest so eine Datei wieder ein (Dubletten werden erkannt).
   „Alle neu prüfen" ist der monatliche Pflegelauf in einem Klick — mit
   Kostenansage, denn je Punkt läuft u. a. eine Overpass-Abfrage. */
function pflegeleiste(zeilen) {
  const dateiwahl = el('input', {
    type: 'file', accept: 'application/json,.json', hidden: true,
    onchange: async (ev) => {
      const datei = ev.target.files && ev.target.files[0];
      if (!datei) return;
      let daten;
      try {
        daten = JSON.parse(await datei.text());
      } catch {
        alert('Die Datei ist kein lesbares JSON.');
        return;
      }
      const r = await fetch('/api/points/import', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(daten),
      });
      const antwort = await r.json().catch(() => ({}));
      if (!r.ok) {
        alert(`Einspielen fehlgeschlagen: ${antwort.detail || `HTTP ${r.status}`}`);
        return;
      }
      alert(`Sicherung eingespielt: ${antwort.neu} Punkt(e) neu, `
        + `${antwort.uebersprungen} bereits vorhanden.`);
      zeigeVergleich();
    },
  });
  return el('div', { class: 'pflegeleiste' },
    el('a', {
      class: 'knopf-link', href: '/api/points/export',
      title: 'Alle gemerkten Punkte samt Verlauf und Notizen als eine Datei sichern',
    }, 'Sichern (Datei)'),
    el('button', { onclick: () => dateiwahl.click() }, 'Sicherung einspielen'),
    dateiwahl,
    zeilen.length > 1 ? el('button', {
      title: 'Alle gemerkten Punkte nacheinander neu prüfen (je Punkt u. a. eine Overpass-Abfrage)',
      onclick: () => alleNeuPruefen(zeilen),
    }, `alle ${zeilen.length} neu prüfen`) : null,
    ...duellWahl(zeilen));
}

/* Duell-Bericht: die Endauswahl ist fast immer ein Zweikampf. Zwei Punkte
   wählen, eine Druckseite Spalte an Spalte mit beiden Lagekarten. */
function duellWahl(zeilen) {
  if (zeilen.length < 2) return [];
  const wahl = (id, vorgabe) => el('select', { id },
    zeilen.map((z, i) => {
      const o = el('option', { value: String(z.id) }, z.label);
      if (i === vorgabe) o.selected = true;
      return o;
    }));
  const a = wahl('duell-a', 0);
  const b = wahl('duell-b', 1);
  return [
    el('span', { class: 'gruppenwahl-titel', style: 'margin-left:12px' }, 'Duell:'),
    a, el('span', {}, 'gegen'), b,
    el('button', {
      title: 'Druckseite: beide Kandidaten Spalte an Spalte, mit beiden Lagekarten',
      onclick: () => {
        if (a.value === b.value) { alert('Zwei verschiedene Punkte wählen.'); return; }
        window.open(`/duell?a=${a.value}&b=${b.value}`, '_blank', 'noopener');
      },
    }, 'Duell-Bericht'),
  ];
}

async function alleNeuPruefen(zeilen) {
  const sicher = confirm(
    `Alle ${zeilen.length} gemerkten Punkte jetzt neu prüfen?\n\n`
    + 'Das fragt je Punkt alle Quellen erneut ab (am Cache vorbei), darunter '
    + `je eine Overpass-Abfrage — insgesamt ${zeilen.length} Stück, nacheinander. `
    + 'Der bisherige Stand wandert jeweils in den Verlauf.');
  if (!sicher) return;
  const inhalt = document.getElementById('vergleich-inhalt');
  const box = el('div', { class: 'verlauf-ergebnis' });
  inhalt.prepend(box);
  const befunde = [];
  for (let i = 0; i < zeilen.length; i += 1) {
    const z = zeilen[i];
    box.replaceChildren(el('div', { class: 'laden' }),
      `Pflegelauf ${i + 1} von ${zeilen.length}: „${z.label}" …`);
    try {
      const r = await fetch(`/api/points/${z.id}/pruefung`, { method: 'POST' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      const n = d.veraendert.length + d.neue_betriebe.length
        + d.verschwundene_betriebe.length;
      befunde.push(`${z.label}: ${n ? `${n} Veränderung(en)` : 'unverändert'}`);
    } catch (e) {
      befunde.push(`${z.label}: fehlgeschlagen (${e.message})`);
    }
  }
  await zeigeVergleich();
  document.getElementById('vergleich-inhalt').prepend(
    el('div', { class: 'verlauf-ergebnis' },
      el('strong', {}, `Pflegelauf abgeschlossen (${zeilen.length} Punkte)`),
      el('ul', { class: 'liste' },
        befunde.map((b) => el('li', {}, el('span', { class: 'haupt' }, b)))),
      el('div', { class: 'hinweis-klein' },
        'Details je Punkt: „neu prüfen" am einzelnen Punkt zeigt die '
        + 'veränderten Kennzahlen und Betriebe.')));
}

/* --------------------------------- Kannibalisierungs-Check (Z6) */

/* Macht aus der Geometrie-Warnung eine Zahl: Einwohner, deren Zensuszelle
   in BEIDEN Umkreisen liegt. Zwei Zensus-Abfragen je Rechnung — deshalb
   auf Knopfdruck, nicht automatisch. */
async function kannibalisierungRechnen(paar, knopf) {
  const box = el('div', { class: 'verlauf-ergebnis' },
    el('div', { class: 'laden' }),
    `Zensuszellen für „${paar.a}" und „${paar.b}" werden gezählt …`);
  document.getElementById('vergleich-inhalt').prepend(box);
  if (knopf) knopf.disabled = true;
  let d;
  try {
    const r = await fetch(`/api/points/kannibalisierung?a=${paar.aId}&b=${paar.bId}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    d = await r.json();
  } catch (e) {
    box.replaceChildren(el('div', { class: 'fehlerbox' },
      `Kannibalisierungs-Check fehlgeschlagen: ${e.message}`));
    if (knopf) knopf.disabled = false;
    return;
  }
  if (knopf) knopf.disabled = false;
  if (!d.ueberlappung) {
    box.replaceChildren(el('strong', {}, 'Keine Überlappung'),
      el('div', {}, `${paar.a} und ${paar.b} überschneiden sich nicht mehr.`));
    return;
  }
  box.replaceChildren(
    el('strong', {}, `Kannibalisierung: ${d.a.label} ↔ ${d.b.label}`),
    el('div', { class: 'kennzahlen' },
      kennzahl('Gemeinsame Einwohner', d.gemeinsame_einwohner),
      kennzahl(`Anteil am Umkreis „${d.a.label}"`, d.anteil_an_a_prozent, '%', 1),
      kennzahl(`Anteil am Umkreis „${d.b.label}"`, d.anteil_an_b_prozent, '%', 1),
      kennzahl(`Einwohner „${d.a.label}" (${NF.format(d.a.radius_m)} m)`, d.einwohner_a),
      kennzahl(`Einwohner „${d.b.label}" (${NF.format(d.b.radius_m)} m)`, d.einwohner_b)),
    ...(d.hinweise || []).map((h) => hinweisZeile(h)),
    el('button', {
      class: 'kein-druck',
      onclick: (ev) => ev.target.closest('.verlauf-ergebnis').remove(),
    }, 'ausblenden'));
}

/* ------------------------------------- Veränderungs-Wächter (Z5) */

/* Der leichte Bruder von „neu prüfen": nur die OSM-Gastronomie wird gegen
   den gespeicherten Stand gehalten (eine Quelle, standardmäßig aus dem
   Cache), und der Punkt bleibt unverändert — Konkurrenzbeobachtung ohne
   Nebenwirkungen. Erst „neu prüfen" übernimmt den neuen Stand. */
async function waechterPruefen(z) {
  const inhalt = document.getElementById('vergleich-inhalt');
  const box = el('div', { class: 'verlauf-ergebnis' },
    el('div', { class: 'laden' }), `Wächter prüft „${z.label}" …`);
  inhalt.prepend(box);
  let d;
  try {
    const r = await fetch(`/api/points/${z.id}/waechter`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    d = await r.json();
  } catch (e) {
    box.replaceChildren(el('div', { class: 'fehlerbox' },
      `Wächter fehlgeschlagen: ${e.message}`));
    return;
  }
  if (!d.ok) {
    box.replaceChildren(el('div', { class: 'fehlerbox' },
      `Wächter: OSM nicht erreichbar (${d.fehler || '?'})`));
    return;
  }
  const teile = [el('strong', {}, `Wächter: ${d.label}`)];
  const delta = d.gastro_jetzt - d.gastro_gespeichert;
  teile.push(el('div', {},
    `Gastronomie im Umkreis: ${NF.format(d.gastro_gespeichert)} gespeichert → `
    + `${NF.format(d.gastro_jetzt)} jetzt`
    + (delta ? ` (${delta > 0 ? '+' : ''}${NF.format(delta)})` : ' (unverändert)')
    + (d.aus_cache ? ' · OSM-Stand aus dem Cache' : ' · frisch abgefragt')));
  const liste = (titel, eintraege) => (eintraege.length
    ? el('div', {},
      el('h3', { class: 'hinweis-klein' }, `${titel} (${eintraege.length})`),
      el('ul', { class: 'liste' }, eintraege.slice(0, 12).map((g) => el('li', {},
        el('span', { class: 'dist' },
          g.distanz_m === null || g.distanz_m === undefined
            ? '' : `${NF.format(g.distanz_m)} m`),
        el('span', { class: 'haupt' },
          el('div', { class: 'name' }, g.name || '(ohne Name)'),
          g.typ ? el('div', { class: 'meta' }, g.typ) : null)))))
    : null);
  teile.push(liste('Seit dem Speichern dazugekommen', d.neue_betriebe));
  teile.push(liste('Seit dem Speichern verschwunden', d.verschwundene_betriebe));
  if (!d.neue_betriebe.length && !d.verschwundene_betriebe.length) {
    teile.push(el('div', { class: 'notiz' },
      'Keine Veränderung im OSM-Gastro-Bestand seit dem gespeicherten Stand.'));
  }
  teile.push(el('div', { class: 'hinweis-klein' }, d.hinweis || ''));
  teile.push(el('button', {
    class: 'kein-druck',
    onclick: (ev) => ev.target.closest('.verlauf-ergebnis').remove(),
  }, 'ausblenden'));
  box.replaceChildren(...teile.filter(Boolean));
}

/* --------------------------------------------- Neu prüfen (Verlauf) */

/* Standortsuche dauert Monate. „Neu prüfen" fragt dieselben Quellen erneut ab
   (am Cache vorbei), legt den bisherigen Stand in den Verlauf und benennt die
   konkrete Veränderung: eröffnete Betriebe, verschwundene Betriebe, geänderte
   Kennzahlen. Ein verschwundener Betrieb ist ein doppeltes Signal — mögliches
   freies Ladenlokal UND ein Wettbewerber weniger. */
async function neuPruefen(z) {
  const sicher = confirm(
    `„${z.label}" jetzt neu prüfen?\n\n`
    + 'Das fragt alle Quellen erneut ab (am Cache vorbei), darunter eine '
    + 'Overpass-Abfrage. Der bisherige Stand wandert in den Verlauf des Punktes.');
  if (!sicher) return;
  const inhalt = document.getElementById('vergleich-inhalt');
  const wartebox = el('div', { class: 'verlauf-ergebnis' },
    el('div', { class: 'laden' }),
    `„${z.label}" wird neu geprüft — alle Quellen werden erneut abgefragt …`);
  inhalt.prepend(wartebox);
  let d;
  try {
    const r = await fetch(`/api/points/${z.id}/pruefung`, { method: 'POST' });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    d = await r.json();
  } catch (e) {
    wartebox.replaceChildren(el('div', { class: 'fehlerbox' },
      `Neu prüfen fehlgeschlagen: ${e.message}`));
    return;
  }
  await zeigeVergleich();

  const teile = [el('strong', {}, `Neu geprüft: ${d.label}`)];
  const nichts = !d.veraendert.length && !d.neue_betriebe.length
    && !d.verschwundene_betriebe.length;
  if (nichts) {
    teile.push(el('div', {},
      'Keine Veränderung bei den beweglichen Kennzahlen (OSM, GTFS, Zählstellen).'));
  }
  if (d.veraendert.length) {
    const tab = el('table', { class: 'daten' },
      el('tr', {}, el('th', {}, 'Kennzahl'), el('th', { class: 'num' }, 'vorher'),
        el('th', { class: 'num' }, 'jetzt')));
    for (const v of d.veraendert) {
      tab.append(el('tr', {},
        el('td', {}, v.titel),
        el('td', { class: 'num' }, v.alt === null || v.alt === undefined ? '—' : NF1.format(v.alt)),
        el('td', { class: 'num' }, v.neu === null || v.neu === undefined ? '—' : NF1.format(v.neu))));
    }
    teile.push(tab);
  }
  const betriebsliste = (titel, liste) => {
    if (!liste.length) return null;
    return el('div', {},
      el('h3', { class: 'hinweis-klein' }, titel),
      el('ul', { class: 'liste' }, liste.map((g) => el('li', {},
        el('span', { class: 'dist' },
          g.distanz_m === null || g.distanz_m === undefined ? '' : `${NF.format(g.distanz_m)} m`),
        el('span', { class: 'haupt' },
          el('div', { class: 'name' }, g.name || '(ohne Name)'),
          g.typ ? el('div', { class: 'meta' }, g.typ) : null)))));
  };
  teile.push(betriebsliste(`Neue Betriebe (${d.neue_betriebe.length})`, d.neue_betriebe));
  teile.push(betriebsliste(
    `Verschwundene Betriebe (${d.verschwundene_betriebe.length})`, d.verschwundene_betriebe));
  for (const h of d.hinweise || []) teile.push(el('div', { class: 'hinweis-klein' }, h));
  teile.push(el('button', { class: 'kein-druck', onclick: (ev) => ev.target.closest('.verlauf-ergebnis').remove() },
    'ausblenden'));

  document.getElementById('vergleich-inhalt')
    .prepend(el('div', { class: 'verlauf-ergebnis' }, teile.filter(Boolean)));
}

/* ------------------------------- Gewichtetes Ranking (eigene Gewichte) */

/* Das Werkzeug bewertet weiterhin nicht — die Punktzahl folgt allein aus den
   Gewichten des Nutzers, und jeder Beitrag steht offen in der Tabelle. Ohne
   diese Offenheit wäre es eine Scheinnote. */
const GEWICHTE_SPEICHER = 'gastroviewer.gewichte';
const RANKING_METRIKEN = [
  { key: 'einwohner', titel: 'Einwohner im Umkreis', richtung: 1 },
  { key: 'wettbewerb_je_1000', titel: 'Wettbewerber je 1.000 Einw.', richtung: -1 },
  { key: 'frequenzbringer', titel: 'Frequenzbringer', richtung: 1 },
  { key: 'abfahrten', titel: 'ÖPNV-Abfahrten je Tag', richtung: 1 },
  { key: 'miete_qm', titel: 'Nettokaltmiete €/m²', richtung: -1 },
  { key: 'erschliessung_einwohner', titel: 'Erschließungsgrad zu Fuß', richtung: 1 },
];
let rankingOffen = false;

function ladeGewichte() {
  let gemerkt = null;
  try {
    gemerkt = JSON.parse(localStorage.getItem(GEWICHTE_SPEICHER) || 'null');
  } catch { gemerkt = null; }
  const gewichte = {};
  for (const m of RANKING_METRIKEN) {
    const v = gemerkt && typeof gemerkt[m.key] === 'number' ? gemerkt[m.key] : 1;
    gewichte[m.key] = Math.min(3, Math.max(0, v));
  }
  return gewichte;
}

function rechneRanking(zeilen, gewichte) {
  /* Min-Max-Skalierung je Kennzahl über die gemerkten Punkte. Kennzahlen, die
     weniger als zweimal vorliegen oder überall gleich sind, tragen nichts bei
     — eine Skala aus einem einzigen Wert wäre erfunden. */
  const spannen = {};
  for (const m of RANKING_METRIKEN) {
    const werte = zeilen.map((z) => z[m.key]).filter((v) => typeof v === 'number');
    if (werte.length >= 2) {
      const min = Math.min(...werte);
      const max = Math.max(...werte);
      if (max > min) spannen[m.key] = { min, max };
    }
  }
  const ergebnisse = zeilen.map((z) => {
    const beitraege = [];
    let summe = 0;
    let gewichtsumme = 0;
    for (const m of RANKING_METRIKEN) {
      const sp = spannen[m.key];
      const g = gewichte[m.key];
      if (!sp || !g || typeof z[m.key] !== 'number') continue;
      let norm = ((z[m.key] - sp.min) / (sp.max - sp.min)) * 100;
      if (m.richtung < 0) norm = 100 - norm;
      beitraege.push({ metrik: m, norm });
      summe += norm * g;
      gewichtsumme += g;
    }
    return { zeile: z, punkte: gewichtsumme ? summe / gewichtsumme : null, beitraege };
  });
  ergebnisse.sort((a, b) => (b.punkte ?? -1) - (a.punkte ?? -1));
  return { ergebnisse, spannen };
}

function gewichtText(g) {
  return `×${String(g).replace('.', ',')}`;
}

function zeichneRanking(zeilen, gewichte, ziel) {
  const { ergebnisse } = rechneRanking(zeilen, gewichte);
  const aktive = RANKING_METRIKEN.filter((m) => gewichte[m.key] > 0);
  const tab = el('table', { class: 'vergleich-tabelle ranking-tabelle' },
    el('tr', {},
      el('th', {}, 'Rang'), el('th', {}, 'Bezeichnung'), el('th', {}, 'Punktzahl'),
      aktive.map((m) => el('th', {}, `${m.titel} (${gewichtText(gewichte[m.key])})`))));
  ergebnisse.forEach((e, i) => {
    const je = new Map(e.beitraege.map((b) => [b.metrik.key, b.norm]));
    tab.append(el('tr', {},
      el('td', {}, e.punkte === null ? '—' : String(i + 1)),
      el('td', { class: 'text' }, e.zeile.label),
      el('td', { class: 'num' },
        e.punkte === null ? '—' : NF1.format(e.punkte)),
      aktive.map((m) => el('td', { class: 'num' },
        je.has(m.key) ? NF.format(Math.round(je.get(m.key))) : '—'))));
  });
  ziel.replaceChildren(
    el('div', { class: 'tabelle-rahmen' }, tab),
    el('div', { class: 'hinweis-klein' },
      'Zellwerte: die auf 0–100 skalierte Kennzahl vor der Gewichtung. „—" heißt: '
      + 'liegt nicht vor oder ist bei allen Punkten gleich — geht nicht in die '
      + 'Punktzahl ein.'));
}

function rankingBereich(d) {
  if (!d.zeilen || d.zeilen.length < 2) return null;
  const gewichte = ladeGewichte();
  const ausgabe = el('div', { id: 'ranking-ausgabe' });

  const regler = el('div', { class: 'ranking-gewichte' });
  for (const m of RANKING_METRIKEN) {
    const anzeige = el('span', { class: 'ranking-wert' }, gewichtText(gewichte[m.key]));
    regler.append(el('label', {},
      el('span', { class: 'ranking-titel' }, m.titel, ' ',
        el('em', {}, m.richtung > 0 ? '(mehr = besser)' : '(weniger = besser)'), ' ', anzeige),
      el('input', {
        type: 'range', min: '0', max: '3', step: '0.5',
        value: String(gewichte[m.key]),
        'aria-label': `Gewicht für ${m.titel}`,
        oninput: (ev) => {
          gewichte[m.key] = Number(ev.target.value);
          anzeige.textContent = gewichtText(gewichte[m.key]);
          localStorage.setItem(GEWICHTE_SPEICHER, JSON.stringify(gewichte));
          zeichneRanking(d.zeilen, gewichte, ausgabe);
        },
      })));
  }

  const bereich = el('details', {
    class: 'ranking',
    ontoggle: (ev) => { rankingOffen = ev.target.open; },
  },
  el('summary', {}, 'Gewichtetes Ranking (eigene Gewichte)'),
  el('div', { class: 'notiz' },
    'Die Punktzahl folgt allein aus deinen Gewichten — sie ist keine Empfehlung '
    + 'des Werkzeugs. Jede Kennzahl wird über die gemerkten Punkte auf 0–100 '
    + 'skaliert (bester Wert 100, schlechtester 0) und nach Gewicht gemittelt. '
    + 'Ob „weniger Wettbewerb" für dich besser ist, entscheidet die Kennzahl '
    + 'nicht: Innenstadtlagen haben hohe Dichte UND hohen Zulauf.'),
  regler, ausgabe);
  if (rankingOffen) bereich.open = true;
  zeichneRanking(d.zeilen, gewichte, ausgabe);
  return bereich;
}

/* ------------------------------------------------ Adressliste-Import */

/* Aus einem Exposé-Stapel in Minuten eine Vergleichstabelle: eine Adresse je
   Zeile, jede wird über Nominatim gesucht (der Server hält die 1-Anfrage/s-
   Regel ein; die Schleife läuft deshalb bewusst nacheinander) und beim ersten
   Treffer als Punkt gemerkt — mit vollem Datenabruf wie bei „Punkt merken". */
const ADRESSLISTE_MAX = 25;

document.getElementById('btn-adressliste').addEventListener('click',
  () => document.getElementById('adressliste-dialog').showModal());
document.getElementById('adressliste-zu').addEventListener('click',
  () => document.getElementById('adressliste-dialog').close());
document.getElementById('adressliste-start').addEventListener('click',
  adresslisteVerarbeiten);

async function adresslisteVerarbeiten() {
  const feld = document.getElementById('adressliste-text');
  const ziel = document.getElementById('adressliste-ergebnis');
  const radius = Number(document.getElementById('adressliste-radius').value);
  const zeilen = feld.value.split('\n').map((z) => z.trim()).filter(Boolean);
  if (!zeilen.length) {
    ziel.replaceChildren(el('div', { class: 'warnung' }, 'Keine Adresse eingegeben.'));
    return;
  }
  if (zeilen.length > ADRESSLISTE_MAX) {
    ziel.replaceChildren(el('div', { class: 'warnung' },
      `Höchstens ${ADRESSLISTE_MAX} Adressen auf einmal — es sind ${zeilen.length}. `
      + 'Das begrenzt die Last auf Nominatim und Overpass.'));
    return;
  }
  const knopf = document.getElementById('adressliste-start');
  knopf.disabled = true;
  const befunde = [];
  const fehler = [];
  for (let i = 0; i < zeilen.length; i += 1) {
    const adresse = zeilen[i];
    ziel.replaceChildren(el('div', { class: 'verlauf-ergebnis' },
      el('div', { class: 'laden' }),
      `${i + 1} von ${zeilen.length}: „${adresse}" — suchen, dann Datenabruf …`));
    try {
      const d = await hole('/api/geocode', { q: adresse });
      const treffer = (d.data || [])[0];
      if (!treffer) {
        fehler.push(`${adresse}: kein Treffer bei Nominatim`);
        continue;
      }
      const r = await fetch('/api/points', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          label: adresse.slice(0, 80), lat: treffer.lat, lon: treffer.lon, radius,
        }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      befunde.push(`${adresse} → ${treffer.display_name.split(',').slice(0, 3).join(',')}`);
    } catch (e) {
      fehler.push(`${adresse}: ${e.message}`);
    }
  }
  knopf.disabled = false;
  // .filter(Boolean): replaceChildren stringifiziert null zum sichtbaren „null“.
  ziel.replaceChildren(...[
    el('div', { class: 'notiz' },
      el('strong', {}, `${befunde.length} von ${zeilen.length} Adressen gemerkt.`),
      befunde.length ? el('ul', { class: 'liste' },
        befunde.map((b) => el('li', {}, el('span', { class: 'haupt' }, b)))) : null),
    fehler.length ? el('div', { class: 'warnung' },
      el('strong', {}, 'Ohne Treffer oder fehlgeschlagen:'),
      el('ul', { class: 'liste' },
        fehler.map((f) => el('li', {}, el('span', { class: 'haupt' }, f)))),
      el('div', { class: 'hinweis-klein' },
        'Nominatim findet Adressen am besten als „Straße Hausnummer, Ort". '
        + 'Zeile anpassen und nur die fehlgeschlagenen erneut einfügen.')) : null,
    el('button', {
      onclick: () => {
        document.getElementById('adressliste-dialog').close();
        zeigeVergleich();
      },
    }, 'zum Standortvergleich'),
  ].filter(Boolean));
  ladePunkteEbene();
}

/* ------------------------------------------------------------- Suche */

const sucheFeld = document.getElementById('suche');
const trefferBox = document.getElementById('suche-treffer');
const sucheStatus = document.getElementById('suche-status');

/* Beim Tippen läuft seit der Z-Runde NUR noch die Photon-Vervollständigung
   (Listener weiter unten) — die Nominatim-Nutzungsbedingungen untersagen
   Autocomplete ausdrücklich, die frühere 1,1-s-Tippsuche ging dorthin.
   Nominatim beantwortet weiterhin die ausdrückliche Suche per Enter. */

document.getElementById('suche-form').addEventListener('submit', (e) => {
  e.preventDefault();
  // Anstehende und bereits laufende Photon-Vervollständigungen verwerfen —
  // sonst überschreibt eine verspätete Vorschlagsliste die Nominatim-Treffer.
  clearTimeout(vorschlagTimer);
  vorschlagLauf += 1;
  const q = sucheFeld.value.trim();
  if (q.length >= 3) sucheAusfuehren(q);
});

async function sucheAusfuehren(q) {
  sucheStatus.textContent = 'sucht …';
  try {
    const d = await hole('/api/geocode', { q });
    if (!d.ok) { sucheStatus.textContent = d.error?.message || 'Suche fehlgeschlagen'; return; }
    const treffer = d.data || [];
    sucheStatus.textContent = treffer.length ? `${treffer.length} Treffer` : 'keine Treffer';
    trefferBox.replaceChildren(...treffer.map((t) => el('button', {
      type: 'button',
      onclick: () => {
        trefferBox.hidden = true;
        sucheFeld.value = t.display_name;
        setzePunkt(t.lat, t.lon, true);
      },
    }, t.display_name)));
    trefferBox.hidden = !treffer.length;
  } catch (e) {
    sucheStatus.textContent = `Fehler: ${e.message}`;
  }
}

document.addEventListener('click', (e) => {
  if (!trefferBox.contains(e.target) && e.target !== sucheFeld) trefferBox.hidden = true;
});

/* ----------------------------- Adress-Autovervollständigung (Z7) */

/* Beim Tippen Vorschläge über Photon (die Nominatim-Regeln untersagen
   Autocomplete ausdrücklich — deshalb ein eigener, Photon-einziger
   Endpunkt). Enter läuft weiter über die normale Suche. Entprellt auf
   350 ms und ab drei Zeichen, damit der öffentliche Photon-Dienst nicht
   je Tastendruck gefragt wird; jede Eingabe wird zudem serverseitig
   gecacht. */
let vorschlagTimer = null;
let vorschlagLauf = 0;
sucheFeld.addEventListener('input', () => {
  clearTimeout(vorschlagTimer);
  const q = sucheFeld.value.trim();
  if (q.length < 3) {
    trefferBox.hidden = true;
    sucheStatus.textContent = '';
    return;
  }
  sucheStatus.textContent = 'Vorschläge …';
  vorschlagTimer = setTimeout(async () => {
    const lauf = ++vorschlagLauf;
    try {
      const d = await hole('/api/geocode/vorschlaege', { q });
      if (lauf !== vorschlagLauf || sucheFeld.value.trim() !== q) return;
      const treffer = (d.ok && d.data) || [];
      trefferBox.replaceChildren(...[
        ...treffer.map((t) => el('button', {
          type: 'button',
          onclick: () => {
            trefferBox.hidden = true;
            sucheFeld.value = t.display_name;
            setzePunkt(t.lat, t.lon, true);
          },
        }, t.display_name)),
        treffer.length ? el('div', { class: 'hinweis-klein', style: 'padding:4px 8px' },
          'Vorschläge: Photon (OSM-Daten)') : null,
      ].filter(Boolean));
      trefferBox.hidden = !treffer.length;
      sucheStatus.textContent = treffer.length
        ? `${treffer.length} Vorschläge — Enter sucht genau (Nominatim)`
        : 'keine Vorschläge — Enter sucht genau (Nominatim)';
    } catch { /* Vorschläge sind Komfort — die Suche per Enter bleibt. */ }
  }, 350);
});

/* ------------------------------------------------------------ Bedienung */

document.getElementById('radius').addEventListener('change', (e) => {
  state.radius = Number(e.target.value);
  if (state.lat !== null) setzePunkt(state.lat, state.lon);
});
document.getElementById('btn-merken').addEventListener('click', merken);
document.getElementById('btn-vergleich').addEventListener('click', zeigeVergleich);
document.getElementById('btn-neu').addEventListener('click', () => {
  if (state.lat !== null) lade(true);
});
document.getElementById('vergleich-zu').addEventListener('click',
  () => document.getElementById('vergleich-dialog').close());

async function aktualisiereFuss() {
  try {
    const s = await (await fetch('/api/stats')).json();
    /* Overpass und Nominatim sind Spendenprojekte. Wer nicht sieht, wie viel
       er ihnen abverlangt, merkt auch nicht, wenn er sie strapaziert. Deshalb
       steht die Zahl der letzten 24 Stunden je Dienst in der Fußzeile. */
    const je = s.outbound_24h_je_dienst || {};
    const teile = Object.entries(je)
      .sort((a, b) => b[1] - a[1])
      .map(([q, n]) => `${q} ${NF.format(n)}`);
    const ziel = document.getElementById('fuss-stats');
    // .filter(Boolean): replaceChildren macht aus einem null-Argument das
    // sichtbare Wort "null" — im Screenshot-Abgleich aufgefallen.
    ziel.replaceChildren(...[
      el('span', {}, `Cache: ${NF.format(s.total)} Einträge`),
      el('span', {}, ` · echte Abrufe seit Start: ${NF.format(s.outbound_requests_total)}`),
      el('span', {
        class: s.overpass_24h >= OVERPASS_WARNSCHWELLE ? 'viel-verkehr' : '',
        title: teile.length ? `Letzte 24 h: ${teile.join(' · ')}`
          : 'Letzte 24 h: keine Abrufe',
      }, ` · 24 h: ${NF.format(s.outbound_24h || 0)}`
         + (teile.length ? ` (${teile.slice(0, 3).join(', ')})` : '')),
      s.overpass_24h >= OVERPASS_WARNSCHWELLE
        ? el('span', { class: 'viel-verkehr' },
          ` · ${NF.format(s.overpass_24h)} Overpass-Abrufe in 24 h — bitte den `
          + 'Spendendienst schonen, gemerkte Punkte kommen aus dem Cache')
        : null,
    ].filter(Boolean));
  } catch { /* Fußzeile ist nicht kritisch */ }
}

(async function start() {
  try {
    const h = await (await fetch('/api/health')).json();
    if (h.gtfs?.importiert) {
      document.title = `Standort-Datenterminal (GTFS ${h.gtfs.referenzdatum})`;
    }
  } catch { /* Start funktioniert auch ohne */ }
  try {
    // Grenzen-Texte kommen aus dem Backend, damit sie nur an einer Stelle stehen.
    const p = await (await fetch('/api/point/links?lat=48.1334&lon=11.5674&r=600')).json();
    GRENZEN = p.grenzen || [];
  } catch { GRENZEN = []; }
  aktualisiereFuss();
}());

/* ===================================================================
 * Umsatzschätzung — Spec §9
 *
 * Eigener Reiter, klar getrennt vom Datenteil. Bindende Auflagen aus §9:
 * alle Annahmen sind Eingabefelder, die Ausgabe ist eine Spanne, daneben steht
 * die Umrechnung in Bestellungen pro Tag und pro Öffnungsstunde, und die Formel
 * ist sichtbar. Beschriftung: Vergleichsmaß, keine Prognose.
 * =================================================================== */

const schaetzState = { vorgaben: null, fuerPunkt: null };

const FELDER = [
  { key: 'einwohner', label: 'Einwohner im Radius', schritt: '1', herkunft: 'einwohner_herkunft' },
  { key: 'wettbewerber', label: 'Wettbewerber im Radius', schritt: '1', herkunft: 'wettbewerber_herkunft' },
  { key: 'besuche_je_einwohner', label: 'Besuche je Einwohner und Jahr', schritt: '0.1' },
  { key: 'bon_min', label: 'Durchschnittsbon, untere Annahme (€)', schritt: '0.01' },
  { key: 'bon_max', label: 'Durchschnittsbon, obere Annahme (€)', schritt: '0.01' },
  { key: 'unsicherheitsfaktor', label: 'Unsicherheitsfaktor Marktanteil', schritt: '0.1', gesetzt: true },
  { key: 'marktanteil_min_prozent', label: 'Marktanteil untere Annahme (%) — leer = aus Faktor', schritt: '0.01', gesetzt: true },
  { key: 'marktanteil_max_prozent', label: 'Marktanteil obere Annahme (%) — leer = aus Faktor', schritt: '0.01', gesetzt: true },
  { key: 'oeffnungstage', label: 'Öffnungstage im Jahr', schritt: '1', gesetzt: true },
  { key: 'oeffnungsstunden', label: 'Öffnungsstunden je Tag', schritt: '0.5', gesetzt: true },
  { key: 'mietanteil_min_prozent', label: 'Miete, unterer Anteil vom Umsatz (%)', schritt: '0.5', gesetzt: true },
  { key: 'mietanteil_max_prozent', label: 'Miete, oberer Anteil vom Umsatz (%)', schritt: '0.5', gesetzt: true },
  /* Franchise-Kostenprobe. Bewusst ohne Vorgabewerte: die Sätze stehen im
     Franchisevertrag und in der eigenen Kalkulation — jeder hier erfundene
     „typische" Satz würde als Branchenwert gelesen. Leer = Probe entfällt. */
  { key: 'franchisegebuehr_prozent', label: 'Franchisegebühr (% vom Umsatz)', schritt: '0.1',
    hinweis: 'aus deinem Franchisevertrag — leer lassen, wenn ohne' },
  { key: 'werbeabgabe_prozent', label: 'Werbeabgabe (% vom Umsatz)', schritt: '0.1',
    hinweis: 'aus deinem Franchisevertrag — leer lassen, wenn ohne' },
  { key: 'wareneinsatz_prozent', label: 'Wareneinsatz (% vom Umsatz)', schritt: '0.5',
    hinweis: 'aus deiner Kalkulation — leer lassen, wenn unbekannt' },
  { key: 'personalkosten_prozent', label: 'Personalkosten (% vom Umsatz)', schritt: '0.5',
    hinweis: 'aus deiner Kalkulation — leer lassen, wenn unbekannt' },
  /* Mietprobe gegen ein konkretes Exposé — Werte aus dem Angebot des
     Vermieters. Leer = Probe entfällt. */
  { key: 'flaeche_qm', label: 'Fläche laut Exposé (m²)', schritt: '1',
    hinweis: 'aus dem Angebot — leer lassen, wenn keins vorliegt' },
  { key: 'angebotsmiete_qm', label: 'Geforderte Kaltmiete (€/m² und Monat)', schritt: '0.5',
    hinweis: 'aus dem Angebot — leer lassen, wenn keins vorliegt' },
  /* Lage-Anker: Wohnungsmiete des Umkreises aus dem Zensus-Gitter. Vorbefüllt,
     sichtbar, änderbar — geht in keine Umsatzrechnung ein, nur in die
     Einordnung der Mietprobe. */
  { key: 'zensus_wohnmiete_qm', label: 'Wohnungsmiete im Umkreis (€/m², Zensus 2022)',
    schritt: '0.1', herkunft: 'zensus_wohnmiete_herkunft' },
];

/* Der Umkreis ist ein Luftlinienkreis; zu Fuß ist er kleiner und an Flüssen
   und Gleisen zerschnitten. Sind die Gehstrecken berechnet, wird die engere
   Zahl angeboten — aber nicht stillschweigend gesetzt: sonst hinge das
   Ergebnis daran, ob jemand vorher einen Knopf gedrückt hat, und zwei
   Standorte wären nicht mehr vergleichbar. */
function gehwegAngebot(alt) {
  if (!alt) return null;
  return el('div', { class: 'warnung', id: 'gehweg-angebot' },
    el('div', {}, alt.hinweis),
    el('div', { class: 'hinweis-klein', style: 'margin:5px 0 7px' }, alt.warnung),
    el('button', {
      type: 'button',
      id: 'btn-gehweg-uebernehmen',
      onclick: () => {
        document.getElementById('sf-einwohner').value = String(alt.einwohner);
        const feld = document.getElementById('sf-einwohner')?.closest('.feld');
        feld?.querySelector('.herkunft')?.replaceChildren(
          `Zu Fuß erreichbar (Block 4b), ${alt.erschliessungsgrad} % des `
          + 'Luftlinienkreises — übernommen',
        );
        rechneSchaetzung();
      },
    }, `Einwohner auf ${NF.format(alt.einwohner)} setzen`),
    ' ',
    el('button', {
      type: 'button',
      onclick: () => {
        document.getElementById('sf-einwohner').value = String(alt.einwohner_luftlinie ?? 0);
        rechneSchaetzung();
      },
    }, 'zurück auf Luftlinie'));
}

/* Ist im Gastronomieblock ein Branchenprofil gewählt, wird dessen Zählung
   als Wettbewerberzahl angeboten — wie beim Gehweg: sichtbar, ausdrücklich
   zu übernehmen, nie stillschweigend gesetzt. */
function brancheAngebot() {
  const key = localStorage.getItem(BRANCHE_SPEICHER) || 'alle';
  const b = BRANCHEN.find((x) => x.key === key);
  if (!b || !b.typen) return null;
  const gastro = state.daten.osm?.data?.gastronomie;
  if (!gastro) return null;
  const k = brancheKennzahlen(gastro, b.typen);
  return el('div', { class: 'warnung' },
    el('div', {},
      `Im Gastronomieblock ist das Branchenprofil „${b.label}" gewählt: `
      + `${NF.format(k.anzahl)} Betriebe der OSM-Typen ${b.typen.join(', ')} `
      + 'im Umkreis.'),
    el('div', { class: 'hinweis-klein', style: 'margin:5px 0 7px' },
      'Wenn du übernimmst, rechne beide Standorte mit demselben Profil — '
      + 'sonst vergleichst du verschiedene Wettbewerbsbegriffe.'),
    el('button', {
      type: 'button',
      onclick: () => {
        document.getElementById('sf-wettbewerber').value = String(k.anzahl);
        const feld = document.getElementById('sf-wettbewerber')?.closest('.feld');
        feld?.querySelector('.herkunft')?.replaceChildren(
          `OpenStreetMap, Branchenprofil „${b.label}" (${b.typen.join(', ')}) — übernommen`);
        rechneSchaetzung();
      },
    }, `Wettbewerber auf ${NF.format(k.anzahl)} setzen`));
}

/* Kennt Overture Betriebe, die in OSM fehlen, wird die kombinierte Zahl als
   Wettbewerberzahl angeboten — wie beim Gehweg und beim Branchenprofil:
   sichtbar, ausdrücklich zu übernehmen, nie stillschweigend gesetzt. */
function overtureAngebot() {
  const o = state.daten.overture?.data;
  if (!o?.importiert || !(o.nur_overture || []).length) return null;
  return el('div', { class: 'warnung', id: 'overture-angebot' },
    el('div', {},
      `Der Overture-Abgleich kennt ${NF.format(o.nur_overture.length)} Betriebe, `
      + `die in OSM fehlen — kombiniert sind es ${NF.format(o.kombiniert_gesamt)} `
      + `statt ${NF.format(o.osm_gesamt)} Wettbewerber im Umkreis.`),
    el('div', { class: 'hinweis-klein', style: 'margin:5px 0 7px' },
      'Wenn du übernimmst, rechne beide Standorte mit derselben Quelle — '
      + 'sonst vergleichst du eine Untergrenze mit einer kombinierten Zahl.'),
    el('button', {
      type: 'button',
      onclick: () => {
        document.getElementById('sf-wettbewerber').value = String(o.kombiniert_gesamt);
        const feld = document.getElementById('sf-wettbewerber')?.closest('.feld');
        feld?.querySelector('.herkunft')?.replaceChildren(
          `OSM + Overture kombiniert (${NF.format(o.osm_gesamt)} OSM, `
          + `${NF.format(o.nur_overture.length)} nur Overture) — übernommen`);
        rechneSchaetzung();
      },
    }, `Wettbewerber auf ${NF.format(o.kombiniert_gesamt)} setzen (OSM+Overture)`));
}

function schaetzBlock(titel, ...inhalt) {
  return el('section', { class: 'block' },
    el('h2', {}, titel),
    el('div', { class: 'block-inhalt' }, inhalt.filter(Boolean)));
}

function spanne(titel, werte, einheit, nk = 0, hervor = false) {
  const f = (v) => (nk === 0 ? NF : NF1).format(v);
  return el('div', { class: `spanne ${hervor ? 'hervor' : ''}`.trim() },
    el('div', { class: 'titel' }, titel),
    el('div', { class: 'wert' }, f(werte[0]), el('span', { class: 'bis' }, 'bis'), f(werte[1])),
    el('div', { class: 'einheit' }, einheit));
}

async function zeigeSchaetzung() {
  const ziel = document.getElementById('panel-schaetzung');
  if (state.lat === null) {
    ziel.replaceChildren(el('div', { class: 'karte-hinweis' },
      el('h2', {}, 'Erst einen Punkt wählen'),
      el('p', {}, 'Die Schätzung braucht Einwohnerzahl und Wettbewerbszahl aus dem '
        + 'Datenreiter. Wähle links einen Punkt auf der Karte.')));
    return;
  }
  const kennung = `${state.lat}|${state.lon}|${state.radius}`;
  if (schaetzState.fuerPunkt !== kennung) {
    ziel.replaceChildren(el('div', { class: 'block' },
      el('div', { class: 'laden' }),
      el('div', { class: 'block-inhalt' }, 'Vorgaben werden aus den Punktdaten geholt …')));
    try {
      schaetzState.vorgaben = await hole('/api/schaetzung/vorgaben',
        { lat: state.lat, lon: state.lon, r: state.radius });
      schaetzState.fuerPunkt = kennung;
    } catch (e) {
      ziel.replaceChildren(fehlerbox({ message: e.message }));
      return;
    }
  }
  baueSchaetzFormular();
  rechneSchaetzung();
}

function baueSchaetzFormular() {
  const v = schaetzState.vorgaben;
  const ziel = document.getElementById('panel-schaetzung');

  const banner = el('div', { class: 'schaetz-banner' },
    el('strong', {}, 'Vergleichsmaß zwischen Standorten — keine Prognose.'),
    'Alle Annahmen unten sind Eingabefelder und lassen sich ändern. Das Ergebnis ist '
    + 'immer eine Spanne. Für eine belastbare Aussage taugt es nicht: die Rechnung kennt '
    + 'weder Lage noch Passantenströme noch die Stärke der Wettbewerber. '
    + 'Sinnvoll ist sie nur, um zwei Standorte unter denselben Annahmen nebeneinander '
    + 'zu halten.');

  const gitter = el('div', { class: 'eingabe-gitter' });
  for (const f of FELDER) {
    const wert = v[f.key];
    const feld = el('div', { class: `feld ${f.gesetzt ? 'gesetzt' : ''}`.trim() },
      el('label', { for: `sf-${f.key}` }, f.label),
      el('input', {
        type: 'number', id: `sf-${f.key}`, step: f.schritt,
        value: wert === null || wert === undefined ? '' : String(wert),
        oninput: () => rechneSchaetzung(),
      }),
      f.herkunft && v[f.herkunft] ? el('div', { class: 'herkunft' }, v[f.herkunft]) : null,
      f.gesetzt ? el('div', { class: 'herkunft' }, 'frei gewählt, keine Datengrundlage') : null,
      f.hinweis ? el('div', { class: 'herkunft' }, f.hinweis) : null);
    gitter.append(feld);
  }

  const herleitung = v.besuche_herleitung;
  const eingaben = schaetzBlock('Annahmen', gitter,
    el('div', { class: 'notiz' },
      el('strong', {}, 'Besuche je Einwohner und Jahr: '), herleitung.herleitung),
    v.wettbewerber_alternative ? el('div', { class: 'notiz' },
      `${v.wettbewerber_alternative.hinweis} Im Umkreis liegen insgesamt `
      + `${NF.format(v.wettbewerber_alternative.alle_gastronomie)} gastronomische Betriebe.`) : null,
    gehwegAngebot(v.gehweg_alternative),
    brancheAngebot(),
    overtureAngebot());

  const formel = schaetzBlock('Rechenweg',
    el('div', { class: 'formel' }, v.formel.join('\n')),
    el('div', { class: 'notiz' },
      'Das ist der vollständige Rechenweg. Es gibt keine weiteren Faktoren — keine '
      + 'Distanzgewichte, keine Lagefaktoren, keine Kaufkraftindizes.'));

  const ergebnis = el('section', { class: 'block', id: 'schaetz-ergebnis' },
    el('h2', {}, 'Ergebnis'), el('div', { class: 'block-inhalt' }));

  const grenzen = schaetzBlock('Was diese Rechnung nicht kann',
    el('ul', { class: 'liste' }, v.warnungen.map((w) => el('li', {},
      el('span', { class: 'haupt' }, w)))));

  const quellen = schaetzBlock('Referenzwerte',
    el('table', { class: 'daten' },
      el('tr', {}, el('th', {}, 'Größe'), el('th', { class: 'num' }, 'Wert'),
        el('th', {}, 'Stand'), el('th', {}, 'Quelle')),
      v.referenzwerte.map((r) => el('tr', {},
        el('td', {}, r.titel),
        el('td', { class: 'num' }, `${r.wert} ${r.einheit}`),
        el('td', {}, r.stand),
        el('td', {}, r.url
          ? el('a', { href: r.url, target: '_blank', rel: 'noopener' }, r.quelle)
          : r.quelle)))),
    ...v.referenzwerte.filter((r) => r.hinweis).map((r) =>
      el('div', { class: 'notiz' }, el('strong', {}, `${r.titel}: `), r.hinweis)),
    el('div', { class: 'quelle' },
      'Alle Referenzwerte am 01.08.2026 selbst nachgeschlagen. Sie sind Eingabewerte '
      + 'und überschreibbar — verändert sich der Markt, gehören hier neue Zahlen hinein.'));

  /* Prüfstein gegen die Wirklichkeit. Das Modell rechnet mit
     Bundesdurchschnitten und kennt weder Lage noch Passantenströme; ob es für
     einen bestimmten Betriebstyp um Faktor 1,2 oder um Faktor 5 danebenliegt,
     sagt ein einziger bekannter Umsatz mehr als jede weitere Verfeinerung. */
  const kalibrierung = schaetzBlock('Prüfstein: gegen einen echten Betrieb halten',
    el('p', { class: 'hinweis-klein' },
      'Trage den tatsächlichen Jahresumsatz eines Betriebs ein, den du kennst — den '
      + 'eigenen, einen übernommenen, einen befreundeten — und stelle die Rechnung '
      + 'daneben. Der Wert geht in keine Rechnung ein und wird nicht gespeichert.'),
    el('div', { class: 'eingabe-gitter' },
      el('div', { class: 'feld' },
        el('label', { for: 'sf-kalib-umsatz' }, 'Tatsächlicher Jahresumsatz (€)'),
        el('input', {
          type: 'number', id: 'sf-kalib-umsatz', step: '1000', min: '0',
          placeholder: 'leer lassen, wenn unbekannt',
          oninput: () => rechneSchaetzung(),
        })),
      el('div', { class: 'feld' },
        el('label', { for: 'sf-kalib-name' }, 'Um welchen Betrieb geht es?'),
        el('input', {
          type: 'text', id: 'sf-kalib-name', maxlength: '120',
          placeholder: 'z. B. eigener Imbiss Sendling',
          oninput: () => rechneSchaetzung(),
        }))),
    el('div', { class: 'notiz', id: 'kalib-ergebnis' },
      'Ohne Vergleichswert bleibt offen, ob die Rechnung für deinen Betriebstyp '
      + 'überhaupt in der richtigen Größenordnung liegt.'));

  ziel.replaceChildren(banner, eingaben, ergebnis, kalibrierung, formel, grenzen, quellen);
}

let schaetzTimer = null;
function rechneSchaetzung() {
  clearTimeout(schaetzTimer);
  schaetzTimer = setTimeout(schaetzungAbschicken, 250);
}

async function schaetzungAbschicken() {
  const koerper = {};
  for (const f of FELDER) {
    const roh = document.getElementById(`sf-${f.key}`)?.value;
    if (roh === '' || roh === undefined) {
      if (f.key.startsWith('marktanteil')) koerper[f.key] = null;
      continue;
    }
    koerper[f.key] = Number(roh);
  }
  const kalibUmsatz = document.getElementById('sf-kalib-umsatz')?.value;
  if (kalibUmsatz !== '' && kalibUmsatz !== undefined) {
    koerper.kalibrierung_umsatz_eur = Number(kalibUmsatz);
    const name = document.getElementById('sf-kalib-name')?.value?.trim();
    if (name) koerper.kalibrierung_bezeichnung = name;
  }
  const ziel = document.querySelector('#schaetz-ergebnis .block-inhalt');
  if (!ziel) return;
  try {
    const r = await fetch('/api/schaetzung', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(koerper),
    });
    if (!r.ok) {
      let text = `HTTP ${r.status}`;
      try { text = (await r.json()).detail || text; } catch { /* egal */ }
      ziel.replaceChildren(el('div', { class: 'fehlerbox' }, text));
      return;
    }
    zeigeSchaetzErgebnis(await r.json(), ziel);
  } catch (e) {
    ziel.replaceChildren(fehlerbox({ message: e.message }));
  }
}

function zeigeKalibrierung(k) {
  const ziel = document.getElementById('kalib-ergebnis');
  if (!ziel) return;
  if (!k) {
    ziel.className = 'notiz';
    ziel.textContent = 'Ohne Vergleichswert bleibt offen, ob die Rechnung für '
      + 'deinen Betriebstyp überhaupt in der richtigen Größenordnung liegt.';
    return;
  }
  ziel.className = k.innerhalb_der_spanne ? 'notiz' : 'warnung';
  const tab = el('table', { class: 'daten' },
    el('tr', {}, el('th', {}, k.bezeichnung), el('th', { class: 'num' }, '€ im Jahr')),
    el('tr', {}, el('td', {}, 'tatsächlich'),
      el('td', { class: 'num' }, NF.format(k.tatsaechlich_eur))),
    el('tr', {}, el('td', {}, 'gerechnete Spanne'),
      el('td', { class: 'num' },
        `${NF.format(k.gerechnete_spanne_eur[0])} – ${NF.format(k.gerechnete_spanne_eur[1])}`)),
    el('tr', {}, el('td', {}, 'gerechnete Mitte'),
      el('td', { class: 'num' }, NF.format(k.gerechnet_mitte_eur))),
    el('tr', {}, el('td', {}, el('strong', {}, 'Verhältnis')),
      el('td', { class: 'num' }, el('strong', {}, NF2.format(k.faktor)))));
  // Der Befundtext trägt **Betonung** in Markdown-Manier; hier reicht fett.
  const teile = k.befund.split('**');
  const satz = el('p', {}, teile.map((s, i) => (i % 2 ? el('strong', {}, s) : s)));
  ziel.replaceChildren(tab, satz,
    el('p', { class: 'hinweis-klein' }, k.hinweis));
}

function zeigeSchaetzErgebnis(d, ziel) {
  const e = d.ergebnis;
  const z = d.zwischenschritte;
  zeigeKalibrierung(d.kalibrierung);

  // §9: Die Umrechnung in Bestellungen ist Pflichtausgabe und steht deshalb
  // vor dem Umsatz — sie ist die Zahl, die ein Betreiber beurteilen kann.
  const kacheln = el('div', { class: 'kennzahlen' },
    spanne('Bestellungen je Öffnungsstunde', e.bestellungen_je_oeffnungsstunde, 'Bestellungen/h', 1, true),
    spanne('Bestellungen je Öffnungstag', e.bestellungen_je_tag, 'Bestellungen/Tag', 1, true),
    spanne('Umsatz je Öffnungstag', e.umsatz_je_tag_eur, '€ brutto/Tag'),
    spanne('Jahresumsatz', e.jahresumsatz_eur, '€ im Jahr'));

  const kette = el('table', { class: 'daten' },
    el('tr', {}, el('th', {}, 'Schritt'), el('th', { class: 'num' }, 'Wert')),
    el('tr', {}, el('td', {}, 'Besuche im Einzugsgebiet je Jahr'),
      el('td', { class: 'num' }, NF.format(z.besuche_im_einzugsgebiet_je_jahr))),
    el('tr', {}, el('td', {}, 'Marktanteil, naive Gleichverteilung'),
      el('td', { class: 'num' }, `${NF2.format(z.naiver_marktanteil_prozent)} %`)),
    el('tr', {}, el('td', {}, 'Marktanteil, gerechnet'),
      el('td', { class: 'num' },
        `${NF2.format(d.eingaben.marktanteil_min_prozent)} – ${NF2.format(d.eingaben.marktanteil_max_prozent)} %`)),
    el('tr', {}, el('td', {}, 'Besuche des Betriebs je Jahr'),
      el('td', { class: 'num' },
        `${NF.format(z.besuche_des_betriebs_je_jahr[0])} – ${NF.format(z.besuche_des_betriebs_je_jahr[1])}`)));

  /* Franchise-Kostenprobe — nur, wenn der Nutzer Sätze eingegeben hat. */
  const fr = d.franchise;
  const franchiseTeile = [];
  if (fr) {
    const satzTab = el('table', { class: 'daten' },
      el('tr', {}, el('th', {}, 'Satz'), el('th', { class: 'num' }, '% vom Umsatz')));
    for (const s of fr.saetze) {
      satzTab.append(el('tr', {}, el('td', {}, s.titel),
        el('td', { class: 'num' }, NF1.format(s.prozent))));
    }
    satzTab.append(el('tr', {}, el('th', {}, 'Summe'),
      el('th', { class: 'num' }, `${NF1.format(fr.summe_prozent)}`)));
    franchiseTeile.push(
      el('h3', { class: 'hinweis-klein' }, 'Franchise-Kostenprobe'),
      satzTab,
      spanne(`Verbleib (${NF1.format(fr.verbleib_prozent)} % vom Umsatz) je Monat`,
        fr.verbleib_monat_eur, '€ im Monat — vor Miete, AfA, Zinsen, Unternehmerlohn'),
      ...(fr.warnungen || []).map((w) => el('div', { class: 'warnung' }, w)),
      el('div', { class: 'notiz' }, fr.hinweis));
  }

  ziel.replaceChildren(
    kacheln,
    el('div', { class: 'notiz' }, el('strong', {}, 'Beschriftung: '), d.beschriftung),
    el('h3', { class: 'hinweis-klein' }, 'Rechenkette'),
    kette,
    el('div', { class: 'notiz' },
      el('strong', {}, 'Marktanteil: '), z.marktanteil_herkunft),
    el('h3', { class: 'hinweis-klein' }, 'Gegenprobe Miete'),
    spanne('Obergrenze Monatsmiete', e.monatsmiete_obergrenze_eur, '€ im Monat'),
    el('div', { class: 'notiz' },
      `Bei ${d.eingaben.mietanteil_min_prozent} bis ${d.eingaben.mietanteil_max_prozent} % `
      + 'vom Umsatz. Faustregel aus notizen-standort-flaeche.md §6 — keine erhobene Statistik. '
      + 'Liegt die geforderte Miete darüber, trägt der Standort sich unter diesen Annahmen nicht.'),
    // .filter(Boolean): mietprobeTeile enthält ohne Zensus-Wohnmiete ein null,
    // das replaceChildren sonst als sichtbaren Text „null“ rendert.
    ...mietprobeTeile(d.mietprobe).filter(Boolean),
    ...sensitivitaetTeile(d.sensitivitaet),
    ...franchiseTeile);
}

/* Sensitivität: Woran die Spanne hängt — exakt aus der Formel hergeleitet,
   keine gewählten Störgrößen. Balkenlänge proportional zum Spannenfaktor. */
function sensitivitaetTeile(s) {
  if (!s) return [];
  const maxFaktor = Math.max(...s.treiber.map((t) => t.faktor), 1);
  const tab = el('table', { class: 'daten' },
    el('tr', {}, el('th', {}, 'Annahme'), el('th', { class: 'num' }, 'Spannenfaktor'),
      el('th', {}, '')));
  for (const t of s.treiber) {
    tab.append(el('tr', {},
      el('td', {}, el('b', {}, t.titel),
        el('div', { class: 'hinweis-klein' }, t.erklaerung)),
      el('td', { class: 'num' }, `× ${NF2.format(t.faktor)}`),
      el('td', { style: 'width:34%;vertical-align:middle;' },
        el('div', {
          class: 'sens-balken',
          style: `width:${Math.round((t.faktor / maxFaktor) * 100)}%;`,
          title: `Faktor ${NF2.format(t.faktor)}`,
        }))));
  }
  const teile = [
    el('h3', { class: 'hinweis-klein' }, 'Woran die Spanne hängt'),
    tab,
    el('div', { class: 'notiz' }, s.befund),
  ];
  if (s.wettbewerber_plus_eins) {
    const w = s.wettbewerber_plus_eins;
    teile.push(el('div', { class: 'warnung' },
      el('b', {}, `Ein übersehener Wettbewerber: ${NF1.format(w.wirkung_prozent)} % Umsatz. `),
      w.erklaerung));
  }
  teile.push(
    el('div', { class: 'hinweis-klein' },
      `${s.linear.felder.join(' und ')}: ${s.linear.erklaerung}. `
      + `${s.ohne_wirkung.felder.join(' und ')}: ${s.ohne_wirkung.erklaerung}.`),
    el('div', { class: 'hinweis-klein' }, s.hinweis));
  return teile;
}

/* Mietprobe gegen ein konkretes Exposé — nur, wenn Fläche und geforderte
   Miete eingegeben wurden. Der Befund färbt sich nach der Lage zur Spanne. */
function mietprobeTeile(mp) {
  if (!mp) return [];
  const klasse = mp.lage === 'ueber' ? 'warnung'
    : mp.lage === 'innerhalb' ? 'warnung' : 'notiz';
  return [
    el('h3', { class: 'hinweis-klein' }, 'Mietprobe gegen das Exposé'),
    el('div', { class: 'kennzahlen' },
      kennzahl(`Monatsmiete (${NF.format(mp.flaeche_qm)} m² × ${NF1.format(mp.angebotsmiete_qm)} €/m²)`,
        mp.monatsmiete_eur, '€'),
      spanne('Obergrenze aus der Rechnung', mp.obergrenze_eur, '€ im Monat'),
      mp.anteil_am_umsatz_prozent
        ? spanne('Anteil am gerechneten Umsatz', mp.anteil_am_umsatz_prozent, '%', 1)
        : null),
    el('div', { class: klasse }, mp.befund.replaceAll('**', '')),
    mp.wohnmiete_vergleich ? el('div', { class: 'notiz' },
      el('b', {}, `Lage-Anker Wohnungsmiete: das ${NF2.format(mp.wohnmiete_vergleich.verhaeltnis)}-Fache `
        + `der örtlichen Wohnungsmiete (${NF2.format(mp.wohnmiete_vergleich.wohnmiete_qm)} €/m², Zensus 2022). `),
      mp.wohnmiete_vergleich.hinweis) : null,
    el('div', { class: 'hinweis-klein' }, mp.hinweis),
  ];
}

/* Reiterumschaltung */
document.getElementById('reiter').addEventListener('click', (ev) => {
  const knopf = ev.target.closest('button[data-reiter]');
  if (!knopf) return;
  const welcher = knopf.dataset.reiter;
  for (const b of document.querySelectorAll('#reiter button')) {
    const aktiv = b === knopf;
    b.classList.toggle('aktiv', aktiv);
    b.setAttribute('aria-selected', String(aktiv));
  }
  document.getElementById('panel').hidden = welcher !== 'daten';
  document.getElementById('panel-schaetzung').hidden = welcher !== 'schaetzung';
  if (welcher === 'schaetzung') zeigeSchaetzung();
});

/* ===================================================================
 * Bodenrichtwerte als Kartenebene — Phase 4
 *
 * Spec §4.5: Landesdienst als Kartenebene nachrüsten, wenn einer gefunden wird.
 * Es sind sieben Länder verifiziert; für die übrigen bleibt es beim Portallink,
 * und der Grund steht im Panel statt einer geratenen URL.
 *
 * Die Kacheln holt der Browser direkt beim Landesdienst. Die Klickabfrage
 * (GetFeatureInfo) läuft über das Backend, weil sie sonst an CORS scheitert.
 * =================================================================== */

const brwState = { ebene: null, cfg: null, code: null };

function entferneBrwEbene() {
  if (brwState.ebene) {
    karte.removeLayer(brwState.ebene);
    ebenenSchalter.removeLayer(brwState.ebene);
    state.rasterEbenen.delete(brwState.ebene);
    brwState.ebene = null;
  }
  brwState.cfg = null;
  brwState.code = null;
}

async function setzeBrwEbene(bundeslandCode) {
  if (brwState.code === bundeslandCode) return;
  entferneBrwEbene();
  if (!bundeslandCode) return;

  let cfg;
  try {
    cfg = await hole('/api/wms', { bundesland_code: bundeslandCode });
  } catch {
    return; // Ohne Ebene weiterarbeiten; der Panel-Block nennt den Grund.
  }
  if (!cfg.verfuegbar) { brwState.code = bundeslandCode; brwState.cfg = cfg; return; }

  const zusatz = {};
  for (const [k, v] of Object.entries(cfg.params || {})) zusatz[k] = v;

  const ebene = L.tileLayer.wms(cfg.url, {
    layers: cfg.layers,
    format: 'image/png',
    transparent: true,
    version: cfg.version,
    attribution: cfg.attribution,
    minZoom: cfg.min_zoom || 0,
    maxZoom: 19,
    ...zusatz,
  });
  ebene.setOpacity(state.deckkraft);
  state.rasterEbenen.add(ebene);
  brwState.ebene = ebene;
  brwState.cfg = cfg;
  brwState.code = bundeslandCode;
  ebenenSchalter.addOverlay(ebene, `Bodenrichtwerte ${cfg.land}`);
}

/** Klickabfrage: nur auf Wunsch, damit kein Kartenklick ungefragt hinausgeht. */
async function frageBodenrichtwertAb(ziel) {
  ziel.replaceChildren(el('div', { class: 'laden' }));
  try {
    const d = await hole('/api/wms/bodenrichtwert', {
      lat: state.lat, lon: state.lon, bundesland_code: brwState.code || '',
    });
    if (!d.ok) { ziel.replaceChildren(fehlerbox(d.error)); return; }
    if (!d.data) { ziel.replaceChildren(...warnungen(d.warnings)); return; }

    const teile = [];
    if (d.data.felder.length) {
      const tab = el('table', { class: 'daten' },
        el('tr', {}, el('th', {}, 'Feld'), el('th', {}, 'Wert')));
      for (const f of d.data.felder) {
        tab.append(el('tr', {}, el('td', {}, f.feld), el('td', {}, f.wert)));
      }
      teile.push(tab);
    }
    teile.push(...warnungen(d.warnings));
    if (d.data.rohantwort) {
      const roh = el('details', {},
        el('summary', { class: 'hinweis-klein' }, 'Unveränderte Antwort des Dienstes'),
        el('pre', { class: 'formel', style: 'white-space:pre-wrap;max-height:240px;' },
          d.data.rohantwort));
      teile.push(roh);
    }
    ziel.replaceChildren(...teile);
    setQuelle('bodenrichtwert', d.provenance);
  } catch (e) {
    ziel.replaceChildren(fehlerbox({ message: e.message }));
  }
}

/** Wird von zeigeLinks() aufgerufen und hängt den Block ans Panel. */
function brwBlock(bodenrichtwerte) {
  const cfg = bodenrichtwerte.kartendienst || { verfuegbar: false };
  const inhalt = [];

  if (!cfg.verfuegbar) {
    inhalt.push(el('div', { class: 'notiz' },
      el('strong', {}, 'Keine Kartenebene: '), cfg.grund || 'kein Dienst hinterlegt.',
      cfg.hinweis ? el('div', { style: 'margin-top:4px' }, cfg.hinweis) : null));
    return el('section', { class: 'block', id: 'block-bodenrichtwert' },
      el('h2', {}, 'Bodenrichtwerte', el('span', { class: 'status leer' }, 'kein Dienst')),
      el('div', { class: 'block-inhalt', id: 'inhalt-bodenrichtwert' }, inhalt));
  }

  const ergebnis = el('div', { id: 'brw-ergebnis' });
  inhalt.push(
    el('div', { class: 'notiz' },
      el('strong', {}, `${cfg.titel}. `),
      `Als Kartenebene „Bodenrichtwerte ${cfg.land}" zuschaltbar, sichtbar ab `
      + `Zoomstufe ${cfg.min_zoom || 0}. Stand: ${cfg.stand}.`),
    el('div', { style: 'display:flex;gap:6px;flex-wrap:wrap;margin-top:8px' },
      el('button', {
        type: 'button',
        onclick: (ev) => {
          if (brwState.ebene && !karte.hasLayer(brwState.ebene)) karte.addLayer(brwState.ebene);
          if (karte.getZoom() < (cfg.min_zoom || 0)) karte.setZoom(cfg.min_zoom);
          ev.target.textContent = 'Ebene eingeschaltet';
        },
      }, 'Ebene in der Karte zeigen'),
      cfg.abfragbar !== 'nein'
        ? el('button', {
          type: 'button',
          onclick: () => frageBodenrichtwertAb(ergebnis),
        }, 'Wert am Punkt abfragen')
        : null,
      el('a', { class: 'knopf-link', href: cfg.portal, target: '_blank', rel: 'noopener' },
        'Landesportal')),
    ergebnis);

  if (cfg.abfragbar !== 'voll') {
    inhalt.push(el('div', { class: 'warnung' }, cfg.abfrage_hinweis));
  }
  inhalt.push(el('div', { class: 'notiz' },
    'Bodenrichtwerte sind Zonenwerte für ein fiktives Grundstück mit den angegebenen '
    + 'Merkmalen — nicht der Wert eines konkreten Grundstücks und kein Mietpreis.'));

  const block = el('section', { class: 'block', id: 'block-bodenrichtwert' },
    el('h2', {}, 'Bodenrichtwerte',
      el('span', { class: 'status ok' }, 'Dienst verfügbar')),
    el('div', { class: 'block-inhalt', id: 'inhalt-bodenrichtwert' }, inhalt));
  return block;
}

/* ===================================================================
 * München und Bayern
 *
 * Zwei Ergänzungen für die Zielregion:
 *  · Raddauerzählstellen der Stadt — die einzigen gemessenen Frequenzzahlen,
 *    die frei nutzbar sind. Radfahrende, nicht Fußgänger, sechs Standorte.
 *  · Amtliche Kartenebenen Bayerns: Luftbild und Flurstücke. Für die Fragen
 *    aus notizen-standort-flaeche.md §6 (Abluft über Dach, Hoffläche,
 *    Stellplätze) oft aussagekräftiger als jede Zahl.
 * =================================================================== */

const zusatzState = { ebenen: [], code: null };

async function setzeZusatzebenen(bundeslandCode) {
  if (zusatzState.code === bundeslandCode) return;
  for (const e of zusatzState.ebenen) {
    karte.removeLayer(e);
    ebenenSchalter.removeLayer(e);
    state.rasterEbenen.delete(e);
  }
  zusatzState.ebenen = [];
  zusatzState.code = bundeslandCode;
  if (!bundeslandCode) return;

  let d;
  try {
    d = await hole('/api/wms/ebenen', { bundesland_code: bundeslandCode });
  } catch { return; }

  for (const cfg of d.ebenen || []) {
    const ebene = L.tileLayer.wms(cfg.url, {
      layers: cfg.layers,
      format: cfg.format,
      transparent: cfg.transparent,
      version: cfg.version,
      attribution: cfg.attribution,
      minZoom: cfg.min_zoom || 0,
      maxZoom: 19,
    });
    zusatzState.ebenen.push(ebene);
    const beschriftung = cfg.min_zoom > 12
      ? `${cfg.titel} (ab Zoom ${cfg.min_zoom})`
      : cfg.titel;
    if (cfg.als_grundkarte) {
      // Eine Grundkarte wird nicht zurückgeblendet — sie ist ja das, was man
      // durch die anderen Ebenen hindurch sehen will.
      ebenenSchalter.addBaseLayer(ebene, beschriftung);
    } else {
      ebene.setOpacity(state.deckkraft);
      state.rasterEbenen.add(ebene);
      ebenenSchalter.addOverlay(ebene, beschriftung);
    }
  }
}

function zeigeRadzaehlung(d) {
  const id = 'radzaehlung';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const r = d.data;
  if (!r || !r.in_reichweite.length) {
    setStatus(id, 'leer', 'keine Zählstelle');
    setInhalt(id, ...warnungen(d.warnings),
      el('div', { class: 'notiz' },
        'Gemessene Radfrequenz gibt es nur an den städtischen '
        + 'Zählquerschnitten (München, Hamburg). Für diesen Punkt liegt '
        + 'keine vor.'));
    setQuelle(id, d.provenance);
    return;
  }

  setStatus(id, 'ok', 'geladen');
  const n = r.naechste;
  const kz = el('div', { class: 'kennzahlen' },
    kennzahl('Nächste Zählstelle', n.distanz_m, 'm'),
    kennzahl(`Radfahrende ${n.summe_vorjahr_jahr || ''}`.trim(), n.summe_vorjahr),
    kennzahl('davon je Tag', n.je_tag_vorjahr));

  const tab = el('table', { class: 'daten' },
    el('tr', {}, el('th', {}, 'Zählstelle'), el('th', { class: 'num' }, 'm'),
      el('th', { class: 'num' }, 'je Tag'), el('th', { class: 'num' }, 'Jahr')));
  for (const s of r.in_reichweite) {
    tab.append(el('tr', {},
      el('td', {}, `${s.name}${s.richtungen.length ? ` (${s.richtungen.join('/')})` : ''}`),
      el('td', { class: 'num' }, NF.format(s.distanz_m)),
      el('td', { class: 'num' }, s.je_tag_vorjahr === null ? '—' : NF.format(s.je_tag_vorjahr)),
      el('td', { class: 'num' }, s.summe_vorjahr === null ? '—' : NF.format(s.summe_vorjahr))));
  }

  /* Jahresgang der nächsten Zählstelle aus den Tages-Rohdaten: wie weit
     Sommer und Winter auseinanderliegen, sagt die Jahressumme nicht. */
  let jahresgang = null;
  const jg = n.jahresgang;
  if (jg && Array.isArray(jg.monatsmittel)) {
    const max = Math.max(1, ...jg.monatsmittel.map((m) => m || 0));
    jahresgang = el('div', { id: 'rad-jahresgang' },
      el('h3', { class: 'hinweis-klein' },
        `Jahresgang ${r.jahresgang_jahr} (${n.kurzname}) — Tagesmittel je Monat`),
      el('div', { style: 'display:flex;align-items:flex-end;gap:2px;height:60px;margin:6px 0 2px;' },
        jg.monatsmittel.map((m, i) => el('div', {
          title: m === null || m === undefined
            ? `${['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'][i]} — keine Messtage`
            : `${['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'][i]} — Ø ${NF.format(m)} Radfahrende/Tag`,
          style: `flex:1;border-radius:2px 2px 0 0;`
            + (m === null || m === undefined
              ? 'background:#d5dbe1;height:3px;'
              : `background:var(--akzent);opacity:.75;height:${Math.max(3, (m / max) * 100)}%;`),
        }))),
      el('div', { style: 'display:flex;justify-content:space-between;font-size:11px;color:#5b6570;' },
        el('span', {}, 'Jan'), el('span', {}, 'Jun'), el('span', {}, 'Dez')),
      el('div', { class: 'hinweis-klein' },
        `${NF.format(jg.messtage)} Messtage im Jahr ${r.jahresgang_jahr}; `
        + `Ø ${NF.format(jg.je_tag_mittel)} je Tag, stärkster Tag ${NF.format(jg.spitzentag)}. `
        + (jg.messtage < 300 ? 'Deutlich weniger als 365 Messtage — Ausfallzeiten, das Mittel ist entsprechend unsicher. ' : '')
        + 'Wetter und Jahreszeit schlagen stark durch.'));
  }

  const besonders = r.in_reichweite.filter((s) => s.besonderheiten);
  setInhalt(id, kz, tab, jahresgang,
    ...besonders.map((s) => el('div', { class: 'notiz' },
      el('strong', {}, `${s.kurzname}: `), s.besonderheiten)),
    ...warnungen(d.warnings),
    el('div', { class: 'warnung' },
      'Radfahrende, keine Fußgänger — und sechs Querschnitte für die ganze Stadt. '
      + 'Die Zahl beschreibt die Achse an der Zählstelle, nicht das Umfeld dieses Punktes.'),
    el('div', { class: 'notiz' },
      el('a', { href: r.rohdaten, target: '_blank', rel: 'noopener' },
        'Rohdaten im Open-Data-Portal München'),
      ' — dort auch 15-Minuten-Werte und Tageswerte mit Wetter.'));
  setQuelle(id, d.provenance);
}

/* Verkehrsmenge (BAYSIS) — für einen Standort an einer Ausfallstraße, mit
 * Drive-through oder Parkplatz die aussagekräftigste Frequenzgröße, die es
 * amtlich gemessen und frei gibt. */
/* Gehstufen für die Karte. Die Grenzen sind Anteile des gewählten Radius, keine
   festen Meterwerte — sonst wären sie bei 300 m und bei 1400 m gleich sinnlos. */
const GEH_STUFEN = [
  { bis: 0.34, farbe: '#1a7f37', name: 'erstes Drittel' },
  { bis: 0.67, farbe: '#6aab3f', name: 'zweites Drittel' },
  { bis: 1.01, farbe: '#d9a441', name: 'letztes Drittel' },
];

function zeichneGehflaeche(g) {
  const gruppe = state.ebenen.gehflaeche;
  gruppe.clearLayers();
  const punkte = g?.flaeche || [];
  if (!punkte.length) return;
  const radius = g.radius_m || state.radius;

  for (const [lat, lon, meter] of punkte) {
    const anteil = meter / radius;
    const stufe = GEH_STUFEN.find((s) => anteil <= s.bis) || GEH_STUFEN[GEH_STUFEN.length - 1];
    const m = L.circleMarker([lat, lon], {
      renderer: state.gehwegRenderer,
      radius: 4,
      stroke: false,
      fillColor: stufe.farbe,
      fillOpacity: 0.55 * state.deckkraft,
      _basisDeckkraft: 0.55,
      _basisRand: 0,
    });
    m.bindPopup(() => `<h4>Zu Fuß erreichbar</h4>
      <p>${NF.format(meter)} m Gehweg (${NF1.format(meter / g.gehtempo_m_pro_min)} min)
      · Luftlinie ${NF.format(Math.round(
        L.latLng(state.lat, state.lon).distanceTo(L.latLng(lat, lon)))
      )} m</p>
      <p class="hinweis-klein">Ein Punkt je ${g.raster_m} m Rasterzelle,
      jeweils der kürzeste Weg darin.</p>`);
    gruppe.addLayer(m);
  }
  if (!karte.hasLayer(gruppe)) gruppe.addTo(karte);
}

function zeigeGehweg(d) {
  const id = 'gehweg';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error), el('button', { onclick: ladeGehweg }, 'Erneut versuchen'));
    setQuelle(id, d.provenance);
    return;
  }
  const g = d.data;
  if (!g) {
    setStatus(id, 'ok', 'ohne Ergebnis');
    setInhalt(id, ...warnungen(d.warnings || []),
      el('button', { onclick: ladeGehweg }, 'Erneut versuchen'));
    setQuelle(id, d.provenance);
    return;
  }
  setStatus(id, 'ok', 'geladen');
  zeichneGehflaeche(g);

  const gas = g.gastronomie || {};
  const zen = g.zensus || {};
  const kz = el('div', { class: 'kennzahlen' },
    kennzahl(`Gehzeit für ${g.radius_m} m`, g.gehzeit_minuten, 'min', 1),
    kennzahl('Umwegfaktor (Median)', gas.umwegfaktor_median, '', 2),
    kennzahl('Erschließungsgrad Einwohner', zen.erschliessungsgrad, '%', 1),
    kennzahl('Erschließungsgrad Gastronomie', gas.erschliessungsgrad, '%', 1));

  /* Die Gegenüberstellung ist der Kern des Blocks: links, was der Kreis
     behauptet, rechts, was zu Fuß übrig bleibt. */
  const tab = el('table', { class: 'daten' },
    el('tr', {},
      el('th', {}, ''), el('th', { class: 'num' }, `${g.radius_m} m Luftlinie`),
      el('th', { class: 'num' }, `${g.radius_m} m Fußweg`),
      el('th', { class: 'num' }, 'erschlossen')));
  const zeile = (name, luft, fuss, quote) => tab.append(el('tr', {},
    el('td', {}, name),
    el('td', { class: 'num' }, luft === null || luft === undefined ? '—' : NF.format(luft)),
    el('td', { class: 'num' }, fuss === null || fuss === undefined ? '—' : NF.format(fuss)),
    el('td', { class: 'num' }, quote === null || quote === undefined ? '—' : `${NF1.format(quote)} %`)));
  zeile('Einwohner', zen.einwohner_luftlinie, zen.einwohner_gehweg, zen.erschliessungsgrad);
  zeile('Zensuszellen', (zen.zellen_im_gehradius || 0) + (zen.zellen_nur_luftlinie || 0),
    zen.zellen_im_gehradius, null);
  zeile('Gastronomie', gas.im_luftlinienkreis, gas.im_gehradius, gas.erschliessungsgrad);
  for (const [feld, name] of [['frequenzbringer', 'Frequenzbringer'],
    ['oepnv', 'Haltestellen'], ['leerstand', 'Leerstände']]) {
    const x = g[feld];
    if (x) zeile(name, x.im_luftlinienkreis, x.im_gehradius, x.erschliessungsgrad);
  }

  /* Legende zur Kartenebene — ohne sie sind die drei Farben Dekoration. */
  const stufen = el('div', { class: 'gehstufen' },
    el('span', { class: 'hinweis-klein' }, 'Auf der Karte:'),
    GEH_STUFEN.map((s, i) => {
      const von = i === 0 ? 0 : Math.round(GEH_STUFEN[i - 1].bis * g.radius_m);
      const bis = Math.min(g.radius_m, Math.round(s.bis * g.radius_m));
      return el('span', { class: 'gehstufe' },
        el('i', { style: `background:${s.farbe}` }),
        `${NF.format(von)}–${NF.format(bis)} m`);
    }),
    el('span', { class: 'hinweis-klein' },
      `· ${NF.format((g.flaeche || []).length)} Punkte, ein Raster von ${g.raster_m} m`));

  const netz = el('p', { class: 'hinweis-klein' },
    `Wegenetz: ${NF.format(g.knoten)} Knoten, ${NF.format(g.kanten)} Kanten aus `
    + `${NF.format(g.wege)} OSM-Wegen (${NF.format(g.wege_gesperrt)} als nicht begehbar `
    + `ausgeschlossen). Kürzester Weg je Knoten in ${g.rechenzeit_ms} ms berechnet. `
    + `Anbindung des Standorts an das Netz: ${g.anbindung_m} m.`);

  setInhalt(id, kz, tab, stufen, netz,
    ...(g.hinweise || []).map((h) => el('div', { class: 'notiz' }, h)),
    zen.hinweis ? el('div', { class: 'notiz' }, zen.hinweis) : null,
    ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

/* Zwei Fragen, die eine Standortentscheidung kippen: liegt die Flaeche im
   Hochwassergebiet, und gilt ein Bebauungsplan. Beides sind Auskuenfte zum
   Nachgehen, keine Entscheidungen — die Hinweise sagen das. */
function zeigePlanung(d) {
  const id = 'planung';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const p = d.data;
  if (!p) {
    setStatus(id, 'leer', 'keine Daten');
    setInhalt(id, ...warnungen(d.warnings || []));
    setQuelle(id, d.provenance);
    return;
  }
  setStatus(id, 'ok',
    (p.hochwasser || {}).dienst === 'bfg' ? 'bundesweit' : 'geladen');

  const hw = p.hochwasser || {};
  const bp = p.bebauungsplan;
  const teile = [];

  if (hw.betroffen) {
    const tab = el('table', { class: 'daten' },
      el('tr', {}, el('th', {}, 'Gewässer'), el('th', {}, 'Jährlichkeit'),
        el('th', {}, 'ermittelt')));
    for (const g of hw.gebiete) {
      tab.append(el('tr', {},
        el('td', {}, g.gewaesser || '—'),
        el('td', {}, g.jaehrlichkeit || '—'),
        el('td', {}, g.ermittelt || '—')));
    }
    teile.push(el('div', { class: 'warnung' },
      el('strong', {}, 'Der Punkt liegt in einem Hochwassergefahrengebiet. '),
      hw.hq_haeufig
        ? 'Darunter HQhäufig — das ist die ernsteste Stufe.'
        : 'Für Keller, Lager, Kühltechnik und die Versicherungsprämie relevant.'));
    teile.push(tab);
    const amt = (hw.gebiete.find((g) => g.amt) || {}).amt;
    if (amt) {
      teile.push(el('p', { class: 'hinweis-klein' },
        'Zuständig: ',
        el('a', { href: amt, target: '_blank', rel: 'noopener' }, 'Wasserwirtschaftsamt')));
    }
  } else {
    teile.push(el('div', { class: 'notiz' },
      'Kein Hochwassergefahrengebiet am Punkt (geprüft für HQhäufig, HQ100 und '
      + 'HQextrem). Das ist eine Aussage über die berechneten Flächen, keine Zusage.'));
  }

  teile.push(el('h3', { class: 'hinweis-klein' }, 'Bebauungsplan'));
  if (bp === undefined || bp === null) {
    teile.push(el('div', { class: 'notiz' },
      'Für diesen Punkt nicht abgefragt — die Umgriffe stammen aus dem Geoportal '
      + 'der Landeshauptstadt München.'));
  } else if (bp.vorhanden) {
    teile.push(el('ul', { class: 'liste' }, bp.plaene.map((x) => el('li', {},
      el('span', { class: 'haupt' },
        el('div', { class: 'name' }, `Plan ${x.nummer || 'ohne Nummer'}`),
        x.verfahren ? el('div', { class: 'meta' }, `Verfahren ${x.verfahren}`) : null)))));
  } else {
    teile.push(el('div', { class: 'notiz' },
      'Für diese Fläche ist kein Bebauungsplan-Umgriff ausgewiesen.'));
  }

  /* Erhaltungssatzung (Milieuschutz, § 172 BauGB) — nur im Stadtgebiet
     München abgefragt; ein Treffer ist für Umnutzung/Umbau entscheidend. */
  const es = p.erhaltungssatzung;
  teile.push(el('h3', { class: 'hinweis-klein' }, 'Erhaltungssatzung (Milieuschutz)'));
  if (es === undefined || es === null) {
    teile.push(el('div', { class: 'notiz' },
      'Für diesen Punkt nicht abgefragt — die Gebiete stammen aus dem '
      + 'Geoportal der Landeshauptstadt München.'));
  } else if (es.betroffen) {
    teile.push(el('div', { class: 'warnung' },
      el('strong', {}, 'Der Punkt liegt in einem Erhaltungssatzungsgebiet. '),
      'Nutzungsänderungen (etwa Wohnung → Gastraum) und Umbauten sind hier '
      + 'genehmigungspflichtig nach § 172 BauGB.'));
    teile.push(el('ul', { class: 'liste' }, es.gebiete.map((g) => el('li', {},
      el('span', { class: 'haupt' }, `Gebiet „${g.name || 'ohne Namen'}“`,
        g.gueltig_ab ? ` — gültig ab ${g.gueltig_ab}` : ''),
      el('span', { class: 'neben' },
        [g.text_pdf ? el('a', { href: g.text_pdf, target: '_blank', rel: 'noopener' }, 'Satzungstext (PDF)') : null,
          g.plan_pdf ? el('a', { href: g.plan_pdf, target: '_blank', rel: 'noopener' }, 'Gebietsplan (PDF)') : null]
          .filter(Boolean).flatMap((a, i) => (i ? [' · ', a] : [a])))))));
  } else {
    teile.push(el('div', { class: 'notiz' },
      'Der Punkt liegt in keinem Gebiet mit Erhaltungssatzung.'));
  }

  teile.push(...(p.hinweise || []).map((h) => {
    const st = h.split('**');
    return el('div', { class: 'notiz' },
      st.map((s, i) => (i % 2 ? el('strong', {}, s) : s)));
  }));
  teile.push(el('ul', { class: 'liste' }, (p.portale || []).map((x) => el('li', {},
    el('span', { class: 'haupt' },
      el('a', { href: x.url, target: '_blank', rel: 'noopener' }, x.titel))))));

  setInhalt(id, ...teile, ...warnungen(d.warnings || []));
  setQuelle(id, d.provenance);
}

function zeigeVerkehrsmenge(d) {
  const id = 'verkehrsmenge';
  if (!d.ok) {
    setStatus(id, 'fehler', 'nicht erreichbar');
    setInhalt(id, fehlerbox(d.error));
    setQuelle(id, d.provenance);
    return;
  }
  const v = d.data;
  if (!v || !v.zaehlstellen.length) {
    setStatus(id, 'leer', 'keine Zählstelle');
    setInhalt(id, ...warnungen(d.warnings),
      ...((v && v.hinweise) || []).map((h) => hinweisZeile(h)));
    setQuelle(id, d.provenance);
    return;
  }
  setStatus(id, 'ok', v.dienst === 'bast' ? `bundesweit (${v.jahr})` : 'geladen');
  const s = v.staerkste || v.naechste;
  const kz = el('div', { class: 'kennzahlen' },
    kennzahl('Stärkste Zählstelle', s.dtv_kfz, 'Kfz/Tag'),
    kennzahl('davon Schwerverkehr', s.dtv_schwerverkehr, 'Kfz/Tag'),
    kennzahl('Entfernung', s.distanz_m, 'm'),
    kennzahl('Zählstellen im Umkreis', v.zaehlstellen.length));

  const tab = el('table', { class: 'daten' },
    el('tr', {}, el('th', {}, 'Straße'), el('th', { class: 'num' }, 'm'),
      el('th', { class: 'num' }, 'Kfz/Tag'), el('th', { class: 'num' }, 'SV %')));
  for (const z of v.zaehlstellen.slice(0, 12)) {
    tab.append(el('tr', {},
      el('td', {}, `${z.strasse || '(ohne Angabe)'}${z.im_radius ? ' ✓' : ''}`),
      el('td', { class: 'num' }, NF.format(z.distanz_m)),
      el('td', { class: 'num' }, z.dtv_kfz === null ? '—' : NF.format(z.dtv_kfz)),
      el('td', { class: 'num' },
        z.schwerverkehr_anteil === null ? '—' : NF1.format(z.schwerverkehr_anteil))));
  }

  setInhalt(id, kz, tab,
    el('div', { class: 'notiz' }, '✓ = innerhalb des gewählten Radius.'),
    ...warnungen(d.warnings),
    el('div', { class: 'warnung' },
      'Vorbeifahrender Verkehr ist keine Kundschaft. Ohne Zufahrt, Parkplatz oder '
      + 'Drive-through nutzt eine hohe Verkehrsstärke wenig — und der Außengastronomie '
      + 'schadet sie eher. Der DTV ist ein Jahresmittel über alle Wochentage.'),
    ...(v.hinweise || []).map((h) => hinweisZeile(h)),
    el('div', { class: 'notiz' },
      v.dienst === 'bast'
        ? 'Gemessen werden bundesweit nur Autobahnen und Bundesstraßen '
          + '(BASt-Dauerzählstellen). Innerstädtische Straßen fehlen. '
        : 'Gezählt wird nur das klassifizierte Straßennetz (Autobahnen, Bundes-, Staats- '
          + 'und Kreisstraßen). Innerstädtische Gemeindestraßen und Fußgängerzonen fehlen. ',
      el('a', { href: v.portal, target: '_blank', rel: 'noopener' },
        v.dienst === 'bast' ? 'Zählstellen bei der BASt' : 'Straßenverkehrszählung bei BAYSIS')));
  setQuelle(id, d.provenance);
}

/* ------------------------------------------------- Brücke zum Fenster
 *
 * Ein Modul hat einen eigenen Namensraum — seine Funktionen liegen nicht
 * mehr automatisch auf `window`. Zwei Nutzer brauchen sie aber dort:
 *
 * 1. Die Browserprüfung (scripts/uitest.py) steuert die Oberfläche über
 *    page.evaluate und fasst genau diese Namen an.
 * 2. Wer die Seite offen hat und in der Entwicklerkonsole nachsehen will,
 *    was gerade geladen ist.
 *
 * Die Liste ist bewusst kurz und ausdrücklich — nicht der ganze Modulinhalt.
 * `sprungRing` braucht einen Lesezugriff statt einer Zuweisung: Die Variable
 * wird beim Springen zu einem Kartenpunkt neu gesetzt, eine einfache
 * Zuweisung würde den Startwert null einfrieren.
 */
Object.assign(window, {
  setzePunkt, state, karte, osmKarte, ueberlappungen, zeigeScore,
});
Object.defineProperty(window, 'sprungRing', {
  get: () => sprungRing,
  configurable: true,
});

/* Den Score einhängen, statt ihn in dom.js zu importieren — siehe Kopf von
   js/dom.js. Damit zeigt die Abhängigkeit nur in eine Richtung. */
beiBlockRender(planeScoreUpdate);
