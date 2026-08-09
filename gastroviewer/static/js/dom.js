/* Bausteine der Oberfläche: Elemente, Blöcke, Status, Quellenfußzeile.
 *
 * Zweitunterste Schicht — hängt nur an den Zahlenformaten. Jeder Block
 * benutzt `el`, `setStatus`, `setInhalt`, `setQuelle`; zusammen sind das
 * über achthundert Aufrufe.
 *
 * Eine Besonderheit: `setInhalt` stößt die Neuberechnung des Gesamt-Scores
 * an. Der Score wiederum rendert über `setStatus`/`setInhalt` — das wäre
 * ein Ringschluss zwischen zwei Modulen. Statt ihn zu importieren, nimmt
 * dieses Modul einen Rückruf entgegen, den der Einstiegspunkt einhängt.
 * Die Abhängigkeit zeigt damit nur noch in eine Richtung.
 */

import { NF, NF1, NF2, zahl } from './format.js';

export const el = (tag, attrs = {}, ...kinder) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') n.className = v;
    else if (k === 'html') n.innerHTML = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const kind of kinder.flat()) {
    if (kind === null || kind === undefined || kind === false) continue;
    n.append(kind.nodeType ? kind : document.createTextNode(String(kind)));
  }
  return n;
};

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** Aggregate kommen als {wert, zellen, zellen_gesamt, median, min, max}. */
export function kennzahl(titel, agg, einheit = '', nk = 0) {
  const box = el('div', { class: 'kennzahl' });
  box.append(el('div', { class: 'titel' }, titel));
  const v = agg && typeof agg === 'object' ? agg.wert : agg;
  const txt = zahl(v, nk);
  if (txt === null) {
    box.append(el('div', { class: 'wert fehlt' }, 'keine Angabe'));
    if (agg && agg.zellen_gesamt) {
      box.append(el('div', { class: 'basis' }, `kein Wert in ${agg.zellen_gesamt} Zellen`));
    }
    return box;
  }
  box.append(el('div', { class: 'wert' }, einheit ? `${txt} ${einheit}` : txt));
  if (agg && typeof agg === 'object' && agg.zellen !== undefined) {
    const teile = [`${agg.zellen} von ${agg.zellen_gesamt} Zellen`];
    if (agg.median !== undefined) teile.push(`Median ${zahl(agg.median, nk)}`);
    if (agg.min !== undefined) teile.push(`${zahl(agg.min, nk)}–${zahl(agg.max, nk)}`);
    box.append(el('div', { class: 'basis' }, teile.join(' · ')));
  }
  return box;
}

export function quellenzeile(prov) {
  if (!prov) return null;
  const teile = [];
  teile.push(el('b', {}, 'Quelle: '), prov.source);
  if (prov.stand) teile.push(' · ', el('b', {}, 'Stand: '), prov.stand);
  if (prov.retrieved_at) teile.push(` · abgerufen ${prov.retrieved_at.replace('T', ' ').replace('Z', ' UTC')}`);
  teile.push(el('br', {}), el('b', {}, 'Lizenz: '), prov.license);
  if (prov.endpoint) teile.push(el('br', {}), el('span', {}, prov.endpoint));
  if (prov.note) teile.push(el('br', {}), el('span', {}, prov.note));
  return el('div', { class: 'quelle' }, teile);
}

/** Ein Panel-Block mit Statusanzeige, Inhalt und Quellenfußzeile. */
export function block(id, titel) {
  const kopf = el('h2', {}, titel, el('span', { class: 'status laedt', id: `status-${id}` }, 'lädt …'));
  const inhalt = el('div', { class: 'block-inhalt', id: `inhalt-${id}` },
    el('div', { class: 'laden' }));
  return el('section', { class: 'block', id: `block-${id}` }, kopf, inhalt);
}

export function setStatus(id, klasse, text) {
  const s = document.getElementById(`status-${id}`);
  if (s) { s.className = `status ${klasse}`; s.textContent = text; }
}

/* Rückruf statt Import — siehe Modulkopf. Vorbelegt mit einer leeren
   Funktion, damit die Oberfläche auch dann rendert, wenn niemand ihn
   einhängt (etwa in einer künftigen Testseite ohne Score). */
let nachBlockRender = () => {};

export function beiBlockRender(fn) {
  nachBlockRender = typeof fn === 'function' ? fn : () => {};
}

export function setInhalt(id, ...kinder) {
  const c = document.getElementById(`inhalt-${id}`);
  if (!c) return;
  c.replaceChildren(...kinder.flat().filter(Boolean));
  // Der Gesamt-Score speist sich aus den Blockdaten — sobald irgendein Block
  // neu rendert, rechnet er (entprellt) nach. Der Score selbst ist
  // ausgenommen, sonst riefe er sich endlos selbst auf.
  if (id !== 'score') nachBlockRender();
}

export function setQuelle(id, prov) {
  const b = document.getElementById(`block-${id}`);
  if (!b) return;
  b.querySelector('.quelle')?.remove();
  const z = quellenzeile(prov);
  if (z) b.append(z);
}

/** Fehleranzeige mit konkreter Ursache — Spec §5. */
export function fehlerbox(err) {
  const kinder = [el('strong', {}, 'Nicht erreichbar. '), err?.message || 'Unbekannter Fehler.'];
  if (err?.detail) kinder.push(el('br', {}), el('code', {}, String(err.detail).slice(0, 400)));
  return el('div', { class: 'fehlerbox' }, kinder);
}

/* Die Quellenmodule setzen Betonung in Markdown-Manier (**so**). Ohne
   Umsetzung standen die Sternchen sichtbar im Text. */
export function mitBetonung(text) {
  return String(text ?? '').split('**')
    .map((s, i) => (i % 2 ? el('strong', {}, s) : s));
}

export function warnungen(liste) {
  return (liste || []).map((w) => el('div', { class: 'warnung' },
    ...mitBetonung(w)));
}

/* Hinweiszeile mit Betonung — die Kurzform für die vielen
   `hinweise`-Listen der Quellenmodule. */
export function hinweisZeile(text, klasse = 'hinweis-klein') {
  return el('div', { class: klasse }, ...mitBetonung(text));
}
