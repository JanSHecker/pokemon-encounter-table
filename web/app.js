'use strict';

/*
 * Soul-Link Tracker - Frontend fuer die gekoppelte Encounter-Tabelle.
 *
 * Zwei Ansichten: die Run-Uebersicht (Landing Page) und das Run-Dashboard.
 * Es gibt keinen Login und keine Identitaet - wer editiert, ist egal, alle sehen
 * dasselbe.
 *
 * API-Basis ueberschreiben (lokale Entwicklung): ?api=http://127.0.0.1:8000
 */

const API_BASE =
  new URLSearchParams(window.location.search).get('api') ||
  window.localStorage.getItem('encounter-api-base') ||
  '/encounter-table/api';

// Die kleinen Spielsprites, nicht das Artwork: in einer Zelle von 42px ist die
// gerasterte Grafik lesbarer als eine herunterskalierte Illustration.
const SPRITE_BASE = 'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon';
const POLL_INTERVAL_MS = 10000;
const SORT_KEY = 'encounter-sort';
const MAX_TYPES = 2;

// Vertragswerte der API (GET /runs -> rules). Der Platzhalter ist Protokoll: wir
// schreiben ihn als Namen, die API leitet daraus 'failed' ab. Die Vorgaben hier
// gelten nur, bis die erste Antwort da ist - gepflegt wird das im Backend.
let LOST_LABEL = 'Encounter verloren';
let NO_CULPRIT = 'niemand';
let TEAM_SIZE = 6;

function applyRules(rules) {
  if (!rules) return;
  LOST_LABEL = rules.lost_label ?? LOST_LABEL;
  NO_CULPRIT = rules.no_culprit ?? NO_CULPRIT;
  TEAM_SIZE = rules.team_size ?? TEAM_SIZE;
}

// Reihenfolge wie im Pokedex, nicht alphabetisch. Die Farben stehen in der CSS
// (.t-fire und Co.), hier steht nur das deutsche Label - so gibt es keine zweite
// Farbliste, die auseinanderlaufen kann.
const TYPE_LABELS = {
  normal: 'NORMAL', fighting: 'KAMPF', flying: 'FLUG',
  poison: 'GIFT', ground: 'BODEN', rock: 'GESTEIN',
  bug: 'KÄFER', ghost: 'GEIST', steel: 'STAHL',
  fire: 'FEUER', water: 'WASSER', grass: 'PFLANZE',
  electric: 'ELEKTRO', psychic: 'PSYCHO', ice: 'EIS',
  dragon: 'DRACHE', dark: 'UNLICHT', fairy: 'FEE',
};

const TYPE_ORDER = Object.keys(TYPE_LABELS);

/** Heutige Typentabelle: angreifender Typ -> Abweichungen von 1x. */
const CHART = {
  normal: { rock: 0.5, ghost: 0, steel: 0.5 },
  fighting: { normal: 2, flying: 0.5, poison: 0.5, rock: 2, bug: 0.5, ghost: 0, steel: 2, psychic: 0.5, ice: 2, dark: 2, fairy: 0.5 },
  flying: { fighting: 2, rock: 0.5, bug: 2, steel: 0.5, grass: 2, electric: 0.5 },
  poison: { poison: 0.5, ground: 0.5, rock: 0.5, ghost: 0.5, steel: 0, grass: 2, fairy: 2 },
  ground: { flying: 0, poison: 2, rock: 2, bug: 0.5, steel: 2, fire: 2, grass: 0.5, electric: 2 },
  rock: { fighting: 0.5, flying: 2, ground: 0.5, bug: 2, steel: 0.5, fire: 2, ice: 2 },
  bug: { fighting: 0.5, flying: 0.5, poison: 0.5, ghost: 0.5, steel: 0.5, fire: 0.5, grass: 2, psychic: 2, dark: 2, fairy: 0.5 },
  ghost: { normal: 0, ghost: 2, psychic: 2, dark: 0.5 },
  steel: { rock: 2, steel: 0.5, fire: 0.5, water: 0.5, electric: 0.5, ice: 2, fairy: 2 },
  fire: { rock: 0.5, bug: 2, steel: 2, fire: 0.5, water: 0.5, grass: 2, ice: 2, dragon: 0.5 },
  water: { ground: 2, rock: 2, fire: 2, water: 0.5, grass: 0.5, dragon: 0.5 },
  grass: { flying: 0.5, poison: 0.5, ground: 2, rock: 2, bug: 0.5, steel: 0.5, fire: 0.5, water: 2, grass: 0.5, dragon: 0.5 },
  electric: { flying: 2, ground: 0, water: 2, grass: 0.5, electric: 0.5, dragon: 0.5 },
  psychic: { fighting: 2, poison: 2, steel: 0.5, psychic: 0.5, dark: 0 },
  ice: { flying: 2, ground: 2, steel: 0.5, fire: 0.5, water: 0.5, grass: 2, ice: 0.5, dragon: 2 },
  dragon: { steel: 0.5, dragon: 2, fairy: 0 },
  dark: { fighting: 0.5, ghost: 2, psychic: 2, dark: 0.5, fairy: 0.5 },
  fairy: { fighting: 2, poison: 0.5, steel: 0.5, fire: 0.5, dragon: 2, dark: 2 },
};

// Alle Faktoren sind Zweierpotenzen und damit exakt vergleichbar - gerundet wird nichts.
const BUCKETS = [4, 2, 0.5, 0.25, 0];
const BUCKET_CLASS = { 4: '4', 2: '2', 0.5: '05', 0.25: '025', 0: '0' };

const FILTERS = [
  ['alle', 'Alle'], ['team', 'Team'], ['box', 'Box'],
  ['tot', 'Tot'], ['verloren', 'Verloren'], ['offen', 'Offen'],
];

// Reihenfolge der Sortierung 'Nach Status': was gerade gespielt wird, zuerst.
const CATEGORY_RANK = { team: 0, box: 1, tot: 2, verloren: 3, offen: 4 };

const RUN_STATUS_LABELS = { active: 'AKTIV', paused: 'PAUSIERT', completed: 'FERTIG', failed: 'VERKACKT' };
const RUN_STATUS_ACTIONS = [
  ['active', 'aktiv'], ['paused', 'pause'], ['completed', 'geschafft'], ['failed', 'verkackt'],
];

// Die drei Zuschnitte der Statistik auf der Uebersicht. Alle drei rechnen aus
// derselben Liste (GET /stats -> runs), nur anders gebuendelt.
const STATS_SCOPES = [
  ['all', 'GESAMT', 'Alle Runs zusammen'],
  ['run', 'PRO RUN', 'Jeder Run für sich'],
  ['variant', 'PRO VARIANTE', 'Nach Edition zusammengefasst'],
];
const STATS_SCOPE_KEY = 'encounter-stats-scope';

const state = {
  view: 'home',
  games: [],
  catalogs: {},
  players: [],
  runs: [],
  currentRunId: null,
  run: null,
  updatedAt: null,
  stats: null,
  statsScope: 'all',
  filter: 'alle',
  sort: 'order',
  search: '',
  types: [],
  // Das Pokémon, das per Knopf aus der Tabelle in den Rechner geladen wurde -
  // oder null, wenn die Typen von Hand gewaehlt sind.
  typeMon: null,
  // Der Modus wird bewusst nicht gespeichert: nur im Angriff markiert die
  // Tabelle die anfaelligen Pokémon, und ein aus der letzten Sitzung
  // stehengebliebenes 'def' sieht aus, als wuerde die Markierung fehlen.
  mode: 'atk',
  picker: null,
  lostRowId: null,
  newRunGame: null,
};

const el = {
  brandButton: document.getElementById('brand-button'),
  brandSub: document.getElementById('brand-sub'),
  headStats: document.getElementById('head-stats'),
  playersButton: document.getElementById('players-button'),
  globalError: document.getElementById('global-error'),

  homeView: document.getElementById('home-view'),
  homeSub: document.getElementById('home-sub'),
  runGrid: document.getElementById('run-grid'),
  statsScope: document.getElementById('stats-scope'),
  statsGrid: document.getElementById('stats-grid'),
  rosterChips: document.getElementById('roster-chips'),

  runView: document.getElementById('run-view'),
  filterBar: document.getElementById('filter-bar'),
  locationSearch: document.getElementById('location-search'),
  sortBar: document.getElementById('sort-bar'),
  tableScroll: document.getElementById('table-scroll'),
  tableHead: document.getElementById('table-head'),
  tableRows: document.getElementById('table-rows'),

  capCard: document.getElementById('cap-card'),
  failList: document.getElementById('fail-list'),
  blameLine: document.getElementById('blame-line'),
  typeCard: document.getElementById('type-card'),
  typeMon: document.getElementById('type-mon'),
  typeModes: document.getElementById('type-modes'),
  typeGrid: document.getElementById('type-grid'),
  typeResultTitle: document.getElementById('type-result-title'),
  typeResultList: document.getElementById('type-result-list'),
  typeReset: document.getElementById('type-reset'),
  teamCheckTitle: document.getElementById('team-check-title'),
  teamCheckList: document.getElementById('team-check-list'),

  pickerDialog: document.getElementById('picker-dialog'),
  pickerDot: document.getElementById('picker-dot'),
  pickerTitle: document.getElementById('picker-title'),
  pickerSub: document.getElementById('picker-sub'),
  pickerSearch: document.getElementById('picker-search'),
  pickerList: document.getElementById('picker-list'),
  pickerClear: document.getElementById('picker-clear'),

  lostDialog: document.getElementById('lost-dialog'),
  lostSub: document.getElementById('lost-sub'),
  culpritList: document.getElementById('culprit-list'),

  confirmDialog: document.getElementById('confirm-dialog'),
  confirmTitle: document.getElementById('confirm-title'),
  confirmSub: document.getElementById('confirm-sub'),
  confirmOk: document.getElementById('confirm-ok'),

  playersDialog: document.getElementById('players-dialog'),
  playerList: document.getElementById('player-list'),
  playerForm: document.getElementById('player-form'),
  playerName: document.getElementById('player-name'),

  renameDialog: document.getElementById('rename-dialog'),
  renameForm: document.getElementById('rename-form'),
  renameInput: document.getElementById('rename-input'),
  renameSub: document.getElementById('rename-sub'),

  runDialog: document.getElementById('run-dialog'),
  runForm: document.getElementById('run-form'),
  runName: document.getElementById('run-name'),
  runGames: document.getElementById('run-games'),
  runRoster: document.getElementById('run-roster'),
};

