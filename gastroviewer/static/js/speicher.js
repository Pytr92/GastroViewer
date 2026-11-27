/* Geschützter Zugriff auf localStorage.
 *
 * Im privaten Modus, bei gesperrten Website-Daten oder vollem Speicher
 * werfen getItem/setItem — schon der Zugriff auf window.localStorage kann
 * werfen. Die Oberfläche darf daran nicht scheitern: Lesen fällt auf den
 * Ersatzwert zurück, Schreiben meldet nur Erfolg oder Misserfolg.
 */

/** Gespeicherter Text, oder `ersatz`, wenn nichts da ist oder Lesen scheitert. */
export function lies(schluessel, ersatz = null) {
  try {
    const wert = window.localStorage.getItem(schluessel);
    return wert === null ? ersatz : wert;
  } catch {
    return ersatz;
  }
}

/** Speichert einen Text; true bei Erfolg, false bei Fehler (wirft nie). */
export function schreibe(schluessel, wert) {
  try {
    window.localStorage.setItem(schluessel, String(wert));
    return true;
  } catch {
    return false;
  }
}
