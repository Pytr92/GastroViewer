/* Zahlenformate — die unterste Schicht, ohne jede Abhängigkeit.
 *
 * Getrennt gehalten, weil praktisch jedes andere Modul sie braucht: NF
 * kommt gut zweihundertmal vor. Ein Modul ganz ohne Importe kann in keinen
 * Zyklus geraten, und genau das ist hier der Zweck.
 */

export const NF = new Intl.NumberFormat('de-DE');
export const NF1 = new Intl.NumberFormat('de-DE', { maximumFractionDigits: 1 });
export const NF2 = new Intl.NumberFormat('de-DE',
  { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/* Ab dieser Zahl Overpass-Abrufe in 24 Stunden weist die Fußzeile darauf hin.
   Gewählte Schwelle, kein gemessener Wert — sie steht in der Meldung mit drin.
   Ein normaler Arbeitsgang mit einer Handvoll Kandidaten bleibt darunter. */
export const OVERPASS_WARNSCHWELLE = 40;

/* Feste Nachkommastellen, wenn eine Vergleichsspalte sie vorgibt. Ohne die
   feste Untergrenze würde 0,50 als „0,5" erscheinen und 0,07 als „0,1". */
const NF_FEST = new Map();

export function nfFest(n) {
  if (!NF_FEST.has(n)) {
    NF_FEST.set(n, new Intl.NumberFormat('de-DE',
      { minimumFractionDigits: n, maximumFractionDigits: n }));
  }
  return NF_FEST.get(n);
}

/** Formatiert eine Zahl. null/undefined ergibt bewusst „keine Angabe", nicht 0. */
export function zahl(v, nk = 0) {
  if (v === null || v === undefined || Number.isNaN(v)) return null;
  return (nk === 0 ? NF : nk === 1 ? NF1 : NF2).format(v);
}