// --------------------------------------------------------------- Helfer ---

/** Gerendert wird durchgehend mit innerHTML - jeder ausgegebene Wert geht hier durch. */
function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function formatDate(value) {
  if (!value) return '';
  return new Intl.DateTimeFormat('de-DE', { dateStyle: 'short' }).format(new Date(value));
}

/** Vergleichsform fuer jede Suche: klein, ohne Akzente, ohne Trennzeichen.
 *
 * Damit ist der Slug einer Art dieselbe Form wie ihr englischer Name - er *ist*
 * der englische Name in Kleinbuchstaben ('mr-mime'), nur mit Bindestrichen.
 * Gesucht wird deshalb ueber deutschen Namen und Slug zugleich: eingeben darf
 * man beides, angezeigt wird immer der deutsche Name.
 */
function fold(value) {
  return String(value ?? '')
    .toLocaleLowerCase('de')
    .replaceAll('ß', 'ss')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '')
    // 'ü', 'ue' und 'u' sind dieselbe Eingabe - wer keine Umlaut-Taste bemueht,
    // tippt 'Verwuesteter'. Beide Seiten laufen durch dieselbe Zusammenziehung
    // und treffen sich damit in der Mitte. Ein echtes 'ue' im Wort schadet nicht:
    // dem Eintrag widerfaehrt es genauso wie der Eingabe.
    .replace(/ae/g, 'a')
    .replace(/oe/g, 'o')
    .replace(/ue/g, 'u');
}

/** Editierdistanz des am besten passenden Teilstuecks von `text` zu `term`.
 *
 * Der Anfang kostet nichts (erste Zeile bleibt 0) und gewertet wird das Minimum
 * der letzten Zeile - gemessen wird also, wie weit der Suchbegriff *irgendwo* in
 * `text` danebenliegt, statt beide Woerter ganz zu vergleichen. 'geweiher' ist
 * so einen Buchstaben von 'gehweiher' entfernt, obwohl kein Teilstueck woertlich
 * passt.
 */
function nearDistance(term, text) {
  let previous = new Array(text.length + 1).fill(0);
  let current = new Array(text.length + 1);
  for (let i = 1; i <= term.length; i += 1) {
    current[0] = i;
    for (let j = 1; j <= text.length; j += 1) {
      current[j] = Math.min(
        previous[j] + 1,
        current[j - 1] + 1,
        previous[j - 1] + (term[i - 1] === text[j - 1] ? 0 : 1),
      );
    }
    [previous, current] = [current, previous];
  }
  return Math.min(...previous);
}

/** Wie weit ein Treffer danebenliegen darf.
 *
 * Kurze Begriffe muessen sitzen: bei vier Buchstaben ist sonst der halbe Pokedex
 * "aehnlich" und der erste Treffer, den Enter nimmt, waere Zufall.
 */
function searchTolerance(term) {
  return term.length < 5 ? 0 : Math.min(3, Math.floor(term.length / 4));
}

/** Treffer einer Liste: woertlich oder, im zweiten Durchgang, mit Tippfehlern.
 *
 * Jeder Eintrag bringt seine Suchschluessel als `search` mit (deutscher Name und
 * Slug, beide gefaltet). Die Toleranzsuche sortiert nach Abstand - Enter nimmt
 * den ersten Treffer, also muss der beste vorne stehen.
 */
/** Abstand des besten Treffers einer Gruppe - Infinity, wenn sie leer ist.
 *
 * Die Toleranzsuche hat bereits sortiert, es zaehlt also nur der erste Eintrag.
 */
function groupDistance(hits, term) {
  if (!hits.length) return Infinity;
  return Math.min(...hits[0].search.map((key) => nearDistance(term, key)));
}

function searchEntries(entries, term, fuzzy) {
  if (!term) return entries;
  if (!fuzzy) return entries.filter((entry) => entry.search.some((key) => key.includes(term)));

  const tolerance = searchTolerance(term);
  if (!tolerance) return [];
  return entries
    .map((entry) => ({ entry, distance: Math.min(...entry.search.map((key) => nearDistance(term, key))) }))
    .filter((hit) => hit.distance <= tolerance)
    .sort((a, b) => a.distance - b.distance)
    .map((hit) => hit.entry);
}

function spriteUrl(dex) {
  return `${SPRITE_BASE}/${Number(dex) || 0}.png`;
}

/** Typ-Badge, wie sie an Pokémon, im Ergebnis und an der Cap-Karte steht. */
function typeBadge(type) {
  if (!TYPE_LABELS[type]) return '';
  return `<span class="type-badge t-${esc(type)}"><span class="type-icon"></span>${esc(TYPE_LABELS[type])}</span>`;
}

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function api(path, options = {}) {
  const { method = 'GET', body } = options;
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    cache: 'no-store',
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (response.status === 204) return null;
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload && typeof payload.detail === 'string' ? payload.detail : `HTTP ${response.status}`;
    throw new ApiError(response.status, detail);
  }
  return payload;
}

/** Rueckfrage vor einer Aktion, die sich nicht zurueckholen laesst.
 *
 * Bewusst nicht `window.confirm`: den nativen Dialog darf der Browser
 * unterdruecken - Chrome bietet dafuer sogar eine Checkbox an ("weitere Dialoge
 * verhindern"), und wer sie einmal setzt, bekommt bis zum Neuladen still ein
 * `false` zurueck. Der Loeschknopf tat dann nichts, ohne jede Meldung. Ein
 * eigener Dialog kann nicht abgeschaltet werden und sieht aus wie der Rest.
 */
function ask({ title, text, confirmLabel = 'Löschen' }) {
  el.confirmTitle.textContent = title;
  el.confirmSub.textContent = text;
  el.confirmOk.textContent = confirmLabel;

  return new Promise((resolve) => {
    let answer = false;
    const accept = () => {
      answer = true;
      el.confirmDialog.close();
    };
    el.confirmOk.addEventListener('click', accept);
    // Erst beim Schliessen antworten - egal ob ueber Abbrechen, Escape oder den
    // Bestaetigen-Knopf. So gibt es genau einen Weg heraus.
    el.confirmDialog.addEventListener(
      'close',
      () => {
        el.confirmOk.removeEventListener('click', accept);
        resolve(answer);
      },
      { once: true },
    );
    el.confirmDialog.showModal();
  });
}

function showError(message) {
  el.globalError.textContent = message;
  el.globalError.hidden = false;
}

function clearError() {
  el.globalError.hidden = true;
  el.globalError.textContent = '';
}

// Schreibvorgaenge laufen nacheinander statt parallel: wer schnell mehrere
// Zeilen umschaltet, soll keine Klicks verlieren, und die Antworten kommen in
// derselben Reihenfolge zurueck, in der geklickt wurde.
let writeChain = Promise.resolve();
let pendingWrites = 0;

function write(action) {
  pendingWrites += 1;
  document.body.classList.add('saving');

  const running = writeChain.then(action);
  writeChain = running.catch(() => {});

  return running
    .then((result) => {
      clearError();
      return result;
    })
    .catch(async (error) => {
      if (error instanceof ApiError && error.status === 412) {
        showError('Die Tabelle wurde zwischenzeitlich geändert. Es wird neu geladen.');
        await reloadEverything();
      } else if (error instanceof ApiError && [409, 422].includes(error.status)) {
        // Regelverstoss, kein Fehler - die API erklaert sich selbst.
        showError(error.message);
      } else {
        showError(`Speichern fehlgeschlagen: ${error.message}`);
      }
      return null;
    })
    .finally(() => {
      pendingWrites -= 1;
      if (pendingWrites === 0) document.body.classList.remove('saving');
    });
}

// ---------------------------------------------------------------- Daten ---

function catalog() {
  return state.run ? state.catalogs[state.run.game_id] : null;
}

function catalogLocation(locationId) {
  return (locationId && catalog()?.index.locations.get(locationId)) || null;
}

function speciesInfo(species) {
  return (species && catalog()?.index.species.get(species)) || null;
}

function speciesTypes(species) {
  return speciesInfo(species)?.types || [];
}

/** Entwicklungslinie einer Art - die Einheit, in der die Dupes-Clause zaehlt.
 *
 * Ohne Katalogeintrag bleibt die Art ihre eigene Familie: lieber die alte
 * Artenpruefung als gar keine.
 */
function familyOf(species) {
  if (!species) return null;
  return speciesInfo(species)?.family ?? species;
}

async function ensureCatalog(gameId) {
  if (!gameId || state.catalogs[gameId]) return;
  const fetched = await api(`/games/${encodeURIComponent(gameId)}`);
  // Indizes einmal bauen statt pro Zelle: der Katalog aendert sich zur Laufzeit
  // nicht, die Tabelle schlaegt aber fuer jede Zelle darin nach.
  //
  // Die Ortslisten kommen zuerst und der Pokedex danach: er ist die
  // vollstaendigere Quelle (er allein kennt Familie und Typen) und soll gewinnen.
  fetched.index = {
    locations: new Map(fetched.locations.map((location) => [location.id, location])),
    species: new Map([
      ...fetched.locations.flatMap((location) => location.encounters.map((entry) => [entry.species, entry])),
      ...(fetched.pokedex || []).map((entry) => [entry.species, entry]),
    ]),
  };
  // Die Suchschluessel des Pokedex haengen nur am Katalog, nicht an der Zeile:
  // einmal je Spiel falten statt bei jedem Oeffnen des Auswahldialogs. Der
  // Pokedex-Eintrag ist zugleich sein eigener Nachschlag - er gewinnt oben im
  // Index ohnehin.
  fetched.index.choices = (fetched.pokedex || []).map((entry) => pickerEntry(entry, entry));
  state.catalogs[gameId] = fetched;
}

