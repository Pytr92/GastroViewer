/* Brücke zum Gesamt-Score.
 *
 * Die Rechnung selbst steht in score.js — einem klassischen Skript, das
 * auch die Berichtsseite lädt und das deshalb bewusst kein Modul ist.
 * Seine Funktionen sind damit globale Namen; dieses Modul ist die einzige
 * Stelle, die sie anspricht.
 *
 * Aufgabe hier: aus den Blockdaten den Score anstoßen (entprellt, weil
 * jeder neu gerenderte Block ihn auslöst) und das Ergebnis samt
 * Gewichtsreglern darstellen.
 */

import { NF, NF1 } from './format.js';
import { el, kennzahl, setStatus, setInhalt, liste } from './dom.js';
import { state } from './state.js';

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

  // Aufbau einmal, danach nur noch Werte setzen: Ein Neubau je input-Schritt
  // ersetzte den Regler unter dem Zeiger — der Drag brach nach dem ersten
  // Schritt ab, per Tastatur sprang der Fokus bei jedem Pfeil hinaus.
  const gesamtWert = el('div', { class: 'wert' });
  const gesamtBasis = el('div', { class: 'basis' });
  const kopf = el('div', { class: 'kennzahlen' },
    el('div', { class: 'kennzahl' },
      el('div', { class: 'titel' }, 'Gesamt-Score'), gesamtWert, gesamtBasis));

  const wertText = (t) => t.text
    || `${NF.format(Math.round(t.wert))}${t.einheit ? ' ' + t.einheit : ''}`;
  const zeilen = new Map();
  const zeilenEls = s.teile.map((t) => {
    const regler = el('input', {
      type: 'range', min: '0', max: '3', step: '0.5', 'data-key': t.key,
      value: String(t.gewicht), title: 'Gewicht dieser Kennzahl (0 = zählt nicht)',
    });
    const neben = el('span', { class: 'neben' });
    const balken = el('div', {
      style: 'width:0;height:100%;background:var(--akzent);opacity:.8;',
    });
    const gewichtText = el('span', {});
    zeilen.set(t.key, { neben, balken, gewichtText });
    regler.addEventListener('input', () => {
      const g = ladeScoreGewichte();
      g[t.key] = Number(regler.value);
      speichereScoreGewichte(g);
      aktualisiere(berechneScore(state.daten || {}, g));
    });
    const [schlecht, gut] = t.anker;
    return el('div', { class: 'score-zeile', title: t.begruendung || '' },
      el('div', { class: 'score-kopf' },
        el('span', { class: 'haupt' }, t.label), neben),
      el('div', { class: 'score-balken', style: 'height:8px;background:#e8ecef;border-radius:4px;overflow:hidden;' },
        balken),
      el('div', { class: 'score-fuss', style: 'display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:11px;color:#5b6570;' },
        el('span', {},
          `Anker (gewählt): ${NF.format(schlecht)} → 0 P. · ${NF.format(gut)} → 100 P.`),
        el('label', { style: 'display:flex;align-items:center;gap:4px;' },
          gewichtText, regler)));
  });

  function aktualisiere(s2) {
    if (s2.teile.length !== zeilen.size || s2.teile.some((t) => !zeilen.has(t.key))) {
      zeigeScore(); // andere Kennzahlmenge — dann wirklich neu bauen
      return;
    }
    setStatus('score', 'ok',
      s2.gesamt === null ? 'alle Gewichte 0' : `${s2.gesamt} / 100`);
    gesamtWert.textContent = s2.gesamt === null ? '—' : `${NF.format(s2.gesamt)} / 100`;
    gesamtBasis.textContent =
      `${s2.teile.length} Kennzahlen · Gewichtssumme ${NF1.format(s2.gewichtSumme)}`;
    for (const t of s2.teile) {
      const z = zeilen.get(t.key);
      z.neben.textContent = ` ${wertText(t)} → ${NF.format(t.punkte)} P. · ${t.quelle}`;
      z.balken.style.width = `${t.punkte}%`;
      z.gewichtText.textContent = `Gewicht ${NF1.format(t.gewicht)}`;
    }
  }
  aktualisiere(s);

  setInhalt('score',
    kopf,
    el('div', { class: 'score-liste', style: 'display:flex;flex-direction:column;gap:10px;margin-top:6px;' }, zeilenEls),
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
export { planeScoreUpdate, zeigeScore };
