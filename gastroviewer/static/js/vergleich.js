/* Gemerkte Punkte: Vergleichstabelle, Pflegelauf, Wächter, Ranking.
 *
 * Der Arbeitsteil des Werkzeugs — hier wird aus Einzelabfragen eine
 * Kandidatenliste. Vergleich und Ranking liegen bewusst zusammen: Das
 * Ranking liest die Spaltenwahl und die Auffälligkeitsrichtung der
 * Vergleichstabelle, eine Trennung ergäbe zwei Module, die sich
 * gegenseitig importieren.
 *
 * Die Kartenebene der gemerkten Punkte wird über einen Rückruf
 * benachrichtigt statt importiert — sonst hinge dieses Modul an der
 * gesamten Karte, nur um nach dem Löschen eines Punktes neu zu zeichnen.
 */

import { NF, NF1, nfFest, zahl } from './format.js';
import { el, kennzahl, fehlerbox, hinweisZeile } from './dom.js';
import { ueberlappungen } from './geometrie.js';

let nachPunkteAenderung = () => {};

export function beiPunkteAenderung(fn) {
  nachPunkteAenderung = typeof fn === 'function' ? fn : () => {};
}

/* ---------------------------------------------------------- Vergleich */

async function merken() {
  if (state.lat === null) { alert('Erst einen Punkt in der Karte wählen.'); return; }
  const vorschlag = state.daten.adresse?.data?.display_name?.split(',').slice(0, 2).join(',')
    || `${state.lat}, ${state.lon}`;
  const label = prompt('Bezeichnung für diesen Standort:', vorschlag);
  if (!label) return;
  const btn = document.getElementById('btn-merken');
  btn.disabled = true; btn.textContent = 'speichert …';
  try {
    const r = await fetch('/api/points', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label, lat: state.lat, lon: state.lon, radius: state.radius }),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    await zeigeVergleich();
  } catch (e) {
    alert(`Konnte den Punkt nicht merken: ${e.message}`);
  } finally {
    btn.disabled = false; btn.textContent = 'Punkt merken';
  }
}

/* Spalten, bei denen ein hoher Wert im Vergleich hervorgehoben wird.
   Bewusst neutral: hervorgehoben wird nur der Höchstwert, es wird nicht bewertet.
   „Wettbewerber je 1.000 Einwohner" steht absichtlich nicht hier — dort wäre der
   Höchstwert die dichteste Konkurrenz, und die zu markieren liest sich wie ein Lob. */
const HOCH_IST_AUFFAELLIG = new Set([
  'einwohner', 'frequenzbringer', 'haltestellen', 'linien', 'abfahrten',
  'abfahrten_je_einwohner', 'abfahrten_mittag', 'mittagsanteil',
]);

/* Sichtbare Spaltengruppen. Die Tabelle ist auf 36 Spalten gewachsen; ohne
   Gruppen scrollt man an der Bezeichnung vorbei und findet nichts wieder.
   Abgeschaltet werden nur ganze Gruppen — einzelne Spalten würden die Tabelle
   in beliebig viele Zustände zerfallen lassen. */
const GRUPPEN_SPEICHER = 'gastroviewer.vergleichsgruppen';
let sichtbareGruppen = null;

function ladeGruppenwahl(gruppen) {
  if (sichtbareGruppen) return sichtbareGruppen;
  let gemerkt = null;
  try {
    gemerkt = JSON.parse(localStorage.getItem(GRUPPEN_SPEICHER) || 'null');
  } catch { gemerkt = null; }
  const gueltig = new Set(gruppen.map((g) => g.key));
  sichtbareGruppen = new Set(
    Array.isArray(gemerkt) && gemerkt.every((k) => gueltig.has(k))
      ? gemerkt
      : gruppen.filter((g) => g.vorgabe).map((g) => g.key),
  );
  // Feste Gruppen lassen sich nicht abwählen — ohne Bezeichnung ist die
  // Tabelle nicht lesbar.
  for (const g of gruppen) if (g.fest) sichtbareGruppen.add(g.key);
  return sichtbareGruppen;
}

function merkeGruppenwahl() {
  localStorage.setItem(GRUPPEN_SPEICHER, JSON.stringify([...sichtbareGruppen]));
}

