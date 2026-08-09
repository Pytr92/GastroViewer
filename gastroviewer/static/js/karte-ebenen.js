/* Kartenebenen: gemerkte Punkte, Zensusgitter, Umfeld-Marker — und das
 * Setzen des Standorts.
 *
 * `setzePunkt` steht hier, weil es Marker und Umkreis auf der Karte führt.
 * Es stößt am Ende das Laden aller Blöcke an — das aber über einen
 * Rückruf: Andernfalls hinge dieses Modul am gesamten Ladeorchester und
 * damit an jedem einzelnen Datenblock.
 */

import { NF, NF1, zahl } from './format.js';
import { el, esc } from './dom.js';
import { state } from './state.js';
import { karte } from './karte.js';

let nachPunktWahl = () => {};

export function beiPunktWahl(fn) {
  nachPunktWahl = typeof fn === 'function' ? fn : () => {};
}

/* ------------------------------------------- Gemerkte Punkte als Ebene */

/* Überschneidungen der Einzugsgebiete: Luftliniendistanz kleiner als die
   Summe der Radien. Reine Geometrie — ob die Überschneidung schlimm ist,
   hängt vom Konzept ab; der Hinweis sagt nur, DASS sie da ist. */

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
  nachPunktWahl();
}

export {
  FARBEN, METRIKEN, POI_STIL, farbe, grenzen, ladePunkteEbene, metrikWert,
  setzePunkt, springeZuPoi, zeichnePois, zeichneZensus, zeigeLegende,
};

/* sprungRing wird beim Springen neu gesetzt — als Lesezugriff nach außen,
   eine Kopie wuerde den Startwert einfrieren. */
export function aktuellerSprungRing() { return sprungRing; }
