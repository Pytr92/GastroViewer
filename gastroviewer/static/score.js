/* Gesamt-Score — gemeinsame Logik für Anwendung (app.js) und Bericht
 * (bericht.js).
 *
 * Grundsatz-Ehrlichkeit: Ein Score ist IMMER eine Setzung. Deshalb ist hier
 * nichts versteckt — jede Kennzahl nennt ihre Quelle, ihre Anker („ab wann
 * gibt es 0, ab wann 100 Punkte" — gewählte Werte, keine Messwerte) und ihr
 * Gewicht. Die Gewichte stellt der Nutzer selbst ein (Schieberegler, lokal
 * gespeichert); fehlende Kennzahlen fallen aus der Rechnung heraus und werden
 * ausgewiesen, statt still als 0 einzugehen.
 *
 * Punkteformel je Kennzahl: linear zwischen den Ankern [schlecht, gut],
 * darüber/darunter gekappt. Steht der „gut"-Anker niedriger als der
 * „schlecht"-Anker (Miete, Lärm, Baustellen), dreht dieselbe Formel die
 * Richtung automatisch um.
 */

'use strict';

const SCORE_SPEICHER = 'gastroviewer.score.gewichte';

/* Zensus-Kennzahlen kommen als Objekt {wert, zellen, …} — hier zählt der
   Wert; alles andere (auch Strings) fällt als „liegt nicht vor" heraus. */
