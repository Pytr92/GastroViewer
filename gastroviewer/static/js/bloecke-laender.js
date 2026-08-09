/* Bodenrichtwerte als Kartenebene und die Blöcke mit Landes- oder Stadtbezug:
 * Radzählung, Verkehrsmenge, Planungsrecht, Gehweg.
 *
 * Zusammengefasst, weil sie alle an einem Landesdienst hängen und die
 * Verfügbarkeit je Bundesland unterschiedlich ist — der Block sagt jeweils,
 * was es für dieses Land gibt und was nicht.
 */

import { NF, NF1 } from './format.js';
import { state } from './state.js';
import { block, el, fehlerbox, hinweisZeile, kennzahl, liste, setInhalt, setQuelle, setStatus, warnungen } from './dom.js';
import { hole } from './api.js';
import { ebenenSchalter, karte } from './karte.js';
import { farbe } from './karte-ebenen.js';
import { ladeGehweg } from './bloecke-mobilitaet.js';
import { zeigeLinks } from './bloecke-region.js';
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

export {
  GEH_STUFEN,
  brwBlock,
  brwState,
  entferneBrwEbene,
  frageBodenrichtwertAb,
  setzeBrwEbene,
  setzeZusatzebenen,
  zeichneGehflaeche,
  zeigeGehweg,
  zeigePlanung,
  zeigeRadzaehlung,
  zeigeVerkehrsmenge,
  zusatzState,
};
