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
  NF, NF1, NF2, OVERPASS_WARNSCHWELLE, fmtIsoDatum, nfFest, zahl,
} from './js/format.js';
import { state } from './js/state.js';
import {
  beiBlockRender, block, el, esc, fehlerbox, hinweisZeile, kennzahl, liste,
  setInhalt, setQuelle, setStatus, warnungen, zeigeBlockFehler,
} from './js/dom.js';
import { hole } from './js/api.js';
import { planeScoreUpdate, zeigeScore } from './js/score-bruecke.js';
import { BRANCHEN, BRANCHE_SPEICHER, brancheKennzahlen } from './js/branche.js';
import { schaetzState, spanne, zeigeSchaetzung } from './js/schaetzung.js';
import { ueberlappungen } from './js/geometrie.js';
import {
  zeigeFahrzeitAngebot, zeigeGehwegAngebot, zeigeLieferAngebot,
  zeigeOepnvEinzugAngebot,
} from './js/bloecke-mobilitaet.js';
import {
  ladeRegister, zeigeKopf, zeigeLeerstandsmelder, zeigeOsm, zeigeZensus,
} from './js/bloecke-gastro.js';
import {
  ladeEinkommen, ladeGenesis, ladeKalender, ladeKreisprofil, ladeLaerm, ladePendler, ladePks, ladeWahl, zeigeAirbnb, zeigeBaurecht, zeigeBaustellen, zeigeDynamik, zeigeFrequenz, zeigeGtfs, zeigeIhkAngebot, zeigeIndikatoren, zeigeKlima, zeigeLinks, zeigeLuft, zeigeMaerkte, zeigeMesse, zeigeOverture, zeigeSonne, zeigeTourismus,
} from './js/bloecke-region.js';
import {
  zeigePlanung, zeigeRadzaehlung, zeigeVerkehrsmenge,
} from './js/bloecke-laender.js';
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
    block('fahrzeit', '4h · Fahrzeit-Einzugsgebiet (Auto)'),
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
  zeigeFahrzeitAngebot();
  zeigeOepnvEinzugAngebot();
  zeigeIhkAngebot();
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
