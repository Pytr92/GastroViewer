/* Duell-Bericht „A gegen B" — zwei gemerkte Punkte Spalte an Spalte.
 *
 * Dieselben Grundsätze wie Anwendung und Einzelbericht: kein Wert ohne
 * Herkunft, „—" heißt „liegt nicht vor" und nie 0, und es gibt bewusst
 * keine „Gewinner"-Markierung — ob mehr Wettbewerb oder mehr Abfahrten gut
 * sind, hängt vom Konzept ab. Die Differenzspalte ist ein Fakt, keine
 * Wertung. Gezeichnet wird aus den GESPEICHERTEN Datenständen.
 */

'use strict';

const NF = new Intl.NumberFormat('de-DE');
const NF_FEST = new Map();
function nfFest(n) {
  if (!NF_FEST.has(n)) {
    NF_FEST.set(n, new Intl.NumberFormat('de-DE',
      { minimumFractionDigits: n, maximumFractionDigits: n }));
  }
  return NF_FEST.get(n);
}

const el = (tag, attrs = {}, ...kinder) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') n.className = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const kind of kinder.flat()) {
    if (kind === null || kind === undefined || kind === false) continue;
    n.append(kind.nodeType ? kind : document.createTextNode(String(kind)));
  }
  return n;
};

const NOTEN = { 1: '1 — sehr gut', 2: '2 — gut', 3: '3 — mittel', 4: '4 — schwach', 5: '5 — ungeeignet' };

function wert(v, stellen) {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') return (stellen === undefined ? nfFest(v % 1 ? 1 : 0) : nfFest(stellen)).format(v);
  return String(v);
}

async function hole(pfad) {
  const r = await fetch(pfad);
  if (!r.ok) {
    let detail = `HTTP ${r.status}`;
    try { detail = (await r.json()).detail || detail; } catch { /* egal */ }
    throw new Error(detail);
  }
  return r.json();
}

function lagekarte(containerId, p) {
  // setView VOR den Layern — die Lehre aus der Berichtskarte (Browser-Check).
  const karte = L.map(containerId, {
    zoomControl: false, attributionControl: true, scrollWheelZoom: false,
    dragging: false,
  }).setView([p.lat, p.lon], 15);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OSM-Mitwirkende</a>',
  }).addTo(karte);
  const kreis = L.circle([p.lat, p.lon], {
    radius: p.radius, color: '#1f5f8b', weight: 1.5, fillOpacity: 0.05,
  }).addTo(karte);
  L.marker([p.lat, p.lon]).addTo(karte);
  const gastro = p.payload?.bloecke?.osm?.data?.gastronomie || [];
  for (const g of gastro) {
    L.circleMarker([g.lat, g.lon], {
      radius: 3.5, color: '#a32020', weight: 1, fillColor: '#d94b4b',
      fillOpacity: 0.85,
    }).addTo(karte);
  }
  karte.fitBounds(kreis.getBounds().pad(0.08));
  return gastro.length;
}

