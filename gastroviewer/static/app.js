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

'use strict';

const NF = new Intl.NumberFormat('de-DE');
const NF1 = new Intl.NumberFormat('de-DE', { maximumFractionDigits: 1 });
const NF2 = new Intl.NumberFormat('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const state = {
  lat: null,
  lon: null,
  radius: 600,
  marker: null,
  kreis: null,
  daten: {},          // name -> Antwort des jeweiligen Quellen-Endpunkts
  ebenen: {},         // name -> L.LayerGroup
  choroMetrik: 'Einwohner',
  ladeLauf: 0,        // verhindert, dass eine alte Antwort eine neue überschreibt
};

/* ------------------------------------------------------------- Helfer */

const el = (tag, attrs = {}, ...kinder) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') n.className = v;
    else if (k === 'html') n.innerHTML = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const kind of kinder.flat()) {
    if (kind === null || kind === undefined || kind === false) continue;
    n.append(kind.nodeType ? kind : document.createTextNode(String(kind)));
  }
  return n;
};

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** Formatiert eine Zahl. null/undefined ergibt bewusst „keine Angabe", nicht 0. */
function zahl(v, nk = 0) {
  if (v === null || v === undefined || Number.isNaN(v)) return null;
  return (nk === 0 ? NF : nk === 1 ? NF1 : NF2).format(v);
}

/** Aggregate kommen als {wert, zellen, zellen_gesamt, median, min, max}. */
function kennzahl(titel, agg, einheit = '', nk = 0) {
  const box = el('div', { class: 'kennzahl' });
  box.append(el('div', { class: 'titel' }, titel));
  const v = agg && typeof agg === 'object' ? agg.wert : agg;
  const txt = zahl(v, nk);
  if (txt === null) {
    box.append(el('div', { class: 'wert fehlt' }, 'keine Angabe'));
    if (agg && agg.zellen_gesamt) {
      box.append(el('div', { class: 'basis' }, `kein Wert in ${agg.zellen_gesamt} Zellen`));
    }
    return box;
  }
  box.append(el('div', { class: 'wert' }, einheit ? `${txt} ${einheit}` : txt));
  if (agg && typeof agg === 'object' && agg.zellen !== undefined) {
    const teile = [`${agg.zellen} von ${agg.zellen_gesamt} Zellen`];
    if (agg.median !== undefined) teile.push(`Median ${zahl(agg.median, nk)}`);
    if (agg.min !== undefined) teile.push(`${zahl(agg.min, nk)}–${zahl(agg.max, nk)}`);
    box.append(el('div', { class: 'basis' }, teile.join(' · ')));
  }
  return box;
}

function quellenzeile(prov) {
  if (!prov) return null;
  const teile = [];
  teile.push(el('b', {}, 'Quelle: '), prov.source);
  if (prov.stand) teile.push(' · ', el('b', {}, 'Stand: '), prov.stand);
  if (prov.retrieved_at) teile.push(` · abgerufen ${prov.retrieved_at.replace('T', ' ').replace('Z', ' UTC')}`);
  teile.push(el('br', {}), el('b', {}, 'Lizenz: '), prov.license);
  if (prov.endpoint) teile.push(el('br', {}), el('span', {}, prov.endpoint));
  if (prov.note) teile.push(el('br', {}), el('span', {}, prov.note));
  return el('div', { class: 'quelle' }, teile);
}

/** Ein Panel-Block mit Statusanzeige, Inhalt und Quellenfußzeile. */
function block(id, titel) {
  const kopf = el('h2', {}, titel, el('span', { class: 'status laedt', id: `status-${id}` }, 'lädt …'));
  const inhalt = el('div', { class: 'block-inhalt', id: `inhalt-${id}` },
    el('div', { class: 'laden' }));
  const b = el('section', { class: 'block', id: `block-${id}` }, kopf, inhalt);
  return b;
}

function setStatus(id, klasse, text) {
  const s = document.getElementById(`status-${id}`);
  if (s) { s.className = `status ${klasse}`; s.textContent = text; }
}

function setInhalt(id, ...kinder) {
  const c = document.getElementById(`inhalt-${id}`);
  if (!c) return;
  c.replaceChildren(...kinder.flat().filter(Boolean));
}

function setQuelle(id, prov) {
  const b = document.getElementById(`block-${id}`);
  if (!b) return;
  b.querySelector('.quelle')?.remove();
  const z = quellenzeile(prov);
  if (z) b.append(z);
}

/** Fehleranzeige mit konkreter Ursache — Spec §5. */
function fehlerbox(err) {
  const kinder = [el('strong', {}, 'Nicht erreichbar. '), err?.message || 'Unbekannter Fehler.'];
  if (err?.detail) kinder.push(el('br', {}), el('code', {}, String(err.detail).slice(0, 400)));
  return el('div', { class: 'fehlerbox' }, kinder);
}

function warnungen(liste) {
  return (liste || []).map((w) => el('div', { class: 'warnung' }, w));
}

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

