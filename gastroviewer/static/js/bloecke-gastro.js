/* Die Kernblöcke am Punkt: Standortkopf, Bevölkerung, Wohnen, Gastronomie,
 * Umfeld, Leerstände, Handelsregister, Systemgastronomie.
 *
 * Die Blockgruppe, die den Standort selbst beschreibt — alles, was
 * unmittelbar am gewählten Punkt hängt und nicht erst über den
 * Gemeindeschlüssel zugeordnet werden muss.
 */

import { NF, NF1, NF2, fmtIsoDatum, zahl } from './format.js';
import { state } from './state.js';
import { el, esc, fehlerbox, kennzahl, liste, setInhalt, setQuelle, setStatus, warnungen, zeigeBlockFehler } from './dom.js';
import { hole } from './api.js';
import { BRANCHEN, BRANCHE_SPEICHER, brancheKennzahlen } from './branche.js';
import { karte } from './karte.js';
import { springeZuPoi, zeichnePois, zeichneZensus } from './karte-ebenen.js';
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

export {
  brancheBereich,
  fuelleVersorgungsgrad,
  kundenprofilSatz,
  ladeMarke,
  ladeRegister,
  oeffnungsluecken,
  snackBereich,
  versorgungsgrad,
  zeigeFranchise,
  zeigeKopf,
  zeigeLeerstandsmelder,
  zeigeOsm,
  zeigeRegister,
  zeigeZensus,
};