function rows() {
  return state.run?.encounters || [];
}

function findRow(rowId) {
  return rows().find((row) => row.id === rowId) || null;
}

function player(playerId) {
  return state.players.find((entry) => entry.id === playerId) || null;
}

/** Zustand einer Zeile fuer Filter, Sortierung und Faerbung.
 *
 * 'box' und 'team' sind derselbe Fang - nur einmal auf der Bank und einmal im
 * Spiel. Die API kennt dafuer kein eigenes Outcome, das steht in `in_team`.
 */
function category(row) {
  if (row.outcome === 'dead') return 'tot';
  if (row.outcome === 'failed') return 'verloren';
  if (row.outcome === 'caught') return row.in_team ? 'team' : 'box';
  return 'offen';
}

function categoryCounts() {
  const counts = { alle: rows().length, team: 0, box: 0, tot: 0, verloren: 0, offen: 0 };
  for (const row of rows()) counts[category(row)] += 1;
  return counts;
}

function visibleRows() {
  const term = fold(state.search);
  const list = rows().filter(
    (row) =>
      (state.filter === 'alle' || category(row) === state.filter) &&
      (!term || fold(row.encounter).includes(term)),
  );
  const rank = (row) => (state.sort === 'status' ? CATEGORY_RANK[category(row)] : 0);
  return list.sort((a, b) => rank(a) - rank(b) || a.order - b.order || a.id.localeCompare(b.id));
}

function isFilled(pick) {
  return Boolean(pick && (pick.species || String(pick.name || '').trim()));
}

/** Die Pokémon, die ein Spieler gerade im Team hat. */
function teamMons(playerId) {
  return rows()
    .filter((row) => row.in_team && category(row) !== 'tot')
    .map((row) => row.picks[playerId])
    .filter((pick) => isFilled(pick) && pick.status !== 'dead');
}

/** Spieler nach Schuld sortieren - die eine Rechnung fuer alle Balken.
 *
 * Schuld = Tod x2 + vergeigter Encounter: ein toter Link kostet die ganze Reihe,
 * ein verpasster nur die Gelegenheit. Run-Ansicht und Uebersicht teilen sich die
 * Formel, sonst stuenden zwei Zahlen fuer dasselbe Wort.
 */
function scorePlayers(deaths, misses) {
  const scored = state.players
    .map((entry) => {
      const dead = deaths[entry.id] || 0;
      const missed = misses[entry.id] || 0;
      return { player: entry, deaths: dead, misses: missed, score: dead * 2 + missed };
    })
    .sort((a, b) => b.score - a.score);
  return { scored, worst: scored[0], max: Math.max(1, ...scored.map((entry) => entry.score)) };
}

/** Negativstatistik des offenen Runs: eine Zeile = ein Vorfall beim Verursacher.
 *
 * Dieselbe Rechnung wie GET /stats, nur lokal: die Zahlen sollen sich mit der
 * Tabelle aendern und nicht erst beim naechsten Poll.
 */
function failStats() {
  const deaths = {};
  const misses = {};
  for (const entry of state.players) {
    deaths[entry.id] = 0;
    misses[entry.id] = 0;
  }
  for (const row of rows()) {
    const blame = row.responsible_player;
    if (!blame || deaths[blame] === undefined) continue;
    if (row.outcome === 'dead') deaths[blame] += 1;
    else if (row.outcome === 'failed') misses[blame] += 1;
  }
  return scorePlayers(deaths, misses);
}

/** Was jeder Spieler im Run schon belegt hat - Arten und Entwicklungslinien.
 *
 * Die Dupes-Clause gilt fuer die ganze Linie: wer ein Karpador eingetragen hat,
 * darf kein Garados mehr nehmen. Der Status spielt dabei keine Rolle - ein totes
 * Karpador gibt die Linie nicht wieder frei.
 *
 * Einmal pro Zeichenvorgang statt einmal pro Zelle - sonst waechst der Aufwand
 * quadratisch mit der Zeilenzahl.
 */
function pickCounts() {
  const counts = new Map();
  const bump = (map, key) => map.set(key, (map.get(key) || 0) + 1);

  for (const row of rows()) {
    for (const [playerId, pick] of Object.entries(row.picks || {})) {
      if (!pick.species) continue;
      let perPlayer = counts.get(playerId);
      if (!perPlayer) counts.set(playerId, (perPlayer = { species: new Map(), families: new Map() }));
      bump(perPlayer.species, pick.species);
      bump(perPlayer.families, familyOf(pick.species));
    }
  }
  return counts;
}

const NO_PICKS = { species: new Map(), families: new Map() };

/** Warum eine Art fuer diesen Spieler schon vergeben ist - oder null.
 *
 * Die eigene Zeile zaehlt nicht gegen sich selbst, sonst waere jeder Eintrag
 * sofort sein eigenes Duplikat.
 */
function dupeReason(counts, playerId, ownSpecies, species) {
  if (!species) return null;
  const mine = counts.get(playerId) || NO_PICKS;
  const own = ownSpecies === species ? 1 : 0;
  if ((mine.species.get(species) || 0) - own > 0) return 'Art schon gefangen';
  if ((mine.families.get(familyOf(species)) || 0) - own > 0) return 'Entwicklungslinie schon vergeben';
  return null;
}

// -------------------------------------------------------- Typenrechner ----

function factor(attack, defence) {
  return CHART[attack]?.[defence] ?? 1;
}

/** Schaden der gewaehlten Angriffstypen gegen eine Typenkombination.
 *
 * Bei zwei Angriffstypen zaehlt der bessere - man greift schliesslich mit einer
 * Attacke an und sucht sich die passende aus (Coverage).
 */
function attackAgainst(selection, defenders) {
  return Math.max(...selection.map((attack) => defenders.reduce((total, type) => total * factor(attack, type), 1)));
}

/** Multiplikator je Typ fuer das Ergebnisfeld. */
function bucketsFor(selection, mode) {
  const grouped = new Map();
  for (const type of TYPE_ORDER) {
    const value = mode === 'atk'
      ? Math.max(...selection.map((attack) => factor(attack, type)))
      // Abwehr mit zwei Typen ist das Produkt beider Verteidigungswerte - so
      // entstehen ueberhaupt erst x4 und x1/4.
      : selection.reduce((total, defence) => total * factor(type, defence), 1);
    if (value === 1) continue;
    if (!grouped.has(value)) grouped.set(value, []);
    grouped.get(value).push(type);
  }
  return grouped;
}

function formatFactor(value) {
  if (value === 0.25) return '×¼';
  if (value === 0.5) return '×½';
  return `×${value}`;
}

// -------------------------------------------------------------- Rendern ---

function render() {
  const isHome = state.view === 'home';
  el.homeView.hidden = !isHome;
  el.runView.hidden = isHome;
  renderBrand();
  renderHeadStats();
  if (isHome) renderHome();
  else renderRunView();
}

function renderBrand() {
  if (state.view === 'home') {
    el.brandSub.textContent = 'RUN-ÜBERSICHT';
    el.brandSub.classList.remove('is-link');
    return;
  }
  const game = state.run?.game_name || state.run?.game_id || '';
  el.brandSub.textContent = `← ALLE RUNS · ${(state.run?.run_name || '')} · ${game}`.toUpperCase();
  el.brandSub.classList.add('is-link');
}

function headStat(value, label, tone = '') {
  return `<div class="head-stat ${esc(tone)}"><b>${esc(value)}</b><span>${esc(label)}</span></div>`;
}

function renderHeadStats() {
  if (state.view === 'home') {
    el.headStats.innerHTML = headStat(state.runs.length, 'RUNS') + headStat(state.players.length, 'SPIELER');
    return;
  }
  const counts = categoryCounts();
  el.headStats.innerHTML =
    headStat(`${counts.team + counts.box}/${counts.alle}`, 'GEFANGEN') +
    headStat(`${counts.team}/${TEAM_SIZE}`, 'IM TEAM', 'good') +
    headStat(counts.tot, 'TOT', 'bad') +
    headStat(counts.verloren, 'VERGEIGT', 'warn');
}

/** Die Schuld-Balken, wie sie in der Run-Ansicht und auf der Uebersicht stehen.
 *
 * Ein Markup fuer beide: laeuft es auseinander, zeigen zwei Karten dieselbe
 * Rechnung unterschiedlich - genau das, was `scorePlayers()` schon fuer die
 * Zahlen verhindert.
 */
function failRows(scored, max) {
  return scored
    .map(
      (entry) => `
      <div class="fail-row">
        <span class="dot" style="background:${esc(entry.player.color)}"></span>
        <span class="name">${esc(entry.player.name)}</span>
        <div class="bar">
          <span class="dead" style="width:${esc(((entry.deaths * 2) / max) * 100)}%"></span>
          <span class="lost" style="width:${esc((entry.misses / max) * 100)}%"></span>
        </div>
        <span class="tally">${esc(entry.deaths)} ✝ · ${esc(entry.misses)} ✗</span>
      </div>`,
    )
    .join('');
}

// --------------------------------------------------------- Run-Uebersicht -

function playerChip(entry, className = 'chip') {
  return `<span class="${className}"><span class="dot" style="background:${esc(entry.color)}"></span>${esc(entry.name)}</span>`;
}