for (const name of ['zensus', 'gastronomie', 'frequenzbringer', 'oepnv', 'leerstand']) {
  state.ebenen[name] = L.layerGroup();
}
state.ebenen.zensus.addTo(karte);
state.ebenen.gastronomie.addTo(karte);

const ebenenSchalter = L.control.layers({
  'OpenStreetMap': osmKarte,
  'basemap.de (amtlich)': basemapFarbe,
  'basemap.de grau': basemapGrau,
}, {
  'Zensus-Gitter': state.ebenen.zensus,
  'Gastronomie': state.ebenen.gastronomie,
  'Frequenzbringer': state.ebenen.frequenzbringer,
  'ÖPNV': state.ebenen.oepnv,
  'Leerstände (OSM)': state.ebenen.leerstand,
}, { collapsed: false }).addTo(karte);
ebenenSchalter.getContainer().classList.add('ebenen-schalter');

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
    const poly = L.polygon(latlngs, {
      color: '#ffffff', weight: 0.6, fillColor: farbe(v, g), fillOpacity: v === null ? 0.25 : 0.62,
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
};

function zeichnePois(name, liste) {
  const gruppe = state.ebenen[name];
  gruppe.clearLayers();
  const stil = POI_STIL[name];
  for (const p of liste || []) {
    const m = L.circleMarker([p.lat, p.lon], {
      radius: 5, color: stil.color, weight: 1.5, fillColor: stil.fill, fillOpacity: 0.85,
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
  feld('Entfernung', `${NF.format(p.distanz_m)} m ${p.richtung}`);
  for (const [k, v] of Object.entries(p.tags || {})) feld(k, v);
  return `<h4>${esc(p.name || '(ohne Name)')}</h4><table>${zeilen.join('')}</table>
    ${p.distanz_hinweis ? `<p class="hinweis-klein">${esc(p.distanz_hinweis)}</p>` : ''}
    <p class="hinweis-klein"><a href="${esc(p.osm_url)}" target="_blank" rel="noopener">In OpenStreetMap ansehen</a>
    — dort steht der Rohdatensatz.</p>`;
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

  const aktuell = () => lauf === state.ladeLauf;

  // Jede Quelle einzeln — Ausfall der einen hält die andere nicht auf.
  hole('/api/point/adresse', { lat, lon, ...(refresh ? { refresh: 'true' } : {}) })
    .then((d) => { if (aktuell()) { state.daten.adresse = d; zeigeKopf(); ladeLinks(); } })
    .catch((e) => {
      if (!aktuell()) return;
      state.daten.adresse = { ok: false, error: { message: e.message } };
      zeigeKopf();
    });

  hole('/api/point/zensus', p)
    .then((d) => { if (aktuell()) { state.daten.zensus = d; zeigeZensus(d); zeigeKopf(); ladeLinks(); } })
    .catch((e) => {
      if (!aktuell()) return;
      zeigeBlockFehler('bevoelkerung', e);
      zeigeBlockFehler('wohnen', e);
    });

  hole('/api/point/osm', p)
    .then((d) => { if (aktuell()) { state.daten.osm = d; zeigeOsm(d); } })
    .catch((e) => {
      if (!aktuell()) return;
      for (const id of ['gastronomie', 'umfeld', 'verkehr', 'leerstand']) zeigeBlockFehler(id, e);
    });

  hole('/api/point/gtfs', p)
    .then((d) => { if (aktuell()) { state.daten.gtfs = d; zeigeGtfs(d); } })
    .catch((e) => aktuell() && zeigeBlockFehler('gtfs', e));

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
    block('bevoelkerung', '2 · Bevölkerung'),
    block('wohnen', '3 · Wohnen'),
    block('gastronomie', '4 · Gastronomie'),
    block('umfeld', '5 · Umfeld'),
    block('verkehr', '6 · Verkehr'),
    block('gtfs', '6b · Abfahrten (GTFS)'),
    block('leerstand', '7 · Leerstände'),
    block('quellen', '8 · Weiterführende Quellen'),
    block('grenzen', 'Bekannte Grenzen dieser Daten'),
  );
  setStatus('grenzen', 'ok', '');
  setInhalt('grenzen', el('ul', { class: 'liste' },
    GRENZEN.map((g) => el('li', {}, el('span', { class: 'haupt' }, g)))));
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

  setInhalt('bevoelkerung', kz, tab,
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

function zeigeOsm(d) {
  const ids = ['gastronomie', 'umfeld', 'verkehr', 'leerstand'];
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

  const gListe = liste(o.gastronomie, 12, (p) => el('li', {},
    el('span', { class: 'dist' }, `${NF.format(p.distanz_m)} m`),
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
    el('h3', { class: 'hinweis-klein' }, 'Nach Typ'), typTab,
    el('h3', { class: 'hinweis-klein' }, 'Küchenverteilung'), kuecheTab,
    el('h3', { class: 'hinweis-klein' }, 'Betriebe nach Entfernung'), gListe,
    el('div', { class: 'notiz' },
      'Öffnungszeiten stehen unverändert so in OSM, wie sie dort eingetragen sind. '
      + 'Sie werden nicht ausgewertet — die opening_hours-Syntax kennt Feiertage, '
      + 'Saisons und Ausnahmen, die ein einfacher Parser falsch verstehen würde.'),
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
      liste(o.leerstand, 10, (p) => el('li', {},
        el('span', { class: 'dist' }, `${NF.format(p.distanz_m)} m`),
        el('span', { class: 'haupt' },
          el('div', { class: 'name' }, p.name || '(ohne Name)'),
          el('div', { class: 'meta' }, `${p.art}${p.frueher ? ` · früher: ${p.frueher}` : ''}`)))),
      el('div', { class: 'notiz' },
        'OSM-Leerstand ist lückenhaft gepflegt. Die Zahl ist eine Untergrenze.'));
  }
  setQuelle('leerstand', d.provenance);
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
   Bewusst neutral: hervorgehoben wird nur der Höchstwert, es wird nicht bewertet. */
const HOCH_IST_AUFFAELLIG = new Set([
  'einwohner', 'frequenzbringer', 'haltestellen', 'linien', 'abfahrten',
]);

async function zeigeVergleich() {
  const d = await (await fetch('/api/points/vergleich')).json();
  const ziel = document.getElementById('vergleich-inhalt');
  if (!d.zeilen.length) {
    ziel.replaceChildren(el('p', { class: 'hinweis-klein' },
      'Noch kein Punkt gemerkt. „Punkt merken" legt den aktuellen Standort ab.'));
  } else {
    const beste = {};
    for (const key of HOCH_IST_AUFFAELLIG) {
      const werte = d.zeilen.map((z) => z[key]).filter((v) => typeof v === 'number');
      if (werte.length > 1) beste[key] = Math.max(...werte);
    }
    const tab = el('table');
    tab.append(el('tr', {}, d.spalten.map((c) => el('th', {}, c.titel)), el('th', {}, '')));
    for (const z of d.zeilen) {
      const tr = el('tr', {});
      for (const c of d.spalten) {
        const v = z[c.key];
        const num = typeof v === 'number';
        const klassen = [num ? 'num' : 'text'];
        if (beste[c.key] !== undefined && v === beste[c.key]) klassen.push('best');
        tr.append(el('td', {
          class: klassen.join(' '),
          title: v === null || v === undefined ? '' : String(v),
        }, v === null || v === undefined ? '—' : num ? NF1.format(v) : String(v)));
      }
      tr.append(el('td', {}, el('button', {
        onclick: async () => {
          await fetch(`/api/points/${z.id}`, { method: 'DELETE' });
          zeigeVergleich();
        },
      }, 'löschen')));
      tab.append(tr);
    }
    ziel.replaceChildren(tab);
  }
  document.getElementById('vergleich-dialog').showModal();
}

/* ------------------------------------------------------------- Suche */

let sucheTimer = null;
const sucheFeld = document.getElementById('suche');
const trefferBox = document.getElementById('suche-treffer');
const sucheStatus = document.getElementById('suche-status');

/* Debounce ≥ 1 s — Nominatim erlaubt 1 Anfrage/Sekunde (Spec §5). */
const DEBOUNCE_MS = 1100;

sucheFeld.addEventListener('input', () => {
  clearTimeout(sucheTimer);
  const q = sucheFeld.value.trim();
  if (q.length < 3) { trefferBox.hidden = true; sucheStatus.textContent = ''; return; }
  sucheStatus.textContent = 'wartet (max. 1 Anfrage/s) …';
  sucheTimer = setTimeout(() => sucheAusfuehren(q), DEBOUNCE_MS);
});

document.getElementById('suche-form').addEventListener('submit', (e) => {
  e.preventDefault();
  clearTimeout(sucheTimer);
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
    document.getElementById('fuss-stats').textContent =
      `Cache: ${s.total} Einträge · echte Abrufe seit Start: ${s.outbound_requests_total}`;
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
];

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
      f.gesetzt ? el('div', { class: 'herkunft' }, 'frei gewählt, keine Datengrundlage') : null);
    gitter.append(feld);
  }

  const herleitung = v.besuche_herleitung;
  const eingaben = schaetzBlock('Annahmen', gitter,
    el('div', { class: 'notiz' },
      el('strong', {}, 'Besuche je Einwohner und Jahr: '), herleitung.herleitung),
    v.wettbewerber_alternative ? el('div', { class: 'notiz' },
      `${v.wettbewerber_alternative.hinweis} Im Umkreis liegen insgesamt `
      + `${NF.format(v.wettbewerber_alternative.alle_gastronomie)} gastronomische Betriebe.`) : null);

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

  ziel.replaceChildren(banner, eingaben, ergebnis, formel, grenzen, quellen);
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

function zeigeSchaetzErgebnis(d, ziel) {
  const e = d.ergebnis;
  const z = d.zwischenschritte;

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
      + 'Liegt die geforderte Miete darüber, trägt der Standort sich unter diesen Annahmen nicht.'));
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
