/* Standortbericht — druckbare Seite zu einem gemerkten Punkt.
 *
 * Dieselben Grundsätze wie in der Anwendung: kein Wert ohne Herkunft, fehlende
 * Werte erscheinen als „—" und nie als 0, bewertet wird nur, was der Nutzer
 * selbst bewertet hat. Der Bericht liest ausschließlich gespeicherte bzw.
 * lokale Daten — er löst keinen Abruf bei einem externen Dienst aus.
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

function datum(ts) {
  if (!ts) return null;
  return new Date(ts * 1000).toLocaleDateString('de-DE',
    { year: 'numeric', month: '2-digit', day: '2-digit' });
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

async function start() {
  const ziel = document.getElementById('bericht');
  const id = new URLSearchParams(location.search).get('punkt');
  if (!id) {
    ziel.replaceChildren(el('p', { class: 'warnung' },
      'Kein Punkt angegeben. Der Bericht wird aus dem Standortvergleich heraus '
      + 'geöffnet („Bericht" neben einem gemerkten Punkt).'));
    return;
  }
  let p, defs, verlauf;
  try {
    [p, defs, verlauf] = await Promise.all([
      hole(`/api/points/${id}`),
      hole('/api/points/vergleich'),
      hole(`/api/points/${id}/verlauf`),
    ]);
  } catch (e) {
    ziel.replaceChildren(el('p', { class: 'warnung' },
      `Bericht nicht ladbar: ${e.message}`));
    return;
  }

  document.title = `Standortbericht — ${p.label}`;
  const z = p.zeile || {};
  const payload = p.payload || {};
  const teile = [];

  /* --- Kopf --- */
  teile.push(el('div', { class: 'kopfzeile' },
    el('div', {},
      el('h1', {}, `Standortbericht: ${p.label}`),
      el('p', { class: 'untertitel' }, z.adresse || ''),
      el('p', { class: 'meta' },
        `Koordinaten ${p.lat}, ${p.lon} · Radius ${NF.format(p.radius)} m · `
        + `gemerkt am ${datum(p.created_at) || '—'}`
        + (p.geprueft_am ? ` · zuletzt geprüft am ${datum(p.geprueft_am)}` : ''))),
    el('div', { class: 'kein-druck' },
      el('button', { onclick: () => window.print() }, 'Drucken / als PDF sichern'),
      ' ',
      el('a', { class: 'knopf-link', href: '/' }, 'zur Anwendung'))));

  teile.push(el('div', { class: 'notiz' },
    el('strong', {}, 'Daten-Browser, keine Prognose. '),
    'Jeder Wert stammt aus einer realen Antwort der unten genannten Quellen zum '
    + 'jeweils angegebenen Stand. „—" heißt: liegt für diesen Punkt nicht vor — '
    + 'das ist kein Nullwert. Bewertet wird nur, was unter „Eigene Einschätzung" '
    + 'ausdrücklich vom Nutzer kommt.'));

  /* --- Eigene Einschätzung --- */
  if (p.bewertung || p.notiz) {
    teile.push(el('div', { class: 'eigene' },
      el('div', { class: 'kennung' }, 'Eigene Einschätzung (keine Datengrundlage)'),
      p.bewertung ? el('div', {}, el('strong', {}, 'Note: '), NOTEN[p.bewertung] || p.bewertung) : null,
      p.notiz ? el('div', {}, el('strong', {}, 'Notiz: '), p.notiz) : null));
  }

  /* --- Karte: Umkreis und Wettbewerber. Bewusst im Bericht, denn ein
     Kennzahlenblatt ohne Lagebild ist für Bank und Vermieter nur die halbe
     Aussage. Gezeichnet wird aus dem GESPEICHERTEN Datenstand — die Karte
     löst keinen neuen Abruf bei den Fachdiensten aus (die Kacheln kommen,
     wie in der Anwendung, von OpenStreetMap). --- */
  if (typeof L !== 'undefined' && p.lat && p.lon) {
    const kartenBox = el('div', { id: 'bericht-karte' });
    teile.push(kartenBox);
    const gastro = payload.bloecke?.osm?.data?.gastronomie || [];
    teile.push(el('p', { class: 'meta' },
      `Karte: Radius ${NF.format(p.radius)} m um den Standort, rote Punkte = `
      + `${NF.format(gastro.length)} gastronomische Betriebe zum gespeicherten `
      + 'Stand. Karte © OpenStreetMap-Mitwirkende (ODbL).'));
    // Nach dem Einhängen ins DOM initialisieren — Leaflet braucht Maße.
    setTimeout(() => {
      // setView VOR den Layern: ohne Ausgangszustand wirft Leaflet beim
      // ersten Tooltip („layerPointToLatLng of undefined") und die
      // Markerschleife bricht ab — im Browser-Check aufgefallen.
      const karte = L.map('bericht-karte', {
        zoomControl: true, attributionControl: true, scrollWheelZoom: false,
      }).setView([p.lat, p.lon], 15);
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap-Mitwirkende</a>',
      }).addTo(karte);
      const kreis = L.circle([p.lat, p.lon], {
        radius: p.radius, color: '#1f5f8b', weight: 1.5, fillOpacity: 0.05,
      }).addTo(karte);
      L.marker([p.lat, p.lon]).addTo(karte);
      for (const g of gastro) {
        L.circleMarker([g.lat, g.lon], {
          radius: 4, color: '#a32020', weight: 1, fillColor: '#d94b4b',
          fillOpacity: 0.85,
        }).bindTooltip(`${g.name || '(ohne Name)'} · ${g.typ_label || ''}`)
          .addTo(karte);
      }
      karte.fitBounds(kreis.getBounds().pad(0.08));
    }, 0);
  }

  /* --- Kennzahlen je Gruppe, mit denselben Definitionen wie der Vergleich --- */
  const uebersprungen = new Set(['label', 'bewertung', 'notiz', 'adresse', 'gemeinde', 'radius']);
  for (const g of defs.gruppen || []) {
    if (g.key === 'standort') continue;
    const spalten = (defs.spalten || []).filter(
      (c) => c.gruppe === g.key && !uebersprungen.has(c.key));
    if (!spalten.length) continue;
    const belegt = spalten.filter((c) => z[c.key] !== null && z[c.key] !== undefined);
    teile.push(el('h2', {}, g.titel));
    if (!belegt.length) {
      teile.push(el('p', { class: 'hinweis' }, 'Für diesen Punkt liegen hier keine Werte vor.'));
      continue;
    }
    const tab = el('table', {});
    for (const c of spalten) {
      tab.append(el('tr', {},
        el('th', {}, c.titel),
        el('td', { class: z[c.key] === null || z[c.key] === undefined ? 'num fehlt' : 'num' },
          wert(z[c.key], c.stellen))));
    }
    teile.push(tab);
  }

  /* --- Verlauf, sobald es mehr als den ersten Stand gibt --- */
  const staende = verlauf.staende || [];
  if (staende.length > 1) {
    teile.push(el('h2', {}, 'Verlauf'));
    teile.push(el('p', { class: 'hinweis' },
      '„Neu prüfen" legt vor jedem neuen Abruf den alten Stand ab. Beweglich '
      + 'sind OSM, GTFS und die Zählstellen — Zensuswerte behalten ihren Stichtag.'));
    const tab = el('table', {},
      el('tr', {},
        el('th', {}, 'Stand'),
        el('th', { class: 'num' }, 'Gastronomie'),
        el('th', { class: 'num' }, 'bis 300 m'),
        el('th', { class: 'num' }, 'Leerstände'),
        el('th', { class: 'num' }, 'Frequenzbringer'),
        el('th', { class: 'num' }, 'Abfahrten/Tag')));
    for (const s of staende) {
      const sz = s.zeile || {};
      const zelle = (v) => el('td', { class: 'num' }, wert(v));
      const tr = el('tr', {},
        el('td', {}, `${s.ts || '—'}${s.aktuell ? ' (aktuell)' : ''}`),
        zelle(sz.gastro_gesamt), zelle(sz.gastro_bis_300),
        zelle(sz.leerstand_osm), zelle(sz.frequenzbringer), zelle(sz.abfahrten));
      if (s.aktuell) tr.style.fontWeight = '600';
      tab.append(tr);
    }
    teile.push(tab);
  }

  /* --- Hinweise aus den Daten --- */
  const hinweise = payload.hinweise || [];
  const zensusHinweise = payload.bloecke?.zensus?.data?.hinweise || [];
  for (const h of [...hinweise, ...zensusHinweise]) {
    teile.push(el('div', { class: 'notiz' }, h));
  }

  /* --- Quellen und Stände --- */
  teile.push(el('h2', {}, 'Quellen, Stände, Lizenzen'));
  const q = el('table', {},
    el('tr', {}, el('th', {}, 'Block'), el('th', {}, 'Quelle'),
      el('th', {}, 'Stand'), el('th', {}, 'Lizenz')));
  for (const [name, block] of Object.entries(payload.bloecke || {})) {
    const prov = block?.provenance;
    if (!prov) continue;
    q.append(el('tr', {},
      el('td', {}, name),
      el('td', {}, prov.source || '—'),
      el('td', {}, prov.stand || '—'),
      el('td', { class: 'quelle' }, prov.license || '—')));
  }
  teile.push(q);

  /* --- Grenzen --- */
  const grenzen = payload.grenzen || [];
  if (grenzen.length) {
    teile.push(el('h2', {}, 'Bekannte Grenzen dieser Daten'));
    teile.push(el('ul', {}, grenzen.map((g) => el('li', {}, g))));
  }

  teile.push(el('div', { class: 'fusszeile' },
    `Erstellt mit dem Standort-Datenterminal am ${new Date().toLocaleDateString('de-DE')}. `
    + 'Der Bericht zeigt den gespeicherten Datenstand des Punktes; „Neu prüfen" im '
    + 'Standortvergleich erneuert ihn.'));

  ziel.replaceChildren(...teile);
}

start();