function runCard(run) {
  const total = run.encounter_count || 1;
  const percent = (value) => `${(value / total) * 100}%`;
  const caught = run.caught_count;
  const status = RUN_STATUS_LABELS[run.status] ? run.status : 'active';

  const actions = RUN_STATUS_ACTIONS.map(([key, label]) => {
    const on = status === key;
    return `<button type="button" class="status-button tone-${esc(key)}${on ? ' is-on' : ''}"
                    data-action="run-status" data-run="${esc(run.id)}" data-status="${esc(key)}">${esc(label)}</button>`;
  }).join('');

  return `
    <article class="run-card${status === 'active' ? ' is-active' : ''}${status === 'failed' ? ' is-failed' : ''}">
      <div class="run-card-head">
        <div class="run-card-title">
          <b>${esc(run.name)}</b>
          <span>${esc(run.game_name || run.game_id)} · seit ${esc(formatDate(run.created_at))}</span>
        </div>
        <span class="status-pill tone-${esc(status)}">${esc(RUN_STATUS_LABELS[status])}</span>
        <button type="button" class="card-icon" data-action="rename-run" data-run="${esc(run.id)}"
                title="Run umbenennen">✎</button>
        <button type="button" class="card-icon danger" data-action="delete-run" data-run="${esc(run.id)}"
                title="Run löschen">✕</button>
      </div>

      <div class="run-progress">
        <div class="bar">
          <span class="done" style="width:${esc(percent(caught))}"></span>
          <span class="lost" style="width:${esc(percent(run.failed_count))}"></span>
          <span class="dead" style="width:${esc(percent(run.death_count))}"></span>
        </div>
        <span>${esc(caught)} gefangen · ${esc(run.death_count)} tot · ${esc(run.failed_count)} vergeigt ·
              ${esc(run.encounter_count)} Orte</span>
      </div>

      <div class="chips">${state.players.map((entry) => playerChip(entry)).join('')}</div>

      <div class="run-card-actions">
        <button type="button" class="open-button" data-action="open-run" data-run="${esc(run.id)}">Öffnen</button>
        <div class="status-row"><span class="pixel-label">STATUS</span>${actions}</div>
      </div>
    </article>`;
}

function renderHome() {
  el.homeSub.textContent = `${state.runs.length} Runs · ${state.players.length} Spieler`;
  el.runGrid.innerHTML =
    state.runs.map(runCard).join('') +
    `<button type="button" class="new-run-card" data-action="new-run">
       <b>＋</b>
       <strong>Neuen Run anlegen</strong>
       <span>Spiel, Name und Spieler wählen</span>
     </button>`;
  renderStats();
  el.rosterChips.innerHTML = state.players.map((entry) => playerChip(entry)).join('');
}

// ------------------------------------------------------------ Statistik ---

// Alle drei Zuschnitte rechnen aus derselben Liste: GET /stats liefert jeden Run
// samt Aufschluesselung, gebuendelt wird hier. Ein Request, drei Ansichten - und
// 'pro Variante' braucht keinen eigenen Endpunkt.

/** Mehrere Run-Statistiken zu einem Block zusammenfassen. */
function aggregateStats(entries, title, sub) {
  const deaths = {};
  const misses = {};
  const totals = { locations: 0, caught: 0, pending: 0, deaths: 0, misses: 0, unassigned: 0 };

  for (const entry of entries) {
    totals.locations += entry.encounter_count || 0;
    totals.caught += entry.caught_count || 0;
    totals.pending += entry.pending_count || 0;
    totals.deaths += entry.deaths || 0;
    totals.misses += entry.failed_encounters || 0;
    totals.unassigned += (entry.unassigned_deaths || 0) + (entry.unassigned_failed_encounters || 0);
    for (const person of state.players) {
      deaths[person.id] = (deaths[person.id] || 0) + (entry.deaths_by_player?.[person.id] || 0);
      misses[person.id] = (misses[person.id] || 0) + (entry.failed_encounters_by_player?.[person.id] || 0);
    }
  }
  return { title, sub, totals, ...scorePlayers(deaths, misses) };
}

function runLabel(count) {
  return `${count} ${count === 1 ? 'Run' : 'Runs'}`;
}

function statBlocks() {
  const entries = state.stats?.runs || [];

  if (state.statsScope === 'run') {
    return entries.map((entry) =>
      aggregateStats(
        [entry],
        entry.name,
        `${entry.game_name || entry.game_id} · ${RUN_STATUS_LABELS[entry.status] || RUN_STATUS_LABELS.active}`,
      ),
    );
  }

  if (state.statsScope === 'variant') {
    const byGame = new Map();
    for (const entry of entries) {
      if (!byGame.has(entry.game_id)) byGame.set(entry.game_id, []);
      byGame.get(entry.game_id).push(entry);
    }
    return [...byGame.values()].map((group) =>
      aggregateStats(group, group[0].game_name || group[0].game_id, runLabel(group.length)),
    );
  }

  return [aggregateStats(entries, 'Alle Runs', `${runLabel(entries.length)} · ${state.players.length} Spieler`)];
}

function statCounter(value, label, tone = '') {
  return `<div class="stat-counter ${esc(tone)}"><b>${esc(value)}</b><span>${esc(label)}</span></div>`;
}

function statBlock(block) {
  const { totals, worst } = block;
  const bars = failRows(block.scored, block.max);

  // Ohne Punkte gibt es keinen Schuldigsten: liefen alle Vorfaelle auf 'niemand',
  // stuende hier sonst der erste Spieler der Liste, der nichts verbrochen hat.
  const foot =
    totals.deaths + totals.misses === 0
      ? 'Noch nichts schiefgegangen.'
      : `Schuldigster: ${worst && worst.score > 0 ? worst.player.name : '–'}` +
        (totals.unassigned ? ` · ${totals.unassigned} ohne Schuldigen` : '');

  return `
    <article class="stat-card">
      <div class="stat-card-head">
        <b>${esc(block.title)}</b>
        <span>${esc(block.sub)}</span>
      </div>
      <div class="stat-counters">
        ${statCounter(`${totals.caught}/${totals.locations}`, 'GEFANGEN', 'good')}
        ${statCounter(totals.deaths, 'TOT', 'bad')}
        ${statCounter(totals.misses, 'VERGEIGT', 'warn')}
        ${statCounter(totals.pending, 'OFFEN')}
      </div>
      <div class="stat-bars">${bars}</div>
      <span class="stat-foot">${esc(foot)}</span>
    </article>`;
}

function renderStats() {
  el.statsScope.innerHTML = STATS_SCOPES.map(
    ([key, label, title]) => `<button type="button" class="${state.statsScope === key ? 'is-on' : ''}"
                                      data-action="stats-scope" data-scope="${esc(key)}"
                                      title="${esc(title)}">${esc(label)}</button>`,
  ).join('');

  if (!state.stats) {
    el.statsGrid.innerHTML = '<p class="stats-empty">Statistik wird geladen…</p>';
    return;
  }
  const blocks = statBlocks();
  // 'Gesamt' ist ein Block und bekommt die ganze Breite; die anderen kacheln.
  el.statsGrid.classList.toggle('is-single', blocks.length === 1);
  el.statsGrid.innerHTML = blocks.length
    ? blocks.map(statBlock).join('')
    : '<p class="stats-empty">Noch keine Runs.</p>';
}

// ------------------------------------------------------------- Run-View ---

/** Der Schnappschuss im Rechner gilt nur, solange die Zelle dieselbe Art zeigt.
 *
 * `showMonTypes()` kopiert Name, Sprite und Typen - traegt jemand danach etwas
 * anderes ein oder meldet die Reihe als verloren, stuenden zwei verschiedene
 * Pokémon nebeneinander: das neue in der Tabelle, das alte im Rechner. Die
 * gewaehlten Typen bleiben stehen, sie sind ab hier eine Auswahl von Hand.
 */
function syncTypeMon() {
  const mon = state.typeMon;
  if (mon && findRow(mon.rowId)?.picks[mon.playerId]?.species !== mon.species) state.typeMon = null;
}

function renderRunView() {
  syncTypeMon();
  renderFilters();
  renderSort();
  renderTable();
  renderCapCard();
  renderFailStats();
  renderTypeCalculator();
}

function renderFilters() {
  const counts = categoryCounts();
  el.filterBar.innerHTML = FILTERS.map(
    ([key, label]) => `<button type="button" class="filter-button${state.filter === key ? ' is-on' : ''}"
                               data-action="filter" data-filter="${esc(key)}">${esc(label)}<span>${esc(counts[key])}</span></button>`,
  ).join('');
}

function renderSort() {
  const options = [
    ['order', 'Spielreihenfolge', 'Orte in der Reihenfolge, in der man sie besucht'],
    ['status', 'Nach Status', 'Team → Box → tot → verloren → offen'],
  ];
  el.sortBar.innerHTML = options.map(
    ([key, label, title]) => `<button type="button" class="${state.sort === key ? 'is-on' : ''}"
                                      data-action="sort" data-sort="${esc(key)}" title="${esc(title)}">${esc(label)}</button>`,
  ).join('');
}