async function start() {
  const ziel = document.getElementById('duell');
  const params = new URLSearchParams(location.search);
  const idA = params.get('a');
  const idB = params.get('b');
  if (!idA || !idB || idA === idB) {
    ziel.replaceChildren(el('p', { class: 'warnung' },
      'Der Duell-Bericht braucht zwei verschiedene Punkte (?a=ID&b=ID). '
      + 'Er wird aus dem Standortvergleich heraus geöffnet.'));
    return;
  }
  let a, b, defs;
  try {
    [a, b, defs] = await Promise.all([
      hole(`/api/points/${idA}`),
      hole(`/api/points/${idB}`),
      hole('/api/points/vergleich'),
    ]);
  } catch (e) {
    ziel.replaceChildren(el('p', { class: 'warnung' },
      `Duell-Bericht nicht ladbar: ${e.message}`));
    return;
  }

  document.title = `Duell — ${a.label} gegen ${b.label}`;
  const za = a.zeile || {};
  const zb = b.zeile || {};
  const teile = [];

  teile.push(el('div', { class: 'kopfzeile' },
    el('div', {},
      el('h1', {}, `Duell: ${a.label} gegen ${b.label}`),
      el('p', { class: 'untertitel' },
        `${za.adresse || '—'}  ·  gegen  ·  ${zb.adresse || '—'}`)),
    el('div', { class: 'kein-druck' },
      el('button', { onclick: () => window.print() }, 'Drucken / als PDF sichern'),
      ' ',
      el('a', { class: 'knopf-link', href: '/' }, 'zur Anwendung'))));

  teile.push(el('div', { class: 'notiz' },
    el('strong', {}, 'Daten-Browser, keine Prognose. '),
    'Beide Spalten zeigen die gespeicherten Datenstände der Punkte. Die '
    + 'Differenz ist ein Fakt, keine Wertung — ob mehr Wettbewerb oder mehr '
    + 'Abfahrten gut sind, hängt vom Konzept ab. „—" heißt: liegt nicht vor.'));

  /* --- Eigene Einschätzungen nebeneinander --- */
  if (a.bewertung || a.notiz || b.bewertung || b.notiz) {
    const seite = (p) => el('div', {},
      el('strong', {}, p.label),
      p.bewertung ? el('div', {}, `Note: ${NOTEN[p.bewertung] || p.bewertung}`) : null,
      p.notiz ? el('div', {}, `Notiz: ${p.notiz}`) : null);
    teile.push(el('div', { class: 'eigene' },
      el('div', { class: 'kennung' }, 'Eigene Einschätzung (keine Datengrundlage)'),
      el('div', { class: 'duell-karten' }, seite(a), seite(b))));
  }

  /* --- Beide Lagekarten --- */
  const boxA = el('div', {},
    el('div', { class: 'kennung' }, `${a.label} — Radius ${NF.format(a.radius)} m`),
    el('div', { class: 'duell-karte', id: 'duell-karte-a' }));
  const boxB = el('div', {},
    el('div', { class: 'kennung' }, `${b.label} — Radius ${NF.format(b.radius)} m`),
    el('div', { class: 'duell-karte', id: 'duell-karte-b' }));
  teile.push(el('div', { class: 'duell-karten' }, boxA, boxB));
  teile.push(el('p', { class: 'meta' },
    'Rote Punkte = gastronomische Betriebe zum gespeicherten Stand. '
    + 'Karten © OpenStreetMap-Mitwirkende (ODbL).'));

  if (a.radius !== b.radius) {
    teile.push(el('div', { class: 'warnung' },
      `Achtung, ungleiche Radien: ${NF.format(a.radius)} m gegen `
      + `${NF.format(b.radius)} m. Absolute Zahlen (Einwohner, Betriebe) sind `
      + 'damit nicht direkt vergleichbar — die je-1000-Kennzahlen schon eher.'));
  }

  /* --- Kennzahlen je Gruppe, dieselben Definitionen wie der Vergleich --- */
  const uebersprungen = new Set(['label', 'bewertung', 'notiz', 'adresse', 'gemeinde', 'radius']);
  for (const g of defs.gruppen || []) {
    if (g.key === 'standort') continue;
    const spalten = (defs.spalten || []).filter(
      (c) => c.gruppe === g.key && !uebersprungen.has(c.key));
    const belegt = spalten.filter(
      (c) => (za[c.key] !== null && za[c.key] !== undefined)
        || (zb[c.key] !== null && zb[c.key] !== undefined));
    if (!belegt.length) continue;
    teile.push(el('h2', {}, g.titel));
    const tab = el('table', {},
      el('tr', {},
        el('th', {}, 'Kennzahl'),
        el('th', { class: 'num' }, a.label),
        el('th', { class: 'num' }, b.label),
        el('th', { class: 'num' }, 'Differenz (B − A)')));
    for (const c of belegt) {
      const va = za[c.key];
      const vb = zb[c.key];
      const beide = typeof va === 'number' && typeof vb === 'number';
      tab.append(el('tr', {},
        el('th', {}, c.titel),
        el('td', { class: va === null || va === undefined ? 'num fehlt' : 'num' },
          wert(va, c.stellen)),
        el('td', { class: vb === null || vb === undefined ? 'num fehlt' : 'num' },
          wert(vb, c.stellen)),
        el('td', { class: 'num duell-diff' },
          beide ? (vb - va > 0 ? '+' : '') + wert(vb - va, c.stellen) : '—')));
    }
    teile.push(tab);
  }

  /* --- Quellen und Stände (vereint über beide Punkte) --- */
  teile.push(el('h2', {}, 'Quellen, Stände, Lizenzen'));
  const q = el('table', {},
    el('tr', {}, el('th', {}, 'Block'), el('th', {}, 'Quelle'),
      el('th', {}, `Stand ${a.label}`), el('th', {}, `Stand ${b.label}`),
      el('th', {}, 'Lizenz')));
  const bloecke = new Set([
    ...Object.keys(a.payload?.bloecke || {}),
    ...Object.keys(b.payload?.bloecke || {}),
  ]);
  for (const name of [...bloecke].sort()) {
    const pa = a.payload?.bloecke?.[name]?.provenance;
    const pb = b.payload?.bloecke?.[name]?.provenance;
    const prov = pa || pb;
    if (!prov) continue;
    q.append(el('tr', {},
      el('td', {}, name),
      el('td', {}, prov.source || '—'),
      el('td', {}, pa?.stand || '—'),
      el('td', {}, pb?.stand || '—'),
      el('td', { class: 'quelle' }, prov.license || '—')));
  }
  teile.push(q);

  teile.push(el('div', { class: 'fusszeile' },
    `Erstellt mit dem Standort-Datenterminal am ${new Date().toLocaleDateString('de-DE')}. `
    + 'Der Duell-Bericht zeigt die gespeicherten Datenstände; „Neu prüfen" im '
    + 'Standortvergleich erneuert sie.'));

  ziel.replaceChildren(...teile);

  // Karten nach dem Einhängen initialisieren — Leaflet braucht Maße.
  setTimeout(() => {
    if (typeof L !== 'undefined') {
      lagekarte('duell-karte-a', { lat: a.lat, lon: a.lon, radius: a.radius, payload: a.payload });
      lagekarte('duell-karte-b', { lat: b.lat, lon: b.lon, radius: b.radius, payload: b.payload });
    }
  }, 0);
}

start();