function scoreZahl(v) {
  if (v && typeof v === 'object') v = v.wert;
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

/* Anker: [0 Punkte, 100 Punkte] — gewählte Werte, im Block sichtbar. */
const SCORE_METRIKEN = [
  {
    key: 'einwohner', label: 'Einwohner im Umkreis', quelle: 'Zensus 2022',
    einheit: '', anker: [0, 10000],
    begruendung: 'Grundnachfrage der Wohnbevölkerung; 10.000 im Radius entspricht dichter Innenstadtlage.',
    hole: (b) => scoreZahl(b?.zensus?.data?.bevoelkerung?.einwohner),
  },
  {
    key: 'einkommen', label: 'Verfügbares Einkommen je Ew. (Kreis)',
    quelle: 'Regionalatlas', einheit: '€', anker: [20000, 35000],
    begruendung: 'Kaufkraftrahmen; Spanne deckt die deutschen Kreiswerte ab.',
    hole: (b) => scoreZahl(b?.einkommen?.data?.kreis?.wert_eur),
  },
  {
    key: 'abfahrten', label: 'ÖPNV-Abfahrten am Referenztag', quelle: 'GTFS (DELFI)',
    einheit: '', anker: [0, 1500],
    begruendung: 'Erreichbarkeit ohne Auto; 1.500 Abfahrten/Tag ist ein starker Knoten.',
    hole: (b) => scoreZahl(b?.gtfs?.data?.abfahrten_gesamt),
  },
  {
    key: 'frequenzbringer', label: 'Frequenzbringer im Umkreis', quelle: 'OpenStreetMap',
    einheit: '', anker: [0, 50],
    begruendung: 'Supermärkte, Schulen, Ärzte … bringen Laufkundschaft unabhängig vom eigenen Angebot.',
    hole: (b) => scoreZahl(b?.osm?.data?.zusammenfassung?.frequenzbringer?.gesamt),
  },
  {
    key: 'saettigung', label: 'Einwohner je Gastrobetrieb', quelle: 'Zensus + OSM',
    einheit: '', anker: [150, 1500],
    begruendung: 'Marktsättigung: wenige Einwohner je Betrieb = viel Wettbewerb um dieselbe Kundschaft. Achtung: In Toplagen ist Ballung normal — Kennzahl im Zweifel niedriger gewichten.',
    hole: (b) => {
      const ew = scoreZahl(b?.zensus?.data?.bevoelkerung?.einwohner);
      const g = scoreZahl(b?.osm?.data?.zusammenfassung?.gastronomie?.gesamt);
      if (ew === null || g === null || g <= 0) return null;
      return Math.round(ew / g);
    },
  },
  {
    key: 'miete', label: 'Wohnungsmiete €/m² (Umfeld)', quelle: 'Zensus 2022',
    einheit: '€/m²', anker: [16, 8],
    begruendung: 'Wohnmiete als Anker fürs Kostenniveau der Lage (Gewerbemiete liegt darüber, bewegt sich aber mit).',
    hole: (b) => scoreZahl(b?.zensus?.data?.wohnen?.miete_qm),
  },
  {
    key: 'laerm', label: 'Straßenlärm LDEN', quelle: 'Umgebungslärmkartierung (Bayern)',
    einheit: 'dB(A)', anker: [75, 55],
    begruendung: 'Lärm drückt die Außengastronomie-Qualität. „Nicht kartiert" heißt: keine laute Hauptverkehrsstraße — volle Punkte.',
    hole: (b) => {
      const l = b?.laerm?.data;
      if (!l) return null;
      if (l.kartiert === false) {
        return { punkte: 100, text: 'nicht kartiert (keine laute Hauptverkehrsstraße)' };
      }
      return scoreZahl(l.lden?.wert_db);
    },
  },
  {
    key: 'baustellen', label: 'Laufende Baustellen mit Gehweg-Eingriff',
    quelle: 'Stadt München', einheit: '', anker: [4, 0],
    begruendung: 'Der kurzfristige Ernstfall für Laufkundschaft. Vier-Wochen-Vorschau — vor Vertragsunterschrift neu prüfen.',
    hole: (b) => {
      const d = b?.baustellen?.data;
      if (!d) return null;
      const n = (d.liste || []).filter(
        (e) => e.status === 'laufend' && e.gehweg_betroffen
      ).length;
      // Zählwerte oberhalb der Listenkappung sind hier egal: ab 4 ist ohnehin 0.
      return Math.min(4, n);
    },
  },
];

function ladeScoreGewichte() {
  try {
    const roh = JSON.parse(localStorage.getItem(SCORE_SPEICHER) || '{}');
    const g = {};
    for (const m of SCORE_METRIKEN) {
      const v = Number(roh[m.key]);
      g[m.key] = Number.isFinite(v) && v >= 0 && v <= 3 ? v : 1;
    }
    return g;
  } catch {
    return Object.fromEntries(SCORE_METRIKEN.map((m) => [m.key, 1]));
  }
}

function speichereScoreGewichte(g) {
  localStorage.setItem(SCORE_SPEICHER, JSON.stringify(g));
}

function scorePunkte(metrik, wert) {
  const [schlecht, gut] = metrik.anker;
  const roh = (wert - schlecht) / (gut - schlecht);
  return Math.round(Math.min(1, Math.max(0, roh)) * 100);
}

/* bloecke: die Blockdaten der Anwendung (state.daten) oder des gespeicherten
   Punktes (payload.bloecke) — beide tragen dieselbe Form je Block. */
function berechneScore(bloecke, gewichte) {
  const teile = [];
  const fehlend = [];
  let summe = 0;
  let gewichtSumme = 0;
  for (const m of SCORE_METRIKEN) {
    let wert = null;
    try { wert = m.hole(bloecke || {}); } catch { wert = null; }
    const gewicht = gewichte[m.key] ?? 1;
    if (wert === null || wert === undefined) {
      fehlend.push(m.label);
      continue;
    }
    let punkte;
    let text = null;
    if (typeof wert === 'object') {
      punkte = wert.punkte;
      text = wert.text;
      wert = null;
    } else {
      punkte = scorePunkte(m, wert);
    }
    teile.push({
      key: m.key, label: m.label, quelle: m.quelle, einheit: m.einheit,
      anker: m.anker, begruendung: m.begruendung,
      wert, text, punkte, gewicht,
    });
    if (gewicht > 0) {
      summe += punkte * gewicht;
      gewichtSumme += gewicht;
    }
  }
  return {
    gesamt: gewichtSumme > 0 ? Math.round(summe / gewichtSumme) : null,
    teile,
    fehlend,
    gewichtSumme,
  };
}
