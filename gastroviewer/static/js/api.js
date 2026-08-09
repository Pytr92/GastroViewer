/* Der einzige Weg zum eigenen Backend.
 *
 * Eigenes Modul, weil ihn fast jeder Block braucht: Läge er beim
 * Ladeorchester, importierte jedes Blockmodul von dort zurück und der
 * Abhängigkeitsgraph wäre ein Ring statt eines Sterns.
 *
 * Fehler werden geworfen, nicht geschluckt — der aufrufende Block zeigt
 * die konkrete Ursache an (Spec §5), statt stumm zu verschwinden.
 */

export async function hole(pfad, params) {
  const url = new URL(pfad, window.location.origin);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  const r = await fetch(url);
  if (!r.ok) {
    let detail = `HTTP ${r.status}`;
    try { const j = await r.json(); detail = j.detail || j.fehler || detail; } catch { /* egal */ }
    throw new Error(detail);
  }
  return r.json();
}
