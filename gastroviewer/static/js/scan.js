/* Erkundungsebenen: Übersichtsgitter, Flächen-Scan, Standort-Finder.
 *
 * Die Stufe vor dem Klicken — sie beantwortet „WO ist es überhaupt
 * interessant?", bevor ein Standort gewählt wird.
 *
 * Dieses Modul wird nur wegen seiner Wirkung eingebunden: Es hängt seine
 * Ebenen und Kartenereignisse selbst ein und gibt nichts nach außen. Der
 * Schnitt war entsprechend sauber — es braucht nichts vom übrigen
 * Programm außer den gemeinsamen Bausteinen.
 */

import { NF, zahl } from './format.js';
import { el } from './dom.js';
import { state } from './state.js';
import { hole } from './api.js';
import { karte } from './karte.js';
import { FARBEN, grenzen, setzePunkt } from './karte-ebenen.js';

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
