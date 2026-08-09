/* Der gemeinsame Zustand des Datenreiters.
 *
 * Bewusst **ein Objekt** statt einzelner Variablen: Modul-Importe sind
 * schreibgeschützt, ein `export let x` ließe sich von außen nicht neu
 * setzen. Felder eines exportierten Objekts dagegen schon — deshalb wandert
 * alles Veränderliche hier hinein statt in lose Variablen.
 */

export const state = {
  lat: null,
  lon: null,
  radius: 600,
  marker: null,
  kreis: null,
  daten: {},          // name -> Antwort des jeweiligen Quellen-Endpunkts
  ebenen: {},         // name -> L.LayerGroup
  choroMetrik: 'Einwohner',
  ladeLauf: 0,        // verhindert, dass eine alte Antwort eine neue überschreibt
  /* „Bekannte Grenzen dieser Daten" — kommt beim Start aus dem Backend,
     damit die Texte nur an einer Stelle stehen. Steht hier und nicht als
     eigene Variable, weil Modul-Importe schreibgeschützt sind: Ein
     `export let` liesse sich vom Startcode aus nicht neu setzen. */
  grenzen: [],
};