function pickCell(row, entry, context) {
  const pick = row.picks[entry.id] || {};
  const cat = context.cat;
  const lost = cat === 'verloren';
  const dead = pick.status === 'dead';
  const info = speciesInfo(pick.species);
  const name = lost ? '' : String(pick.name || info?.name || '');

  if (!name) {
    // Leere Zelle: gestrichelte Kachel mit "+", bei verlorener Reihe stattdessen
    // der Hinweis - dort gibt es nichts mehr einzutragen.
    const title = lost ? 'Encounter verloren' : `${entry.name}: Encounter eintragen`;
    return `
      <div class="pick-cell">
        <button type="button" class="pick-button" title="${esc(title)}"
                data-action="pick" data-player="${esc(entry.id)}"${lost ? ' disabled' : ''}>
          <span class="sprite ${lost ? 'is-lost' : 'is-empty'}">${lost ? '' : '+'}</span>
          <span class="pick-text"><span class="pick-name is-empty">${lost ? 'verloren' : 'eintragen'}</span></span>
        </button>
      </div>`;
  }

  const types = speciesTypes(pick.species);
  const multiplier = context.selection.length && types.length ? attackAgainst(context.selection, types) : 1;
  const weak = context.mode === 'atk' && !dead && multiplier >= 2;
  const dupe = dupeReason(context.counts, entry.id, pick.species, pick.species);
  const spriteClass = dead ? 'is-dead' : row.in_team ? 'is-team' : '';
  const background = info ? ` style="background-image:url('${esc(spriteUrl(info.dex))}')"` : '';

  const loaded = context.calcKey === `${row.id}:${entry.id}`;

  return `
    <div class="pick-cell${weak ? ' is-weak' : ''}">
      <button type="button" class="pick-button" title="${esc(`${entry.name}: ${name} ändern`)}"
              data-action="pick" data-player="${esc(entry.id)}">
        <span class="sprite ${spriteClass}"${background}></span>
        <span class="pick-text">
          <span class="pick-name${dead ? ' is-dead' : ''}">${esc(name)}</span>
          <span class="pick-types">
            ${types.map(typeBadge).join('')}
            ${weak ? `<span class="weak-note">${esc(formatFactor(multiplier))}</span>` : ''}
            ${dupe ? `<span class="dupe-note" title="${esc(dupe)}">⚠</span>` : ''}
          </span>
        </span>
      </button>
      ${types.length
        ? `<button type="button" class="calc-button${loaded ? ' is-on' : ''}" data-action="type-mon"
                   data-player="${esc(entry.id)}"
                   title="${esc(`${name}: Angriff und Abwehr im Typenrechner`)}">⚔</button>`
        : ''}
      <button type="button" class="kill-button${dead ? ' is-dead' : ''}" data-action="kill" data-player="${esc(entry.id)}"
              title="${esc(dead ? 'Reihe wiederbeleben' : `${entry.name} verliert ${name} – koppelt die Reihe und trägt ${entry.name} als Schuldigen ein`)}"
              >${dead ? '↺' : '☠'}</button>
    </div>`;
}

function rowHtml(row, context) {
  const cat = category(row);
  const inner = { ...context, cat };
  const blamed = player(row.responsible_player);
  const sub = blamed
    ? `<span class="blamed">Schuld: ${esc(blamed.name)}</span>`
    : row.responsible_player === NO_CULPRIT
      ? '<span>Schuld: niemand</span>'
      : cat === 'offen'
        ? '<span>noch kein Encounter</span>'
        : '<span></span>';

  const canTeam = row.outcome === 'caught';
  const full = context.teamCount >= TEAM_SIZE && !row.in_team;
  const ballClass = row.in_team ? 'is-on' : !canTeam ? 'is-locked' : full ? 'is-full' : 'can-toggle';
  const ballTitle = !canTeam
    ? 'kein Fang'
    : row.in_team
      ? 'Aus dem Team nehmen'
      : full
        ? `Team ist voll (${TEAM_SIZE})`
        : 'Ins Team aufnehmen';

  const action = { offen: 'verloren melden', verloren: 'zurücksetzen', tot: 'wiederbeleben' }[cat] || '';

  return `
    <div class="table-row is-${esc(cat)}" data-row="${esc(row.id)}">
      <div class="team-cell">
        <button type="button" class="ball-button ${ballClass}" data-action="team" title="${esc(ballTitle)}"
                ${canTeam && (!full || row.in_team) ? '' : 'disabled'}><span class="ball"></span></button>
      </div>
      <div class="loc-cell">
        <b>${esc(row.encounter)}</b>
        ${sub}
      </div>
      ${state.players.map((entry) => pickCell(row, entry, inner)).join('')}
      <div class="state-cell">
        <span class="state-pill cat-${esc(cat)}">${esc(cat.toUpperCase())}</span>
        ${action
          ? `<button type="button" class="state-action${cat === 'offen' ? ' is-warning' : ''}" data-action="state">${esc(action)}</button>`
          : ''}
      </div>
    </div>`;
}

function renderTable() {
  const players = state.players;
  // Kopf und Zeilen teilen sich dasselbe Raster; es haengt an der Spieleranzahl
  // und steht deshalb als Variable am Scroll-Container. Die Spalte ist seit dem
  // Rechner-Knopf breiter: neben Name und Typen stehen jetzt zwei Knoepfe.
  el.tableScroll.style.setProperty('--cols', `56px 164px repeat(${players.length}, minmax(226px, 1fr)) 124px`);
  el.tableScroll.style.setProperty('--min', `${344 + players.length * 226}px`);

  el.tableHead.innerHTML =
    '<span>TEAM</span><span>ORT</span>' +
    players
      .map(
        (entry) => `<span class="player-head"><span class="dot" style="background:${esc(entry.color)}"></span>
                    <span>${esc(entry.name.toUpperCase())}</span></span>`,
      )
      .join('') +
    '<span>STATUS</span>';

  const context = {
    counts: pickCounts(),
    teamCount: rows().filter((row) => row.in_team).length,
    selection: state.types,
    mode: state.mode,
    calcKey: state.typeMon ? `${state.typeMon.rowId}:${state.typeMon.playerId}` : null,
  };
  const visible = visibleRows();
  const term = state.search.trim();
  el.tableRows.innerHTML = visible.length
    ? visible.map((row) => rowHtml(row, context)).join('')
    : `<p class="empty-hint">${term ? `Kein Ort passt zu „${esc(term)}“.` : 'Zu diesem Filter gibt es gerade nichts.'}</p>`;
}

function renderCapCard() {
  const caps = catalog()?.level_caps || [];
  if (!caps.length) {
    el.capCard.innerHTML = '<span class="cap-foot">Für dieses Spiel sind keine Level-Caps hinterlegt.</span>';
    return;
  }

  const index = Math.min(Math.max(state.run?.progress ?? 0, 0), caps.length - 1);
  const cap = caps[index];
  const type = TYPE_LABELS[cap.type] ? cap.type : '';

  const ticks = caps
    .map((entry, at) => {
      const title = `${entry.leader} · ${entry.place} · Lv ${entry.cap}${TYPE_LABELS[entry.type] ? ` · ${TYPE_LABELS[entry.type]}` : ''}`;
      const classes = ['cap-tick'];
      if (at <= index) classes.push('is-done');
      if (at === index) classes.push('is-current');
      if (TYPE_LABELS[entry.type]) classes.push(`t-${entry.type}`);
      return `<button type="button" class="${classes.join(' ')}" data-action="cap" data-cap="${at}" title="${esc(title)}"></button>`;
    })
    .join('');

  el.capCard.innerHTML = `
    <div class="cap-head">
      <span class="pixel-label">LEVEL-CAP · GILT FÜR ALLE</span>
      <button type="button" class="cap-step" data-action="cap-step" data-delta="-1"
              ${index <= 0 ? 'disabled' : ''} title="Einen Kampf zurück">−</button>
      <button type="button" class="cap-step" data-action="cap-step" data-delta="1"
              ${index >= caps.length - 1 ? 'disabled' : ''} title="Nächster Kampf">+</button>
    </div>
    <span class="cap-value">Lv ${esc(cap.cap)}</span>
    <div class="cap-leader-row">
      ${type
        ? typeBadge(type)
        : '<span class="type-badge is-mixed t-normal"><span class="type-icon"></span>GEMISCHT</span>'}
      <span class="cap-leader">${esc(cap.leader)} · ${esc(cap.place)}</span>
    </div>
    <div class="cap-ticks">${ticks}</div>
    <span class="cap-foot">KAMPF ${index + 1} VON ${caps.length} ·
      ${esc((state.run?.game_name || state.run?.game_id || '').toUpperCase())}</span>`;
}

function renderFailStats() {
  const { scored, worst, max } = failStats();
  el.failList.innerHTML = failRows(scored, max);
  el.blameLine.textContent = worst
    ? `Schuldigster: ${worst.player.name} · Schuld = Tod ×2 + vergeigter Encounter`
    : '';
}

/** Die Multiplikatoren einer Auswahl als Balkenliste. */
function bucketList(selection, mode) {
  const grouped = selection.length ? bucketsFor(selection, mode) : new Map();
  return BUCKETS.filter((value) => grouped.has(value))
    .map((value) => {
      const tone = `${mode}-${BUCKET_CLASS[value]}`;
      return `
        <div class="bucket${value < 2 ? ' is-weak' : ''}">
          <span class="bucket-badge ${esc(tone)}">${esc(formatFactor(value))}</span>
          <div class="bucket-items">${grouped.get(value).map(typeBadge).join('')}</div>
        </div>`;
    })
    .join('');
}

function typeSection(label, body) {
  return `<div class="type-section">
    <span class="pixel-label soft">${esc(label)}</span>
    ${body || '<span class="type-plain">überall ×1</span>'}
  </div>`;
}

/** Das Pokémon, das gerade im Rechner liegt - oder nichts. */
function renderTypeMon() {
  const mon = state.typeMon;
  el.typeMon.hidden = !mon;
  if (!mon) return;
  el.typeMon.innerHTML = `
    <span class="sprite" style="background-image:url('${esc(spriteUrl(mon.dex))}')"></span>
    <span class="type-mon-text">
      <b><span class="dot" style="background:${esc(mon.color)}"></span>${esc(mon.name)}</b>
      <span class="type-mon-types">${mon.types.map(typeBadge).join('')}</span>
    </span>
    <button type="button" class="icon-button" data-action="type-mon-clear"
            title="Pokémon aus dem Rechner nehmen">✕</button>`;
}

