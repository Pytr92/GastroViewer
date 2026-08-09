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
  beiBlockRender, block, el, esc, fehlerbox, hinweisZeile, kennzahl, liste,
  setInhalt, setQuelle, setStatus, warnungen, zeigeBlockFehler,
} from './js/dom.js';
import { hole } from './js/api.js';
import { BRANCHEN, BRANCHE_SPEICHER, brancheKennzahlen } from './js/branche.js';
import { schaetzState, spanne, zeigeSchaetzung } from './js/schaetzung.js';
import { ueberlappungen } from './js/geometrie.js';
import { ebenenSchalter, karte, osmKarte } from './js/karte.js';
import {
  FARBEN, POI_STIL, aktuellerSprungRing, beiPunktWahl, farbe, grenzen,
  ladePunkteEbene, setzePunkt, springeZuPoi, zeichnePois, zeichneZensus,
} from './js/karte-ebenen.js';
/* Nur wegen seiner Wirkung: hängt Erkundungsebenen und Kartenereignisse ein. */
import './js/scan.js';
import {
  beiPunkteAenderung, merken, pflegeleiste, zeigeVergleich,
} from './js/vergleich.js';




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
    state.grenzen.map((g) => el('li', {}, el('span', { class: 'haupt' }, g)))));
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
    state.grenzen = p.grenzen || [];
  } catch { state.grenzen = []; }
  aktualisiereFuss();
}());

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
  get: aktuellerSprungRing,
  configurable: true,
});

/* Den Score einhängen, statt ihn in dom.js zu importieren — siehe Kopf von
   js/dom.js. Damit zeigt die Abhängigkeit nur in eine Richtung. */
beiBlockRender(planeScoreUpdate);

/* Die Kartenebene der gemerkten Punkte neu zeichnen, wenn sich die Liste
   ändert — als Rückruf, damit das Vergleichsmodul nicht die Karte
   importieren muss. */
beiPunkteAenderung(ladePunkteEbene);

/* Und das Laden aller Blöcke anstoßen, wenn ein Standort gewählt wurde —
   ebenfalls als Rückruf, damit das Kartenmodul nicht am Ladeorchester und
   damit an jedem einzelnen Datenblock hängt. */
beiPunktWahl(lade);
