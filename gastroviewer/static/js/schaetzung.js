import { NF, NF1, NF2 } from './format.js';
import {
  block, el, fehlerbox, kennzahl, setInhalt, setQuelle, setStatus, warnungen,
} from './dom.js';
import { state } from './state.js';
import { hole } from './api.js';
import { BRANCHEN, BRANCHE_SPEICHER, brancheKennzahlen } from './branche.js';

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

export { schaetzState, spanne, zeigeSchaetzung };