function renderTypeCalculator() {
  const selection = state.types;
  const attacking = state.mode === 'atk';

  renderTypeMon();

  el.typeModes.innerHTML = [['atk', 'ANGRIFF'], ['def', 'ABWEHR']]
    .map(
      ([key, label]) => `<button type="button" class="${state.mode === key ? 'is-on' : ''}"
                                 data-action="type-mode" data-mode="${esc(key)}">${esc(label)}</button>`,
    )
    .join('');

  el.typeGrid.innerHTML = TYPE_ORDER.map((type) => {
    const on = selection.includes(type);
    return `<button type="button" class="type-chip t-${esc(type)}${on ? ' is-on' : ''}" data-action="type" data-type="${esc(type)}"
                    aria-pressed="${on}"><span class="type-icon"></span>${esc(TYPE_LABELS[type])}</button>`;
  }).join('');

  el.typeReset.hidden = !selection.length;

  if (state.typeMon) {
    // Bei einem Pokémon aus der Tabelle ist die Frage am Tisch immer beides:
    // womit tut es weh und was tut ihm weh. Der Modus daneben entscheidet
    // weiterhin nur, was die Tabelle markiert.
    el.typeResultTitle.textContent = `${state.typeMon.name}: Angriff & Abwehr`;
    el.typeResultList.innerHTML =
      typeSection('ANGRIFF · SEINE TYPEN GEGEN', bucketList(selection, 'atk')) +
      typeSection('ABWEHR · SCHADEN AN IHM', bucketList(selection, 'def'));
  } else {
    const labels = selection.map((type) => TYPE_LABELS[type].charAt(0) + TYPE_LABELS[type].slice(1).toLowerCase());
    el.typeResultTitle.textContent = selection.length
      ? `${labels.join(' + ')} ${attacking ? 'greift an' : 'wird angegriffen'}`
      : 'Typ wählen (max. 2)';
    el.typeResultList.innerHTML = bucketList(selection, state.mode);
  }

  el.teamCheckTitle.textContent = attacking ? 'WER HAT PROBLEME DAMIT' : 'WER HAT LINKS DIESES TYPS';
  el.teamCheckList.innerHTML = state.players
    .map((entry) => {
      const mons = teamMons(entry.id);
      const hits = selection.length
        ? mons.filter((pick) => {
            const types = speciesTypes(pick.species);
            if (!types.length) return false;
            return attacking
              ? attackAgainst(selection, types) >= 2
              : selection.some((type) => types.includes(type));
          })
        : [];
      const risk = !selection.length
        ? '—'
        : hits.length === 0
          ? attacking ? 'SAUBER' : 'KEINE'
          : `${hits.length}${attacking ? ' ANFÄLLIG' : ' LINKS'}`;
      const tone = !selection.length || hits.length === 0 ? '' : attacking ? 'is-bad' : 'is-link';
      const sprites = hits
        .map((pick) => {
          const info = speciesInfo(pick.species);
          const name = pick.name || info?.name || '';
          return info
            ? `<span title="${esc(name)}" style="background-image:url('${esc(spriteUrl(info.dex))}')"></span>`
            : '';
        })
        .join('');

      return `
        <div class="check-row">
          <span class="dot" style="background:${esc(entry.color)}"></span>
          <span class="name">${esc(entry.name)}</span>
          <div class="check-mons">${sprites}</div>
          <span class="check-risk ${tone}">${esc(risk)}</span>
        </div>`;
    })
    .join('');
}

// -------------------------------------------------------------- Schreiben -

async function patchRow(rowId, body, query = '') {
  const updated = await write(() =>
    api(`/runs/${encodeURIComponent(state.currentRunId)}/encounters/${encodeURIComponent(rowId)}${query}`, {
      method: 'PATCH',
      body,
    }),
  );
  if (!updated) return null;
  const index = rows().findIndex((row) => row.id === updated.id);
  if (index >= 0) state.run.encounters[index] = updated;
  // Eine Aenderung verschiebt Zaehler, Filtergruppe, Fail-Statistik und
  // Typen-Check gleichzeitig - die Ansicht wird deshalb ganz neu gezeichnet.
  renderHeadStats();
  renderRunView();
  return updated;
}

/** Schreibt nur, wenn sich wirklich etwas aendert - schluckt Phantom-Events. */
async function patchPick(row, playerId, changes, query = '') {
  const pick = row.picks[playerId] || {};
  const differs = Object.entries(changes).some(([key, value]) => (pick[key] ?? null) !== (value ?? null));
  if (!differs) return null;
  return patchRow(row.id, { picks: { [playerId]: changes } }, query);
}

/** Alle Picks einer Zeile auf einmal - fuer Zuruecksetzen und Wiederbeleben. */
function allPicks(changes) {
  return Object.fromEntries(state.players.map((entry) => [entry.id, changes]));
}

async function handleKill(row, playerId) {
  if (row.picks[playerId]?.status === 'dead') {
    // Wiederbeleben gilt fuer die ganze Reihe und laeuft deshalb ohne Kopplung -
    // sonst zoege der erste tote Pick alle sofort wieder mit.
    await patchRow(row.id, { picks: allPicks({ status: 'alive' }), responsible_player: null }, '?couple=false');
    return;
  }
  const body = { picks: { [playerId]: { status: 'dead' } } };
  if (!row.responsible_player) body.responsible_player = playerId;
  await patchRow(row.id, body);
}

async function handleStateAction(row) {
  const cat = category(row);
  if (cat === 'offen') {
    openLostDialog(row);
    return;
  }
  if (cat === 'verloren') {
    await patchRow(row.id, {
      outcome: 'pending',
      picks: allPicks({ species: null, name: '' }),
      responsible_player: null,
    });
    return;
  }
  if (cat === 'tot') {
    await patchRow(row.id, { picks: allPicks({ status: 'alive' }), responsible_player: null }, '?couple=false');
  }
}

async function changeCap(index) {
  const caps = catalog()?.level_caps || [];
  const next = Math.min(Math.max(index, 0), Math.max(caps.length - 1, 0));
  if (!caps.length || next === state.run.progress) return;
  const updated = await write(() =>
    api(`/runs/${encodeURIComponent(state.currentRunId)}`, { method: 'PATCH', body: { progress: next } }),
  );
  if (updated) {
    state.run.progress = updated.progress;
    renderCapCard();
  }
}

async function setRunStatus(runId, status) {
  const updated = await write(() => api(`/runs/${encodeURIComponent(runId)}`, { method: 'PATCH', body: { status } }));
  if (updated) {
    await loadRuns();
    render();
  }
}

function openRenameDialog(runId) {
  const run = state.runs.find((entry) => entry.id === runId);
  if (!run) return;
  el.renameForm.dataset.run = run.id;
  el.renameSub.textContent = `${run.game_name || run.game_id} · seit ${formatDate(run.created_at)}`;
  el.renameInput.value = run.name;
  el.renameDialog.showModal();
  el.renameInput.select();
}

el.renameForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const runId = el.renameForm.dataset.run;
  const name = el.renameInput.value.trim();
  el.renameDialog.close();
  if (!runId || !name) return;
  const updated = await write(() => api(`/runs/${encodeURIComponent(runId)}`, { method: 'PATCH', body: { name } }));
  if (!updated) return;
  await loadRuns();
  // Der Name steht auch im Kopf der Run-Ansicht.
  if (state.view === 'run' && state.currentRunId === runId) await loadRun(runId);
  render();
});

async function deleteRun(runId) {
  const run = state.runs.find((entry) => entry.id === runId);
  if (!run) return;
  const confirmed = await ask({
    title: `„${run.name}“ löschen?`,
    text:
      `Alle ${run.encounter_count} Zeilen verschwinden mit. ` +
      'Das lässt sich nur noch aus einem Backup zurückholen.',
  });
  if (!confirmed) return;
  // DELETE antwortet mit 204, also ohne Inhalt - der Erfolg muss selbst markiert
  // werden, sonst ist er von einem abgefangenen Fehler nicht zu unterscheiden.
  const removed = await write(() =>
    api(`/runs/${encodeURIComponent(runId)}`, { method: 'DELETE' }).then(() => true),
  );
  if (!removed) return;
  if (state.currentRunId === runId) state.currentRunId = null;
  await reloadEverything();
}

// ------------------------------------------------------ Pokémon-Auswahl ---

// Der Dialog ist einer fuer die ganze Tabelle: 132 Zellen mit je einer eigenen
// Liste waeren sonst zehntausende DOM-Knoten.

/** Ein Eintrag der Auswahlliste, angereichert um alles zum Suchen und Anzeigen.
 *
 * Die Ortslisten fuehren weder Typen noch Familie - beides steht nur im Pokedex
 * (`index.species`). Ohne den Nachschlag blieben ausgerechnet die Arten des
 * Ortes ohne Typ-Badge. Die Suchschluessel entstehen einmal beim Oeffnen des
 * Dialogs und nicht bei jedem Tastendruck.
 */
function pickerEntry(entry, info = speciesInfo(entry.species)) {
  const merged = { ...entry, ...(info || {}) };
  merged.search = [fold(merged.name), fold(merged.species)];
  return merged;
}

/** Die Auswahlliste: erst die Arten des Ortes nach Methode, dann der Rest. */
function pickerGroups(row) {
  const encounters = catalogLocation(row.location_id)?.encounters || [];
  const groups = [];
  const byMethod = new Map();
  for (const entry of encounters) {
    const key = entry.methods.join(' / ');
    if (!byMethod.has(key)) byMethod.set(key, []);
    byMethod.get(key).push(pickerEntry(entry));
  }
  for (const [label, entries] of byMethod) groups.push({ label: `${label} · KOMMT HIER VOR`, entries, local: true });

  const here = new Set(encounters.map((entry) => entry.species));
  const rest = (catalog()?.index.choices || []).filter((entry) => !here.has(entry.species));
  if (rest.length) groups.push({ label: 'ALLE ANDEREN', entries: rest, local: false });
  return groups;
}

