/* Standortprofil: die eigenen Mindestanforderungen gegen alle Kandidaten.
 *
 * Aus einem Anzeigewerkzeug wird hier ein Filterwerkzeug. Wer dreißig
 * Adressen im Jahr ansieht, fragt nicht „wie viele Einwohner hat der
 * Umkreis", sondern „welche dieser dreißig erfülle ich überhaupt".
 *
 * Gerechnet wird im Backend (gastroviewer/kriterien.py) — dort ist die
 * Prüfung testbar und steht später auch dem Bericht zur Verfügung. Dieses
 * Modul hält nur das Profil im Browser und stellt das Ergebnis dar. Das
 * Profil ist eine Einstellung des Nutzers und gehört deshalb in seinen
 * Browser, nicht in die Datenbank des Werkzeugs.
 */

import { NF, NF1 } from './format.js';
import { el, hinweisZeile } from './dom.js';

const SPEICHER = 'gastroviewer.standortprofil';

let auswahl = [];        // mögliche Kennzahlen, kommen vom Server
let profil = null;       // die eigenen Kriterien

export function ladeProfil() {
  if (profil) return profil;
  try {
    const roh = JSON.parse(localStorage.getItem(SPEICHER) || '[]');
    profil = Array.isArray(roh) ? roh : [];
  } catch { profil = []; }
  return profil;
}

function merkeProfil() {
  try { localStorage.setItem(SPEICHER, JSON.stringify(profil)); } catch { /* egal */ }
}

function titelVon(key) {
  return auswahl.find((k) => k.key === key)?.titel || key;
}

function zahlText(wert, key) {
  if (typeof wert !== 'number') return '—';
  const stellen = auswahl.find((k) => k.key === key)?.stellen || 0;
  return stellen ? NF1.format(wert) : NF.format(wert);
}

const STAND_TEXT = {
  erfuellt: ['erfüllt', 'kriterium-ja'],
  nicht_erfuellt: ['nicht erfüllt', 'kriterium-nein'],
  nicht_pruefbar: ['nicht prüfbar', 'kriterium-offen'],
};

/* Ein Kriterium zum Bearbeiten. */
function kriteriumZeile(k, index, neuzeichnen) {
  const kennzahl = el('select', {
    'aria-label': 'Kennzahl',
    onchange: (ev) => { k.key = ev.target.value; merkeProfil(); neuzeichnen(); },
  });
  for (const m of auswahl) {
    kennzahl.append(el('option', {
      value: m.key, selected: m.key === k.key,
    }, m.einheit ? `${m.titel} (${m.einheit})` : m.titel));
  }
  const richtung = el('select', {
    'aria-label': 'Richtung',
    onchange: (ev) => { k.richtung = ev.target.value; merkeProfil(); neuzeichnen(); },
  });
  for (const [wert, text] of [['min', 'mindestens'], ['max', 'höchstens']]) {
    richtung.append(el('option', { value: wert, selected: k.richtung === wert }, text));
  }
  return el('div', { class: 'kriterium-zeile' },
    kennzahl,
    richtung,
    el('input', {
      type: 'number', step: 'any', value: String(k.wert ?? ''),
      'aria-label': 'Schwellenwert',
      onchange: (ev) => {
        k.wert = ev.target.value === '' ? null : Number(ev.target.value);
        merkeProfil(); neuzeichnen();
      },
    }),
    el('label', { class: 'ko-schalter' },
      el('input', {
        type: 'checkbox', checked: !!k.ko,
        onchange: (ev) => { k.ko = ev.target.checked; merkeProfil(); neuzeichnen(); },
      }), ' K.-o.'),
    el('button', {
      class: 'mehr',
      onclick: () => { profil.splice(index, 1); merkeProfil(); neuzeichnen(); },
    }, 'entfernen'));
}