/* Eigene Note und Notiz. Das Werkzeug bewertet bewusst nicht und stellt keine
   Rangfolge auf — der Nutzer darf und soll das aber. Gespeichert wird beim
   Verlassen des Feldes, nicht bei jedem Tastendruck. */
async function speichereEigenes(id, zeile) {
  try {
    const r = await fetch(`/api/points/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        notiz: zeile.notiz || null,
        bewertung: zeile.bewertung === '' || zeile.bewertung === null
          ? null : Number(zeile.bewertung),
      }),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
  } catch (e) {
    // Sonst ginge eine eingetippte Notiz bei Server-Schluckauf kommentarlos verloren.
    alert(`Notiz/Note konnte nicht gespeichert werden: ${e.message}`);
  }
}

function eigenesFeld(z, key) {
  if (key === 'bewertung') {
    const aus = el('select', {
      'aria-label': 'Eigene Note',
      onchange: (ev) => {
        z.bewertung = ev.target.value === '' ? null : Number(ev.target.value);
        speichereEigenes(z.id, z);
      },
    });
    for (const [wert, beschriftung] of [['', '—'], ['1', '1 sehr gut'], ['2', '2 gut'],
      ['3', '3 mittel'], ['4', '4 schwach'], ['5', '5 ungeeignet']]) {
      aus.append(el('option', {
        value: wert, selected: String(z.bewertung ?? '') === wert,
      }, beschriftung));
    }
    return aus;
  }
  return el('input', {
    type: 'text',
    value: z.notiz || '',
    maxlength: '2000',
    placeholder: 'eigene Notiz …',
    'aria-label': 'Eigene Notiz',
    onchange: (ev) => { z.notiz = ev.target.value; speichereEigenes(z.id, z); },
  });
}

async function zeigeVergleich() {
  const ziel = document.getElementById('vergleich-inhalt');
  let d;
  try {
    const r = await fetch('/api/points/vergleich');
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    d = await r.json();
  } catch (e) {
    ziel.replaceChildren(fehlerbox({ message: e.message }));
    document.getElementById('vergleich-dialog').showModal();
    return;
  }
  const gruppen = d.gruppen || [];
  const sichtbar = ladeGruppenwahl(gruppen);

  if (!d.zeilen.length) {
    ziel.replaceChildren(el('p', { class: 'hinweis-klein' },
      'Noch kein Punkt gemerkt. „Punkt merken" legt den aktuellen Standort ab.'));
    document.getElementById('vergleich-dialog').showModal();
    return;
  }

  const spalten = d.spalten.filter((c) => sichtbar.has(c.gruppe));

  /* Schalterleiste: je Gruppe ein Häkchen mit der Zahl ihrer Spalten. */
  const schalter = el('div', { class: 'gruppenwahl' },
    el('span', { class: 'gruppenwahl-titel' }, 'Spalten:'),
    gruppen.map((g) => {
      const anzahl = d.spalten.filter((c) => c.gruppe === g.key).length;
      const box = el('input', {
        type: 'checkbox',
        checked: sichtbar.has(g.key),
        disabled: !!g.fest,
        id: `gruppe-${g.key}`,
        onchange: (ev) => {
          if (ev.target.checked) sichtbar.add(g.key); else sichtbar.delete(g.key);
          merkeGruppenwahl();
          zeigeVergleich();
        },
      });
      return el('label', { class: g.fest ? 'fest' : '', for: `gruppe-${g.key}` },
        box, ` ${g.titel} (${anzahl})`);
    }),
    el('span', { class: 'gruppenwahl-zahl' },
      `${spalten.length} von ${d.spalten.length} Spalten · CSV enthält immer alle`));

  const beste = {};
  for (const key of HOCH_IST_AUFFAELLIG) {
    const werte = d.zeilen.map((z) => z[key]).filter((v) => typeof v === 'number');
    if (werte.length > 1) beste[key] = Math.max(...werte);
  }

  const tab = el('table', { class: 'vergleich-tabelle' });

  /* Gruppenzeile über den Spaltenköpfen — sonst weiß man nach dem dritten
     Scrollschritt nicht mehr, worauf man schaut. */
  const gruppenzeile = el('tr', { class: 'gruppenzeile' });
  for (const g of gruppen) {
    const n = spalten.filter((c) => c.gruppe === g.key).length;
    if (n) gruppenzeile.append(el('th', { colspan: String(n), class: `gr-${g.key}` }, g.titel));
  }
  gruppenzeile.append(el('th', {}, ''));
  tab.append(gruppenzeile);

  tab.append(el('tr', {}, spalten.map((c) => el('th', {}, c.titel)), el('th', {}, '')));

  for (const z of d.zeilen) {
    const tr = el('tr', {});
    for (const c of spalten) {
      /* Die beiden einzigen Felder, die der Nutzer selbst füllt. Sie werden
         direkt in der Tabelle bearbeitet — ein Dialog dafür wäre ein Umweg. */
      if (c.key === 'bewertung' || c.key === 'notiz') {
        tr.append(el('td', { class: 'eigen' }, eigenesFeld(z, c.key)));
        continue;
      }
      const v = z[c.key];
      const num = typeof v === 'number';
      const klassen = [num ? 'num' : 'text'];
      if (beste[c.key] !== undefined && v === beste[c.key]) klassen.push('best');
      tr.append(el('td', {
        class: klassen.join(' '),
        title: v === null || v === undefined ? '' : String(v),
      }, v === null || v === undefined ? '—'
         : num ? (c.stellen === undefined ? NF1 : nfFest(c.stellen)).format(v)
         : String(v)));
    }
    tr.append(el('td', { class: 'aktionen' },
      el('a', {
        class: 'knopf-link', href: `/bericht?punkt=${z.id}`,
        target: '_blank', rel: 'noopener',
        title: 'Druckbarer Bericht zu diesem Punkt — PDF über die Druckfunktion des Browsers',
      }, 'Bericht'),
      el('button', {
        title: 'Alle Quellen erneut abfragen (am Cache vorbei) und Veränderungen zeigen',
        onclick: () => neuPruefen(z),
      }, 'neu prüfen'),
      el('button', {
        title: 'Nur die OSM-Gastronomie gegen den gespeicherten Stand halten — '
          + 'schnell, ohne den Punkt zu verändern',
        onclick: () => waechterPruefen(z),
      }, 'Wächter'),
      el('button', {
        onclick: async () => {
          try {
            await fetch(`/api/points/${z.id}`, { method: 'DELETE' });
          } catch { /* Der Neuaufbau unten zeigt den echten Zustand. */ }
          zeigeVergleich();
        },
      }, 'löschen')));
    tab.append(tr);
  }

  /* Überschneidende Einzugsgebiete sind keine unabhängigen Optionen. */
  const paare = ueberlappungen(d.zeilen);
  const ueberlappungsBox = paare.length
    ? el('div', { class: 'warnung' },
      el('strong', {}, 'Einzugsgebiete überschneiden sich: '),
      ...paare.map((p) => el('div', { class: 'legende-zeile' },
        `${p.a} ↔ ${p.b} (Abstand ${NF.format(p.distanz_m)} m, Kreise `
        + `überlappen um ${NF.format(p.um_m)} m) `,
        el('button', {
          class: 'kein-druck',
          title: 'Einwohner in beiden Umkreisen über das Zensusgitter zählen',
          onclick: (ev) => kannibalisierungRechnen(p, ev.target),
        }, 'Gemeinsame Einwohner rechnen'))),
      el('div', { class: 'hinweis-klein' },
        'Diese Kandidaten teilen sich einen Teil derselben Einwohner — die '
        + 'Kartenebene „Gemerkte Punkte" zeigt es. Ob das stört, hängt vom '
        + 'Konzept ab; die Geometrie sagt nur, dass es so ist.'))
    : null;

  // .filter(Boolean): rankingBereich() liefert unter zwei Punkten null, und
  // replaceChildren würde daraus das sichtbare Wort „null" machen.
  ziel.replaceChildren(...[
    schalter,
    pflegeleiste(d.zeilen),
    ueberlappungsBox,
    el('div', { class: 'tabelle-rahmen' }, tab),
    rankingBereich(d),
  ].filter(Boolean));
  // Die Kartenebene „Gemerkte Punkte" spiegelt den Bestand — nach Merken
  // oder Löschen (beides landet hier) wird sie nachgeführt.
  nachPunkteAenderung();
  document.getElementById('vergleich-dialog').showModal();
}

/* ------------------------------------- Datensicherung und Pflegelauf */

/* Sichern lädt alle Punkte samt Verlauf als eine JSON-Datei herunter;
   Einspielen liest so eine Datei wieder ein (Dubletten werden erkannt).
   „Alle neu prüfen" ist der monatliche Pflegelauf in einem Klick — mit
   Kostenansage, denn je Punkt läuft u. a. eine Overpass-Abfrage. */
function pflegeleiste(zeilen) {
  const dateiwahl = el('input', {
    type: 'file', accept: 'application/json,.json', hidden: true,
    onchange: async (ev) => {
      const datei = ev.target.files && ev.target.files[0];
      if (!datei) return;
      let daten;
      try {
        daten = JSON.parse(await datei.text());
      } catch {
        alert('Die Datei ist kein lesbares JSON.');
        return;
      }
      const r = await fetch('/api/points/import', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(daten),
      });
      const antwort = await r.json().catch(() => ({}));
      if (!r.ok) {
        alert(`Einspielen fehlgeschlagen: ${antwort.detail || `HTTP ${r.status}`}`);
        return;
      }
      alert(`Sicherung eingespielt: ${antwort.neu} Punkt(e) neu, `
        + `${antwort.uebersprungen} bereits vorhanden.`);
      zeigeVergleich();
    },
  });
  return el('div', { class: 'pflegeleiste' },
    el('a', {
      class: 'knopf-link', href: '/api/points/export',
      title: 'Alle gemerkten Punkte samt Verlauf und Notizen als eine Datei sichern',
    }, 'Sichern (Datei)'),
    el('button', { onclick: () => dateiwahl.click() }, 'Sicherung einspielen'),
    dateiwahl,
    zeilen.length > 1 ? el('button', {
      title: 'Alle gemerkten Punkte nacheinander neu prüfen (je Punkt u. a. eine Overpass-Abfrage)',
      onclick: () => alleNeuPruefen(zeilen),
    }, `alle ${zeilen.length} neu prüfen`) : null,
    ...duellWahl(zeilen));
}

/* Duell-Bericht: die Endauswahl ist fast immer ein Zweikampf. Zwei Punkte
   wählen, eine Druckseite Spalte an Spalte mit beiden Lagekarten. */
function duellWahl(zeilen) {
  if (zeilen.length < 2) return [];
  const wahl = (id, vorgabe) => el('select', { id },
    zeilen.map((z, i) => {
      const o = el('option', { value: String(z.id) }, z.label);
      if (i === vorgabe) o.selected = true;
      return o;
    }));
  const a = wahl('duell-a', 0);
  const b = wahl('duell-b', 1);
  return [
    el('span', { class: 'gruppenwahl-titel', style: 'margin-left:12px' }, 'Duell:'),
    a, el('span', {}, 'gegen'), b,
    el('button', {
      title: 'Druckseite: beide Kandidaten Spalte an Spalte, mit beiden Lagekarten',
      onclick: () => {
        if (a.value === b.value) { alert('Zwei verschiedene Punkte wählen.'); return; }
        window.open(`/duell?a=${a.value}&b=${b.value}`, '_blank', 'noopener');
      },
    }, 'Duell-Bericht'),
  ];
}

async function alleNeuPruefen(zeilen) {
  const sicher = confirm(
    `Alle ${zeilen.length} gemerkten Punkte jetzt neu prüfen?\n\n`
    + 'Das fragt je Punkt alle Quellen erneut ab (am Cache vorbei), darunter '
    + `je eine Overpass-Abfrage — insgesamt ${zeilen.length} Stück, nacheinander. `
    + 'Der bisherige Stand wandert jeweils in den Verlauf.');
  if (!sicher) return;
  const inhalt = document.getElementById('vergleich-inhalt');
  const box = el('div', { class: 'verlauf-ergebnis' });
  inhalt.prepend(box);
  const befunde = [];
  for (let i = 0; i < zeilen.length; i += 1) {
    const z = zeilen[i];
    box.replaceChildren(el('div', { class: 'laden' }),
      `Pflegelauf ${i + 1} von ${zeilen.length}: „${z.label}" …`);
    try {
      const r = await fetch(`/api/points/${z.id}/pruefung`, { method: 'POST' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      const n = d.veraendert.length + d.neue_betriebe.length
        + d.verschwundene_betriebe.length;
      befunde.push(`${z.label}: ${n ? `${n} Veränderung(en)` : 'unverändert'}`);
    } catch (e) {
      befunde.push(`${z.label}: fehlgeschlagen (${e.message})`);
    }
  }
  await zeigeVergleich();
  document.getElementById('vergleich-inhalt').prepend(
    el('div', { class: 'verlauf-ergebnis' },
      el('strong', {}, `Pflegelauf abgeschlossen (${zeilen.length} Punkte)`),
      el('ul', { class: 'liste' },
        befunde.map((b) => el('li', {}, el('span', { class: 'haupt' }, b)))),
      el('div', { class: 'hinweis-klein' },
        'Details je Punkt: „neu prüfen" am einzelnen Punkt zeigt die '
        + 'veränderten Kennzahlen und Betriebe.')));
}

/* --------------------------------- Kannibalisierungs-Check (Z6) */

/* Macht aus der Geometrie-Warnung eine Zahl: Einwohner, deren Zensuszelle
   in BEIDEN Umkreisen liegt. Zwei Zensus-Abfragen je Rechnung — deshalb
   auf Knopfdruck, nicht automatisch. */
async function kannibalisierungRechnen(paar, knopf) {
  const box = el('div', { class: 'verlauf-ergebnis' },
    el('div', { class: 'laden' }),
    `Zensuszellen für „${paar.a}" und „${paar.b}" werden gezählt …`);
  document.getElementById('vergleich-inhalt').prepend(box);
  if (knopf) knopf.disabled = true;
  let d;
  try {
    const r = await fetch(`/api/points/kannibalisierung?a=${paar.aId}&b=${paar.bId}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    d = await r.json();
  } catch (e) {
    box.replaceChildren(el('div', { class: 'fehlerbox' },
      `Kannibalisierungs-Check fehlgeschlagen: ${e.message}`));
    if (knopf) knopf.disabled = false;
    return;
  }
  if (knopf) knopf.disabled = false;
  if (!d.ueberlappung) {
    box.replaceChildren(el('strong', {}, 'Keine Überlappung'),
      el('div', {}, `${paar.a} und ${paar.b} überschneiden sich nicht mehr.`));
    return;
  }
  box.replaceChildren(
    el('strong', {}, `Kannibalisierung: ${d.a.label} ↔ ${d.b.label}`),
    el('div', { class: 'kennzahlen' },
      kennzahl('Gemeinsame Einwohner', d.gemeinsame_einwohner),
      kennzahl(`Anteil am Umkreis „${d.a.label}"`, d.anteil_an_a_prozent, '%', 1),
      kennzahl(`Anteil am Umkreis „${d.b.label}"`, d.anteil_an_b_prozent, '%', 1),
      kennzahl(`Einwohner „${d.a.label}" (${NF.format(d.a.radius_m)} m)`, d.einwohner_a),
      kennzahl(`Einwohner „${d.b.label}" (${NF.format(d.b.radius_m)} m)`, d.einwohner_b)),
    ...(d.hinweise || []).map((h) => hinweisZeile(h)),
    el('button', {
      class: 'kein-druck',
      onclick: (ev) => ev.target.closest('.verlauf-ergebnis').remove(),
    }, 'ausblenden'));
}

/* ------------------------------------- Veränderungs-Wächter (Z5) */

/* Der leichte Bruder von „neu prüfen": nur die OSM-Gastronomie wird gegen
   den gespeicherten Stand gehalten (eine Quelle, standardmäßig aus dem
   Cache), und der Punkt bleibt unverändert — Konkurrenzbeobachtung ohne
   Nebenwirkungen. Erst „neu prüfen" übernimmt den neuen Stand. */
async function waechterPruefen(z) {
  const inhalt = document.getElementById('vergleich-inhalt');
  const box = el('div', { class: 'verlauf-ergebnis' },
    el('div', { class: 'laden' }), `Wächter prüft „${z.label}" …`);
  inhalt.prepend(box);
  let d;
  try {
    const r = await fetch(`/api/points/${z.id}/waechter`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    d = await r.json();
  } catch (e) {
    box.replaceChildren(el('div', { class: 'fehlerbox' },
      `Wächter fehlgeschlagen: ${e.message}`));
    return;
  }
  if (!d.ok) {
    box.replaceChildren(el('div', { class: 'fehlerbox' },
      `Wächter: OSM nicht erreichbar (${d.fehler || '?'})`));
    return;
  }
  const teile = [el('strong', {}, `Wächter: ${d.label}`)];
  const delta = d.gastro_jetzt - d.gastro_gespeichert;
  teile.push(el('div', {},
    `Gastronomie im Umkreis: ${NF.format(d.gastro_gespeichert)} gespeichert → `
    + `${NF.format(d.gastro_jetzt)} jetzt`
    + (delta ? ` (${delta > 0 ? '+' : ''}${NF.format(delta)})` : ' (unverändert)')
    + (d.aus_cache ? ' · OSM-Stand aus dem Cache' : ' · frisch abgefragt')));
  const liste = (titel, eintraege) => (eintraege.length
    ? el('div', {},
      el('h3', { class: 'hinweis-klein' }, `${titel} (${eintraege.length})`),
      el('ul', { class: 'liste' }, eintraege.slice(0, 12).map((g) => el('li', {},
        el('span', { class: 'dist' },
          g.distanz_m === null || g.distanz_m === undefined
            ? '' : `${NF.format(g.distanz_m)} m`),
        el('span', { class: 'haupt' },
          el('div', { class: 'name' }, g.name || '(ohne Name)'),
          g.typ ? el('div', { class: 'meta' }, g.typ) : null)))))
    : null);
  teile.push(liste('Seit dem Speichern dazugekommen', d.neue_betriebe));
  teile.push(liste('Seit dem Speichern verschwunden', d.verschwundene_betriebe));
  if (!d.neue_betriebe.length && !d.verschwundene_betriebe.length) {
    teile.push(el('div', { class: 'notiz' },
      'Keine Veränderung im OSM-Gastro-Bestand seit dem gespeicherten Stand.'));
  }
  teile.push(el('div', { class: 'hinweis-klein' }, d.hinweis || ''));
  teile.push(el('button', {
    class: 'kein-druck',
    onclick: (ev) => ev.target.closest('.verlauf-ergebnis').remove(),
  }, 'ausblenden'));
  box.replaceChildren(...teile.filter(Boolean));
}

/* --------------------------------------------- Neu prüfen (Verlauf) */

/* Standortsuche dauert Monate. „Neu prüfen" fragt dieselben Quellen erneut ab
   (am Cache vorbei), legt den bisherigen Stand in den Verlauf und benennt die
   konkrete Veränderung: eröffnete Betriebe, verschwundene Betriebe, geänderte
   Kennzahlen. Ein verschwundener Betrieb ist ein doppeltes Signal — mögliches
   freies Ladenlokal UND ein Wettbewerber weniger. */
async function neuPruefen(z) {
  const sicher = confirm(
    `„${z.label}" jetzt neu prüfen?\n\n`
    + 'Das fragt alle Quellen erneut ab (am Cache vorbei), darunter eine '
    + 'Overpass-Abfrage. Der bisherige Stand wandert in den Verlauf des Punktes.');
  if (!sicher) return;
  const inhalt = document.getElementById('vergleich-inhalt');
  const wartebox = el('div', { class: 'verlauf-ergebnis' },
    el('div', { class: 'laden' }),
    `„${z.label}" wird neu geprüft — alle Quellen werden erneut abgefragt …`);
  inhalt.prepend(wartebox);
  let d;
  try {
    const r = await fetch(`/api/points/${z.id}/pruefung`, { method: 'POST' });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    d = await r.json();
  } catch (e) {
    wartebox.replaceChildren(el('div', { class: 'fehlerbox' },
      `Neu prüfen fehlgeschlagen: ${e.message}`));
    return;
  }
  await zeigeVergleich();

  const teile = [el('strong', {}, `Neu geprüft: ${d.label}`)];
  const nichts = !d.veraendert.length && !d.neue_betriebe.length
    && !d.verschwundene_betriebe.length;
  if (nichts) {
    teile.push(el('div', {},
      'Keine Veränderung bei den beweglichen Kennzahlen (OSM, GTFS, Zählstellen).'));
  }
  if (d.veraendert.length) {
    const tab = el('table', { class: 'daten' },
      el('tr', {}, el('th', {}, 'Kennzahl'), el('th', { class: 'num' }, 'vorher'),
        el('th', { class: 'num' }, 'jetzt')));
    for (const v of d.veraendert) {
      tab.append(el('tr', {},
        el('td', {}, v.titel),
        el('td', { class: 'num' }, v.alt === null || v.alt === undefined ? '—' : NF1.format(v.alt)),
        el('td', { class: 'num' }, v.neu === null || v.neu === undefined ? '—' : NF1.format(v.neu))));
    }
    teile.push(tab);
  }
  const betriebsliste = (titel, liste) => {
    if (!liste.length) return null;
    return el('div', {},
      el('h3', { class: 'hinweis-klein' }, titel),
      el('ul', { class: 'liste' }, liste.map((g) => el('li', {},
        el('span', { class: 'dist' },
          g.distanz_m === null || g.distanz_m === undefined ? '' : `${NF.format(g.distanz_m)} m`),
        el('span', { class: 'haupt' },
          el('div', { class: 'name' }, g.name || '(ohne Name)'),
          g.typ ? el('div', { class: 'meta' }, g.typ) : null)))));
  };
  teile.push(betriebsliste(`Neue Betriebe (${d.neue_betriebe.length})`, d.neue_betriebe));
  teile.push(betriebsliste(
    `Verschwundene Betriebe (${d.verschwundene_betriebe.length})`, d.verschwundene_betriebe));
  for (const h of d.hinweise || []) teile.push(el('div', { class: 'hinweis-klein' }, h));
  teile.push(el('button', { class: 'kein-druck', onclick: (ev) => ev.target.closest('.verlauf-ergebnis').remove() },
    'ausblenden'));

  document.getElementById('vergleich-inhalt')
    .prepend(el('div', { class: 'verlauf-ergebnis' }, teile.filter(Boolean)));
}

/* ------------------------------- Gewichtetes Ranking (eigene Gewichte) */

/* Das Werkzeug bewertet weiterhin nicht — die Punktzahl folgt allein aus den
   Gewichten des Nutzers, und jeder Beitrag steht offen in der Tabelle. Ohne
   diese Offenheit wäre es eine Scheinnote. */
const GEWICHTE_SPEICHER = 'gastroviewer.gewichte';
const RANKING_METRIKEN = [
  { key: 'einwohner', titel: 'Einwohner im Umkreis', richtung: 1 },
  { key: 'wettbewerb_je_1000', titel: 'Wettbewerber je 1.000 Einw.', richtung: -1 },
  { key: 'frequenzbringer', titel: 'Frequenzbringer', richtung: 1 },
  { key: 'abfahrten', titel: 'ÖPNV-Abfahrten je Tag', richtung: 1 },
  { key: 'miete_qm', titel: 'Nettokaltmiete €/m²', richtung: -1 },
  { key: 'erschliessung_einwohner', titel: 'Erschließungsgrad zu Fuß', richtung: 1 },
];
let rankingOffen = false;

function ladeGewichte() {
  let gemerkt = null;
  try {
    gemerkt = JSON.parse(localStorage.getItem(GEWICHTE_SPEICHER) || 'null');
  } catch { gemerkt = null; }
  const gewichte = {};
  for (const m of RANKING_METRIKEN) {
    const v = gemerkt && typeof gemerkt[m.key] === 'number' ? gemerkt[m.key] : 1;
    gewichte[m.key] = Math.min(3, Math.max(0, v));
  }
  return gewichte;
}

function rechneRanking(zeilen, gewichte) {
  /* Min-Max-Skalierung je Kennzahl über die gemerkten Punkte. Kennzahlen, die
     weniger als zweimal vorliegen oder überall gleich sind, tragen nichts bei
     — eine Skala aus einem einzigen Wert wäre erfunden. */
  const spannen = {};
  for (const m of RANKING_METRIKEN) {
    const werte = zeilen.map((z) => z[m.key]).filter((v) => typeof v === 'number');
    if (werte.length >= 2) {
      const min = Math.min(...werte);
      const max = Math.max(...werte);
      if (max > min) spannen[m.key] = { min, max };
    }
  }
  const ergebnisse = zeilen.map((z) => {
    const beitraege = [];
    let summe = 0;
    let gewichtsumme = 0;
    for (const m of RANKING_METRIKEN) {
      const sp = spannen[m.key];
      const g = gewichte[m.key];
      if (!sp || !g || typeof z[m.key] !== 'number') continue;
      let norm = ((z[m.key] - sp.min) / (sp.max - sp.min)) * 100;
      if (m.richtung < 0) norm = 100 - norm;
      beitraege.push({ metrik: m, norm });
      summe += norm * g;
      gewichtsumme += g;
    }
    return { zeile: z, punkte: gewichtsumme ? summe / gewichtsumme : null, beitraege };
  });
  ergebnisse.sort((a, b) => (b.punkte ?? -1) - (a.punkte ?? -1));
  return { ergebnisse, spannen };
}

function gewichtText(g) {
  return `×${String(g).replace('.', ',')}`;
}

function zeichneRanking(zeilen, gewichte, ziel) {
  const { ergebnisse } = rechneRanking(zeilen, gewichte);
  const aktive = RANKING_METRIKEN.filter((m) => gewichte[m.key] > 0);
  const tab = el('table', { class: 'vergleich-tabelle ranking-tabelle' },
    el('tr', {},
      el('th', {}, 'Rang'), el('th', {}, 'Bezeichnung'), el('th', {}, 'Punktzahl'),
      aktive.map((m) => el('th', {}, `${m.titel} (${gewichtText(gewichte[m.key])})`))));
  ergebnisse.forEach((e, i) => {
    const je = new Map(e.beitraege.map((b) => [b.metrik.key, b.norm]));
    tab.append(el('tr', {},
      el('td', {}, e.punkte === null ? '—' : String(i + 1)),
      el('td', { class: 'text' }, e.zeile.label),
      el('td', { class: 'num' },
        e.punkte === null ? '—' : NF1.format(e.punkte)),
      aktive.map((m) => el('td', { class: 'num' },
        je.has(m.key) ? NF.format(Math.round(je.get(m.key))) : '—'))));
  });
  ziel.replaceChildren(
    el('div', { class: 'tabelle-rahmen' }, tab),
    el('div', { class: 'hinweis-klein' },
      'Zellwerte: die auf 0–100 skalierte Kennzahl vor der Gewichtung. „—" heißt: '
      + 'liegt nicht vor oder ist bei allen Punkten gleich — geht nicht in die '
      + 'Punktzahl ein.'));
}

function rankingBereich(d) {
  if (!d.zeilen || d.zeilen.length < 2) return null;
  const gewichte = ladeGewichte();
  const ausgabe = el('div', { id: 'ranking-ausgabe' });

  const regler = el('div', { class: 'ranking-gewichte' });
  for (const m of RANKING_METRIKEN) {
    const anzeige = el('span', { class: 'ranking-wert' }, gewichtText(gewichte[m.key]));
    regler.append(el('label', {},
      el('span', { class: 'ranking-titel' }, m.titel, ' ',
        el('em', {}, m.richtung > 0 ? '(mehr = besser)' : '(weniger = besser)'), ' ', anzeige),
      el('input', {
        type: 'range', min: '0', max: '3', step: '0.5',
        value: String(gewichte[m.key]),
        'aria-label': `Gewicht für ${m.titel}`,
        oninput: (ev) => {
          gewichte[m.key] = Number(ev.target.value);
          anzeige.textContent = gewichtText(gewichte[m.key]);
          localStorage.setItem(GEWICHTE_SPEICHER, JSON.stringify(gewichte));
          zeichneRanking(d.zeilen, gewichte, ausgabe);
        },
      })));
  }

  const bereich = el('details', {
    class: 'ranking',
    ontoggle: (ev) => { rankingOffen = ev.target.open; },
  },
  el('summary', {}, 'Gewichtetes Ranking (eigene Gewichte)'),
  el('div', { class: 'notiz' },
    'Die Punktzahl folgt allein aus deinen Gewichten — sie ist keine Empfehlung '
    + 'des Werkzeugs. Jede Kennzahl wird über die gemerkten Punkte auf 0–100 '
    + 'skaliert (bester Wert 100, schlechtester 0) und nach Gewicht gemittelt. '
    + 'Ob „weniger Wettbewerb" für dich besser ist, entscheidet die Kennzahl '
    + 'nicht: Innenstadtlagen haben hohe Dichte UND hohen Zulauf.'),
  regler, ausgabe);
  if (rankingOffen) bereich.open = true;
  zeichneRanking(d.zeilen, gewichte, ausgabe);
  return bereich;
}

export { merken, pflegeleiste, zeigeVergleich };