function renderPickerList() {
  if (!state.picker) return;
  const { row, playerId, groups, counts } = state.picker;
  const typed = el.pickerSearch.value.trim();
  const term = fold(typed);
  const own = row.picks[playerId]?.species || null;

  // Zwei Durchgaenge: solange irgendetwas woertlich passt, steht auch nur das
  // da. Erst wenn ueberall nichts ankommt, wird mit Tippfehler-Toleranz gesucht -
  // 'Geweiher' findet dann 'Gehweiher', ohne dass die Liste sonst aufweicht.
  let perGroup = groups.map((group) => searchEntries(group.entries, term, false));
  const fuzzy = Boolean(term) && !perGroup.some((entries) => entries.length);
  if (fuzzy) perGroup = groups.map((group) => searchEntries(group.entries, term, true));

  // Sortiert wird nur innerhalb einer Gruppe; im Toleranz-Durchgang stehen
  // deshalb auch die Gruppen nach ihrem besten Treffer. Enter nimmt den ersten
  // Eintrag im DOM - und das muss der beste ueber alle Gruppen hinweg sein.
  const order = groups.map((group, at) => at);
  if (fuzzy) order.sort((a, b) => groupDistance(perGroup[a], term) - groupDistance(perGroup[b], term));

  let html = fuzzy ? `<p class="picker-hint">Nichts passt genau zu „${esc(typed)}“ – ähnliche Namen:</p>` : '';
  let matches = 0;
  for (const at of order) {
    const group = groups[at];
    const hits = perGroup[at];
    if (!hits.length) continue;
    matches += hits.length;

    html += `<div class="picker-group">
      <div class="picker-group-head">
        <span class="pixel-label${group.local ? ' is-local' : ''}">${esc(group.label)}</span>
        <span class="rule"></span>
        <span class="count">${esc(hits.length)}</span>
      </div>
      <div class="picker-options">`;
    for (const entry of hits) {
      const dupe = dupeReason(counts, playerId, own, entry.species);
      const classes = ['picker-option'];
      if (entry.species === own) classes.push('is-current');
      else if (dupe) classes.push('is-dupe');
      html += `
        <button type="button" class="${classes.join(' ')}" data-species="${esc(entry.species)}"
                title="${esc(dupe || entry.name)}">
          <img src="${esc(spriteUrl(entry.dex))}" alt="" loading="lazy">
          <span class="option-text">
            <span class="option-name">${esc(entry.name)}</span>
            <span class="option-meta">
              ${(entry.types || []).map(typeBadge).join('')}
              <span class="option-dex">#${esc(entry.dex)}</span>
            </span>
          </span>
          ${dupe ? '<span class="warn">⚠</span>' : ''}
        </button>`;
    }
    html += '</div></div>';
  }

  el.pickerList.innerHTML = matches
    ? html
    : `<p class="picker-empty">Nichts gefunden zu „${esc(typed)}“ – deutscher oder englischer Name.</p>`;
}

function openPicker(row, playerId) {
  const entry = player(playerId);
  const own = row.picks[playerId] || {};
  state.picker = { row, playerId, groups: pickerGroups(row), counts: pickCounts() };

  el.pickerDot.style.background = entry?.color || 'var(--accent)';
  el.pickerTitle.textContent = `${entry ? entry.name : playerId} · ${row.encounter}`;
  const current = own.name || speciesInfo(own.species)?.name || '';
  el.pickerSub.textContent = current ? `Aktuell: ${current} · anderes Pokémon wählen` : 'Gefangenes Pokémon eintragen';
  el.pickerClear.textContent = isFilled(own) ? 'Eintrag löschen' : 'Abbrechen';
  el.pickerSearch.value = '';
  renderPickerList();
  el.pickerDialog.showModal();
  el.pickerSearch.focus();
}

async function choosePick(species) {
  const context = state.picker;
  el.pickerDialog.close();
  if (!context) return;
  const { row, playerId } = context;

  if (species === null) {
    await patchPick(row, playerId, { species: null, name: '' });
    return;
  }
  // Die API laesst nur durch, was der Katalog fuer diesen Ort kennt. Zur Auswahl
  // steht aber der ganze Pokedex, also traegt der Aufrufer die Entscheidung und
  // schickt force mit - geprueft wird sichtbar im Dialog, nicht per 422.
  const local = (catalogLocation(row.location_id)?.encounters || []).some((entry) => entry.species === species);
  const info = speciesInfo(species);
  await patchPick(row, playerId, { species, name: info?.name || species }, local ? '' : '?force=true');
}

el.pickerDialog.addEventListener('close', () => {
  state.picker = null;
});

el.pickerSearch.addEventListener('input', renderPickerList);

el.pickerSearch.addEventListener('keydown', (event) => {
  if (event.key !== 'Enter') return;
  // Enter nimmt den ersten Treffer - sonst muesste man nach dem Tippen doch
  // wieder zur Maus greifen.
  event.preventDefault();
  const first = el.pickerList.querySelector('[data-species]');
  if (first) choosePick(first.dataset.species);
});

el.pickerList.addEventListener('click', (event) => {
  const button = event.target.closest('[data-species]');
  if (button) choosePick(button.dataset.species);
});

el.pickerClear.addEventListener('click', () => {
  const context = state.picker;
  if (context && isFilled(context.row.picks[context.playerId])) choosePick(null);
  else el.pickerDialog.close();
});

// ------------------------------------------------- Verlorener Encounter ---

function openLostDialog(row) {
  state.lostRowId = row.id;
  el.lostSub.textContent = `${row.encounter} · die Reihe wird für alle als verloren markiert.`;
  el.culpritList.innerHTML =
    state.players
      .map(
        (entry) => `<button type="button" class="culprit-button" data-culprit="${esc(entry.id)}">
                      <span class="dot" style="background:${esc(entry.color)}"></span>${esc(entry.name)}</button>`,
      )
      .join('') +
    `<button type="button" class="culprit-button" data-culprit="${esc(NO_CULPRIT)}">
       <span class="dot" style="background:#c8d0dc"></span>Niemand – keiner war schuld</button>`;
  el.lostDialog.showModal();
}

el.culpritList.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-culprit]');
  if (!button) return;
  const row = findRow(state.lostRowId);
  el.lostDialog.close();
  if (!row) return;
  // Die API traegt bei 'failed' den Platzhalter bei allen Spielern ein und nimmt
  // die Zeile aus dem Team - hier steht nur, wer es verbockt hat.
  await patchRow(row.id, { outcome: 'failed', responsible_player: button.dataset.culprit });
});

el.lostDialog.addEventListener('close', () => {
  state.lostRowId = null;
});

// ------------------------------------------------------ Spielerverwaltung -

async function openPlayersDialog() {
  el.playerName.value = '';
  renderPlayerList();
  el.playersDialog.showModal();
  // Die Tallies gelten fuer alle Runs - anders als die Fail-Statistik der
  // rechten Spalte, die nur den offenen Run zeigt.
  await loadStats();
  renderPlayerList();
}

function renderPlayerList() {
  const deaths = state.stats?.deaths_by_player || {};
  const misses = state.stats?.failed_encounters_by_player || {};
  el.playerList.innerHTML = state.players
    .map(
      (entry) => `
      <div class="player-row">
        <span class="dot" style="background:${esc(entry.color)}"></span>
        <span class="name">${esc(entry.name)}</span>
        <span class="tally">${esc(deaths[entry.id] || 0)} ✝ · ${esc(misses[entry.id] || 0)} ✗</span>
        <button type="button" data-remove="${esc(entry.id)}" title="Spieler entfernen">✕</button>
      </div>`,
    )
    .join('');
}

el.playerList.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-remove]');
  if (!button) return;
  const entry = player(button.dataset.remove);
  if (!entry) return;
  const confirmed = await ask({
    title: `${entry.name} entfernen?`,
    text: 'Die Einträge dieses Spielers verschwinden in allen Runs.',
    confirmLabel: 'Entfernen',
  });
  if (!confirmed) return;
  // DELETE antwortet mit 204, also ohne Inhalt - der Erfolg muss hier selbst
  // markiert werden, sonst ist er von einem abgefangenen Fehler nicht zu
  // unterscheiden (beides waere null).
  const removed = await write(() =>
    api(`/players/${encodeURIComponent(entry.id)}`, { method: 'DELETE' }).then(() => true),
  );
  if (!removed) return;
  await reloadEverything();
  renderPlayerList();
});

el.playerForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const name = el.playerName.value.trim();
  if (!name) return;
  const roster = await write(() => api('/players', { method: 'POST', body: { name } }));
  if (!roster) return;
  el.playerName.value = '';
  await reloadEverything();
  renderPlayerList();
});

// ------------------------------------------------------------- Neuer Run -

function openRunDialog() {
  state.newRunGame = state.newRunGame || state.run?.game_id || state.games[0]?.id || null;
  el.runName.value = `Run ${state.runs.length + 1}`;
  renderRunDialog();
  el.runDialog.showModal();
  el.runName.focus();
}

function renderRunDialog() {
  el.runGames.innerHTML = state.games
    .map(
      (game) => `<button type="button" class="choice-button${game.id === state.newRunGame ? ' is-on' : ''}"
                          data-game="${esc(game.id)}">${esc(game.name)}</button>`,
    )
    .join('');
  el.runRoster.innerHTML = state.players.map((entry) => playerChip(entry, 'chip')).join('');
}

el.runGames.addEventListener('click', (event) => {
  const button = event.target.closest('[data-game]');
  if (!button) return;
  state.newRunGame = button.dataset.game;
  renderRunDialog();
});

el.runForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const name = el.runName.value.trim();
  if (!name || !state.newRunGame) return;
  const created = await write(() =>
    api('/runs', { method: 'POST', body: { name, game_id: state.newRunGame, make_current: true } }),
  );
  if (!created) return;
  el.runDialog.close();
  await loadRuns();
  await openRun(created.id);
});

// --------------------------------------------------------- Interaktionen -

document.querySelectorAll('dialog [data-close]').forEach((button) => {
  button.addEventListener('click', () => button.closest('dialog').close());
});

// Solange ein Dialog offen war oder der Tab im Hintergrund lag, wurde nicht neu
// gezeichnet. Beides endet hier - also nachholen.
document.querySelectorAll('dialog').forEach((dialog) => dialog.addEventListener('close', refreshWhenFree));
document.addEventListener('visibilitychange', refreshWhenFree);

el.brandButton.addEventListener('click', () => showHome());
el.playersButton.addEventListener('click', openPlayersDialog);