/* Das Ergebnis eines Standorts. */
function punktZeile(p) {
  const teile = [
    el('b', {}, p.label),
    ` — ${p.erfuellt} von ${p.gesamt} erfüllt`,
  ];
  if (p.nicht_erfuellt) teile.push(` · ${p.nicht_erfuellt} nicht erfüllt`);
  if (p.nicht_pruefbar) teile.push(` · ${p.nicht_pruefbar} offen`);

  const details = el('ul', { class: 'liste' });
  for (const e of p.ergebnisse) {
    const [text, klasse] = STAND_TEXT[e.stand];
    details.append(el('li', {},
      el('span', { class: klasse }, text), ' — ',
      titelVon(e.key), ' ',
      e.richtung === 'min' ? 'mindestens ' : 'höchstens ',
      zahlText(e.schwelle, e.key),
      e.stand === 'nicht_pruefbar' ? ' (kein Wert für diesen Standort)'
        : `, tatsächlich ${zahlText(e.wert, e.key)}`,
      e.ko ? el('b', {}, ' · K.-o.') : null));
  }
  return el('div', { class: `kriterium-punkt ${p.durchgefallen ? 'faellt-durch' : ''}`.trim() },
    el('div', {}, ...teile,
      p.durchgefallen ? el('b', { class: 'kriterium-nein' }, ' — fällt durch') : null),
    p.offene_ko_kriterien.length ? hinweisZeile(
      'Offene **K.-o.-Kriterien** (kein Wert vorhanden): '
      + p.offene_ko_kriterien.map(titelVon).join(', ')
      + '. Ein fehlender Wert lässt den Standort ausdrücklich nicht '
      + 'durchfallen — er bleibt eine offene Frage.') : null,
    el('details', {}, el('summary', {}, 'Einzelne Kriterien'), details));
}

/* Der ganze Abschnitt, wie er über der Vergleichstabelle steht. */
export async function kriterienBereich() {
  const box = el('div', { class: 'kriterien-bereich' });
  const inhalt = el('div', {});

  try {
    if (!auswahl.length) {
      const r = await fetch('/api/points/kriterien');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      auswahl = (await r.json()).kriterien || [];
    }
  } catch (e) {
    box.append(hinweisZeile(
      `Die Kennzahlenliste für das Standortprofil ist nicht erreichbar: ${e.message}`));
    return box;
  }

  ladeProfil();

  const neuzeichnen = async () => {
    const zeilen = profil.map((k, i) => kriteriumZeile(k, i, neuzeichnen));
    const hinzu = el('button', {
      class: 'mehr',
      onclick: () => {
        profil.push({ key: auswahl[0].key, richtung: 'min', wert: 0, ko: false });
        merkeProfil(); neuzeichnen();
      },
    }, '+ Kriterium');

    const brauchbar = profil.filter((k) => k.key && typeof k.wert === 'number');
    let ergebnis = null;
    if (brauchbar.length) {
      try {
        const r = await fetch('/api/points/kriterien', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ kriterien: brauchbar }),
        });
        if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`);
        ergebnis = await r.json();
      } catch (e) {
        ergebnis = { fehler: e.message };
      }
    }

    inhalt.replaceChildren(
      ...zeilen,
      hinzu,
      profil.length ? null : hinweisZeile(
        'Noch kein Profil hinterlegt. Ein Standortprofil ist die Liste der '
        + 'eigenen Mindestanforderungen — etwa **mindestens 25.000 Einwohner** '
        + 'im Umkreis oder **höchstens 20 Wettbewerber** in 300 m. Danach zeigt '
        + 'die Liste, welche Kandidaten sie erfüllen.'),
      ergebnis?.fehler
        ? hinweisZeile(`Prüfung nicht möglich: ${ergebnis.fehler}`)
        : null,
      ...(ergebnis?.punkte || []).map(punktZeile),
      // Immer sichtbar: was offene Daten grundsätzlich nicht beantworten.
      ergebnis?.punkte?.length ? el('div', { class: 'notiz' },
        el('b', {}, 'Was dieses Profil nicht prüfen kann — Ortstermin: '),
        (ergebnis.punkte[0].nicht_pruefbar_grundsaetzlich || []).join(' · ')) : null,
    );
  };

  box.append(el('details', { class: 'kriterien' },
    el('summary', {}, 'Standortprofil — erfüllt ein Kandidat meine Anforderungen?'),
    inhalt));
  await neuzeichnen();
  return box;
}
