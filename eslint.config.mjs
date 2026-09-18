// ESLint-Flat-Config: nur „no-undef" und ein paar Stolperfallen — kein
// Stilwächter. Aufruf: npx eslint@9 gastroviewer/static/js gastroviewer/static/app.js
// Die klassischen Skripte (score.js, bericht.js, duell.js) laufen mit denselben
// Globalen; die Modul-Brücke score-bruecke.js spricht die Funktionen aus
// score.js als globale Namen an.
const browser = {
  window: 'readonly', document: 'readonly', fetch: 'readonly', URL: 'readonly',
  URLSearchParams: 'readonly', localStorage: 'readonly', sessionStorage: 'readonly',
  navigator: 'readonly', location: 'readonly', history: 'readonly', console: 'readonly',
  alert: 'readonly', prompt: 'readonly', confirm: 'readonly',
  setTimeout: 'readonly', clearTimeout: 'readonly', setInterval: 'readonly',
  clearInterval: 'readonly', requestAnimationFrame: 'readonly', Blob: 'readonly',
  FileReader: 'readonly', AbortController: 'readonly', Event: 'readonly',
  CustomEvent: 'readonly', Intl: 'readonly', HTMLElement: 'readonly', Node: 'readonly',
  Image: 'readonly', DOMParser: 'readonly', performance: 'readonly',
  L: 'readonly', // Leaflet, klassisches Skript
};
// score.js (klassisches Skript) stellt diese Namen global bereit.
const score = {
  berechneScore: 'readonly', ladeScoreGewichte: 'readonly',
  speichereScoreGewichte: 'readonly', SCORE_KENNZAHLEN: 'readonly',
};

export default [
  {
    files: ['gastroviewer/static/js/**/*.js', 'gastroviewer/static/app.js'],
    languageOptions: {
      ecmaVersion: 2022, sourceType: 'module',
      globals: { ...browser, ...score },
    },
    rules: {
      'no-undef': 'error', 'no-unused-vars': ['warn', { args: 'none' }],
      'no-redeclare': 'error', 'no-dupe-keys': 'error', 'no-unreachable': 'error',
    },
  },
  {
    files: ['gastroviewer/static/score.js', 'gastroviewer/static/bericht.js',
      'gastroviewer/static/duell.js'],
    languageOptions: { ecmaVersion: 2022, sourceType: 'script', globals: { ...browser, ...score } },
    rules: { 'no-undef': 'error', 'no-redeclare': 'off', 'no-dupe-keys': 'error' },
  },
];
