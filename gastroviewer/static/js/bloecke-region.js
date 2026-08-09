/* Blöcke, die über Gemeinde oder Kreis zugeordnet werden: Einkommen,
 * Kriminalstatistik, Wahl, Luft, Kalender, IHK, Baurecht, Passantenfrequenz,
 * Sonne, Pendler, Klima, Overture, Lärm, Baustellen, Märkte, Kurzzeit-
 * vermietung, Messe, Tourismus, amtliche Anker, Viertel-Steckbrief, Dynamik,
 * Kreisprofil, ÖPNV-Abfahrten, Quellen.
 *
 * Die größte Gruppe. Gemeinsam ist ihnen, dass sie erst laufen können, wenn
 * der Zensusblock den Gemeindeschlüssel geliefert hat.
 */

import { NF, NF1, NF2, fmtIsoDatum, nfFest } from './format.js';
import { state } from './state.js';
import { block, el, esc, fehlerbox, hinweisZeile, kennzahl, liste, setInhalt, setQuelle, setStatus, warnungen, zeigeBlockFehler } from './dom.js';
import { hole } from './api.js';
import { POI_STIL, springeZuPoi, zeichnePois } from './karte-ebenen.js';
import { pflegeleiste } from './vergleich.js';
import { brwBlock, setzeBrwEbene, setzeZusatzebenen } from './bloecke-laender.js';
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

export {
  datumKurz,
  entferneGenesisZugang,
  ladeEinkommen,
  ladeGenesis,
  ladeIhkBerlin,
  ladeKalender,
  ladeKreisprofil,
  ladeLaerm,
  ladePendler,
  ladePks,
  ladeWahl,
  speichereGenesisZugang,
  zeigeAirbnb,
  zeigeBaurecht,
  zeigeBaustellen,
  zeigeDynamik,
  zeigeEinkommen,
  zeigeFrequenz,
  zeigeGenesis,
  zeigeGenesisOptIn,
  zeigeGtfs,
  zeigeIhkAngebot,
  zeigeIhkBerlin,
  zeigeIndikatoren,
  zeigeKalender,
  zeigeKlima,
  zeigeKreisprofil,
  zeigeLaerm,
  zeigeLinks,
  zeigeLuft,
  zeigeMaerkte,
  zeigeMesse,
  zeigeOverture,
  zeigePendler,
  zeigePks,
  zeigeSonne,
  zeigeTourismus,
  zeigeWahl,
};
