/* Blöcke, die erst auf Knopfdruck laden: ÖPNV-Einzugsgebiet, Rad-Liefergebiet,
 * Erreichbarkeit zu Fuß.
 *
 * Sie stehen zusammen, weil sie dieselbe Zurückhaltung teilen: Jede dieser
 * Rechnungen kostet eine große Abfrage, deshalb passiert sie nur auf
 * ausdrückliche Anforderung — und der Block sagt das vorher.
 */

import { NF, NF1 } from './format.js';
import { state } from './state.js';
import { el, fehlerbox, hinweisZeile, kennzahl, setInhalt, setQuelle, setStatus, warnungen, zeigeBlockFehler } from './dom.js';
import { hole } from './api.js';
import { karte } from './karte.js';
import { farbe } from './karte-ebenen.js';
import { pflegeleiste } from './vergleich.js';
import { zeigeOsm } from './bloecke-gastro.js';
import { GEH_STUFEN, zeigeGehweg } from './bloecke-laender.js';
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

export {
  ladeGehweg,
  ladeLiefergebiet,
  ladeOepnvEinzug,
  zeichneLieferflaeche,
  zeigeGehwegAngebot,
  zeigeLieferAngebot,
  zeigeLiefergebiet,
  zeigeOepnvEinzug,
  zeigeOepnvEinzugAngebot,
};