// Nur die Tabelle neu zeichnen: die Toolbar bleibt stehen, sonst verlöre das
// Suchfeld bei jedem Tastendruck den Fokus.
el.locationSearch.addEventListener('input', () => {
  state.search = el.locationSearch.value;
  renderTable();
});

el.locationSearch.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape' || !el.locationSearch.value) return;
  // Escape leert erst die Suche, statt gleich etwas anderes zu schliessen.
  event.stopPropagation();
  el.locationSearch.value = '';
  state.search = '';
  renderTable();
});

el.typeReset.addEventListener('click', () => {
  state.types = [];
  state.typeMon = null;
  renderRunView();
});

/** Ein Pokémon aus der Tabelle in den Typenrechner legen.
 *
 * Die Auswahl im Rechner sind danach genau seine Typen, das Ergebnisfeld zeigt
 * Angriff und Abwehr zugleich. Ohne Typen im Katalog (Freitext-Eintrag) gibt es
 * den Knopf gar nicht erst - hier faellt nur der Rest ab.
 */
function showMonTypes(row, playerId) {
  const pick = row.picks[playerId] || {};
  const types = speciesTypes(pick.species);
  if (!types.length) return;
  const info = speciesInfo(pick.species);
  state.types = types.slice(0, MAX_TYPES);
  state.typeMon = {
    rowId: row.id,
    playerId,
    // Die Art ist der Anker: weicht die Zelle spaeter davon ab, gilt der
    // Schnappschuss nicht mehr (`syncTypeMon()`).
    species: pick.species,
    name: pick.name || info?.name || '',
    dex: info?.dex ?? 0,
    color: player(playerId)?.color || 'var(--accent)',
    types: state.types,
  };
  renderRunView();
  // Auf schmalen Fenstern steht die rechte Spalte unter der Tabelle - ohne das
  // passierte auf den Klick sichtbar nichts.
  el.typeCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/**
 * Beim dritten Typ faellt der aelteste heraus, statt den Klick zu schlucken -
 * eine tote Schaltflaeche liest sich sonst wie ein Fehler.
 */
function toggleType(type) {
  // Von Hand gewaehlte Typen sind nicht mehr das geladene Pokémon.
  state.typeMon = null;
  const at = state.types.indexOf(type);
  if (at >= 0) state.types.splice(at, 1);
  else state.types.push(type);
  while (state.types.length > MAX_TYPES) state.types.shift();
  renderRunView();
}

document.addEventListener('click', async (event) => {
  const target = event.target.closest('[data-action]');
  if (!target || !target.isConnected || target.closest('dialog')) return;
  const action = target.dataset.action;
  const row = target.closest('[data-row]') ? findRow(target.closest('[data-row]').dataset.row) : null;

  if (action === 'new-run') openRunDialog();
  else if (action === 'open-players') openPlayersDialog();
  else if (action === 'open-run') await openRun(target.dataset.run);
  else if (action === 'run-status') await setRunStatus(target.dataset.run, target.dataset.status);
  else if (action === 'rename-run') openRenameDialog(target.dataset.run);
  else if (action === 'delete-run') await deleteRun(target.dataset.run);
  else if (action === 'filter') {
    state.filter = target.dataset.filter;
    renderRunView();
  } else if (action === 'sort') {
    state.sort = target.dataset.sort;
    window.localStorage.setItem(SORT_KEY, state.sort);
    renderRunView();
  } else if (action === 'stats-scope') {
    state.statsScope = target.dataset.scope;
    window.localStorage.setItem(STATS_SCOPE_KEY, state.statsScope);
    renderStats();
  } else if (action === 'type') toggleType(target.dataset.type);
  else if (action === 'type-mode') {
    state.mode = target.dataset.mode;
    renderRunView();
  } else if (action === 'type-mon-clear') {
    state.typeMon = null;
    renderRunView();
  } else if (action === 'cap') await changeCap(Number(target.dataset.cap));
  else if (action === 'cap-step') await changeCap((state.run?.progress ?? 0) + Number(target.dataset.delta));
  else if (!row) return;
  else if (action === 'team') await patchRow(row.id, { in_team: !row.in_team });
  else if (action === 'type-mon') showMonTypes(row, target.dataset.player);
  else if (action === 'kill') await handleKill(row, target.dataset.player);
  else if (action === 'pick') openPicker(row, target.dataset.player);
  else if (action === 'state') await handleStateAction(row);
});

// --------------------------------------------------------------- Laden ----

async function loadRuns() {
  const data = await api('/runs');
  applyRules(data.rules);
  state.players = data.players;
  state.runs = data.runs;
  state.updatedAt = data.updated_at;
  // Faellt der aktuelle Run weg (jemand hat ihn geloescht), sonst laeuft jeder
  // weitere Ladeversuch in einen 404.
  if (!state.currentRunId || !state.runs.some((run) => run.id === state.currentRunId)) {
    state.currentRunId = data.current_run_id;
  }
}

async function loadRun(runId) {
  if (!runId) return;
  const data = await api(`/runs/${encodeURIComponent(runId)}/encounters`);
  state.run = data;
  state.currentRunId = data.run_id;
  state.updatedAt = data.updated_at;
  await ensureCatalog(data.game_id);
}

/** Die Negativstatistik ueber alle Runs.
 *
 * Sie ist Beiwerk und darf deshalb scheitern, ohne die Seite mitzunehmen: der
 * Block zeigt dann seinen Platzhalter, der Rest steht.
 */
async function loadStats() {
  try {
    state.stats = await api('/stats');
  } catch {
    // Ohne Zahlen ist die Uebersicht immer noch die Uebersicht. Der alte Stand
    // faellt dabei weg: er zeigte sonst unbemerkt Runs, die es nicht mehr gibt.
    state.stats = null;
  }
}

async function reloadEverything() {
  await loadRuns();
  if (state.view === 'run') await loadRun(state.currentRunId);
  else await loadStats();
  render();
}

async function openRun(runId) {
  try {
    await loadRun(runId);
    state.view = 'run';
    state.filter = 'alle';
    state.search = '';
    // Das geladene Pokémon gehoerte zum vorherigen Run.
    state.typeMon = null;
    el.locationSearch.value = '';
    updateHash();
    render();
    el.tableScroll.scrollTop = 0;
  } catch (error) {
    showError(`Der Run konnte nicht geladen werden: ${error.message}`);
  }
}

async function showHome() {
  state.view = 'home';
  updateHash();
  // Erst zeichnen, dann die Zahlen nachreichen: die Uebersicht soll nicht auf
  // einen Request warten, den sie auch ohne darstellen kann.
  render();
  await loadStats();
  renderStats();
}

function updateHash() {
  const next = state.view === 'run' && state.run ? `#run=${encodeURIComponent(state.run.run_id)}` : '';
  if (window.location.hash !== next) {
    window.history.replaceState(null, '', next || window.location.pathname + window.location.search);
  }
}

// -------------------------------------------------------------- Polling ---

/** Wann ein Neuzeichnen gerade stoeren wuerde.
 *
 * Ein offener Dialog ist der Fall, der zaehlt: die Auswahlliste unter der Hand
 * neu aufzubauen nimmt dem Klick das Ziel. Das Suchfeld ueber der Tabelle
 * blockiert bewusst nicht - es steht ausserhalb des neu gezeichneten Bereichs
 * und behaelt den Fokus.
 */
function isBusy() {
  return pendingWrites > 0 || Boolean(document.querySelector('dialog[open]'));
}

// Eine Aenderung, die gerade nicht gezeigt werden konnte. Sie ist nicht
// verloren - sie wird nachgeholt, sobald der Weg frei ist.
let refreshPending = false;

async function poll() {
  if (document.hidden || isBusy()) {
    refreshPending = true;
    return;
  }
  refreshPending = false;
  try {
    const seen = state.updatedAt;
    // Ueber loadRuns() statt eigenem Fetch: nur so greift der Rueckfall auf den
    // aktuellen Run des Servers, wenn der eigene inzwischen geloescht wurde.
    await loadRuns();
    if (state.updatedAt === seen) return;
    if (state.view === 'run') await loadRun(state.currentRunId);
    else await loadStats();
    render();
  } catch {
    // Ein verpasster Poll ist kein Fehler, der die Seite stoeren soll.
  }
}

function refreshWhenFree() {
  if (refreshPending && !isBusy() && !document.hidden) poll();
}

/** Push statt Warten: der Server meldet jede Änderung ueber /events.
 *
 * Uebertragen wird nur der Zeitstempel; geladen wird wie beim Poll. Der
 * EventSource verbindet sich nach einem Abbruch von selbst neu, und das Polling
 * laeuft weiter - schluckt ein Proxy den Stream, faellt es auf die zehn Sekunden
 * von vorher zurueck, statt gar nicht mehr zu aktualisieren.
 */
function connectStream() {
  if (!window.EventSource) return;
  const stream = new EventSource(`${API_BASE}/events`);
  stream.addEventListener('message', (event) => {
    let payload = null;
    try {
      payload = JSON.parse(event.data);
    } catch {
      return;
    }
    if (!payload || !payload.updated_at || payload.updated_at === state.updatedAt) return;
    poll();
  });
}

// ----------------------------------------------------------------- Start --

async function init() {
  state.sort = window.localStorage.getItem(SORT_KEY) === 'status' ? 'status' : 'order';
  const scope = window.localStorage.getItem(STATS_SCOPE_KEY);
  if (STATS_SCOPES.some(([key]) => key === scope)) state.statsScope = scope;

  try {
    state.games = await api('/games');
    await loadRuns();

    const wanted = new URLSearchParams(window.location.hash.slice(1)).get('run');
    if (wanted && state.runs.some((run) => run.id === wanted)) {
      await openRun(wanted);
    } else {
      render();
      await loadStats();
      renderStats();
    }

    connectStream();
    window.setInterval(poll, POLL_INTERVAL_MS);
  } catch (error) {
    showError(`Die Tabelle konnte nicht geladen werden: ${error.message}`);
    render();
  }
}

init();
