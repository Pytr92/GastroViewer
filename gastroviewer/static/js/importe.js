/* Knopf-Import: Einmal-Downloads aus der Oberfläche heraus (Bevölkerungsraster
   Österreich, Fahrplan Wien). Nichts lädt ungefragt — der Knopf nennt Quelle
   und Größe, erst der Klick startet den Lauf; der Fortschritt kommt alle zwei
   Sekunden von /api/import/status, am Ende lädt der Punkt neu. */
import { state } from './state.js';
import { el } from './dom.js';
import { hole as holeApi } from './api.js';

const NF = new Intl.NumberFormat('de-DE');

async function zustand() {
  return holeApi('/api/import/status', {});
}

async function starten(art) {
  const r = await fetch(`/api/import/${art}`, { method: 'POST' });
  if (!r.ok) {
    let text = `HTTP ${r.status}`;
    try { text = (await r.json()).detail || text; } catch (e) { /* Text reicht */ }
    throw new Error(text);
  }
  return r.json();
}

/* Liefert das Bedienfeld für einen Import — oder null, wenn der Punkt nicht
   in Österreich liegt (die Adresse mit Landeskennung wird abgewartet). */
export async function importFeld(art, lauf) {
  const a = (await (state.adresseLauf || Promise.resolve(null)))?.data;
  if (lauf !== undefined && lauf !== state.ladeLauf) return null;
  if (!a?.land_code || a.land_code === 'DE') return null;
  let z;
  try { z = (await zustand())[art]; } catch (e) { return null; }
  if (!z) return null;
  const feld = el('div', { class: 'import-feld' });
  zeichne(feld, art, z);
  return feld;
}

function zeichne(feld, art, z) {
  feld.replaceChildren();
  const lauf = z.lauf;
  if (lauf && lauf.status === 'laeuft') {
    feld.append(
      el('div', { class: 'notiz' },
        el('strong', {}, `${z.titel}: Import läuft. `),
        `${lauf.schritt}${lauf.fortschritt !== null && lauf.fortschritt !== undefined
          ? ` (${NF.format(Math.round(lauf.fortschritt))} %)` : ''}`),
      el('progress', { max: '100', ...(lauf.fortschritt !== null && lauf.fortschritt !== undefined
        ? { value: String(lauf.fortschritt) } : {}) }));
    setTimeout(async () => {
      try { zeichne(feld, art, (await zustand())[art]); } catch (e) { /* nächster Tick */ }
    }, 2000);
    return;
  }
  if (lauf && lauf.status === 'fertig') {
    feld.append(el('div', { class: 'notiz' },
      el('strong', {}, `${z.titel}: fertig. `), 'Der Punkt wird neu geladen …'));
    if (typeof window.setzePunkt === 'function') window.setzePunkt(state.lat, state.lon, false);
    return;
  }
  if (lauf && lauf.status === 'fehler') {
    feld.append(el('div', { class: 'warnung' },
      el('strong', {}, `${z.titel}: Import fehlgeschlagen. `), lauf.fehler || ''));
  }
  const knopf = el('button', { class: 'knopf', type: 'button' },
    `${z.importiert ? 'Erneut laden' : 'Jetzt laden'} (${NF.format(z.groesse_mb)} MB, einmalig)`);
  knopf.addEventListener('click', async () => {
    knopf.disabled = true;
    try {
      await starten(art);
      zeichne(feld, art, (await zustand())[art]);
    } catch (e) {
      feld.append(el('div', { class: 'warnung' }, `Start fehlgeschlagen: ${e.message}`));
      knopf.disabled = false;
    }
  });
  feld.append(
    el('div', { class: 'notiz' },
      el('strong', {}, `${z.titel}. `), z.beschreibung, ' ',
      el('span', { class: 'hinweis-klein' }, `Quelle: ${z.quelle} · ${z.lizenz}`)),
    knopf);
}
