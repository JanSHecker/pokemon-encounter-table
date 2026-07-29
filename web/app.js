'use strict';

/*
 * Read-write Frontend fuer die gekoppelte Encounter-Tabelle.
 *
 * Es gibt keinen Login und keine Identitaet - wer editiert, ist egal.
 * Abgesichert wird ueber die Historie, in der sich jede Aenderung einzeln
 * zuruecknehmen laesst.
 *
 * API-Basis ueberschreiben (lokale Entwicklung): ?api=http://127.0.0.1:8000
 */

const API_BASE =
  new URLSearchParams(window.location.search).get('api') ||
  window.localStorage.getItem('encounter-api-base') ||
  '/encounter-table/api';

const ARTWORK_BASE = 'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork';
const POLL_INTERVAL_MS = 10000;
const SORT_KEY = 'encounter-sort';
const GENERATION_KEY = 'encounter-type-generation';
// Beide gefuehrten Editionen liegen in Generation 2-5 - danach richtet sich die Vorgabe.
const DEFAULT_GENERATION = 'gen2';
const MAX_TYPES = 2;

// Vertragswerte der API (GET /runs -> rules). Der Platzhalter ist Protokoll: wir
// schreiben ihn als Namen, die API leitet daraus 'failed' ab. Die Vorgaben hier
// gelten nur, bis die erste Antwort da ist - gepflegt wird das im Backend.
let LOST_LABEL = 'Encounter verloren';
let NO_CULPRIT = 'niemand';
let TEAM_SIZE = 6;
let UNDOABLE_ACTIONS = ['row-create', 'row-patch', 'row-delete'];

function applyRules(rules) {
  if (!rules) return;
  LOST_LABEL = rules.lost_label ?? LOST_LABEL;
  NO_CULPRIT = rules.no_culprit ?? NO_CULPRIT;
  TEAM_SIZE = rules.team_size ?? TEAM_SIZE;
  UNDOABLE_ACTIONS = rules.undoable_actions ?? UNDOABLE_ACTIONS;
}

// Jede Sortierung gruppiert nur; innerhalb der Gruppe bleibt die Spielreihenfolge.
const SORTERS = {
  order: () => 0,
  open: (row) => (row.outcome === 'pending' ? 0 : 1),
  caught: (row) => (row.outcome === 'caught' ? 0 : 1),
  team: (row) => (row.in_team ? 0 : 1),
  status: (row) => (row.in_team ? 0 : { caught: 1, pending: 2, failed: 3, dead: 4 }[row.outcome] ?? 5),
};

const OUTCOME_LABELS = {
  pending: 'Offen',
  caught: 'Gefangen',
  dead: 'Tot',
  failed: 'Verloren',
};

const state = {
  games: [],
  catalogs: {},
  players: [],
  runs: [],
  currentRunId: null,
  run: null,
  updatedAt: null,
  view: 'table',
  generation: DEFAULT_GENERATION,
  typeSelection: [],
};

const el = {
  gameSelect: document.getElementById('game-select'),
  runSelect: document.getElementById('run-select'),
  runStatus: document.getElementById('run-status'),
  sortSelect: document.getElementById('sort-select'),
  teamCount: document.getElementById('team-count'),
  lastUpdated: document.getElementById('last-updated'),
  globalError: document.getElementById('global-error'),
  tableHead: document.getElementById('table-head'),
  rows: document.getElementById('encounter-rows'),
  capList: document.getElementById('cap-list'),
  progressLabel: document.getElementById('progress-label'),
  progressUp: document.getElementById('progress-up'),
  progressDown: document.getElementById('progress-down'),
  statScope: document.getElementById('stats-scope'),
  statGrid: document.getElementById('stat-grid'),
  playerStats: document.getElementById('player-stats'),
  runStats: document.getElementById('run-stats'),
  historyRows: document.getElementById('history-rows'),
  newRunButton: document.getElementById('new-run-button'),
  addLocationButton: document.getElementById('add-location-button'),
  runDialog: document.getElementById('run-dialog'),
  runForm: document.getElementById('run-form'),
  runName: document.getElementById('run-name'),
  runGame: document.getElementById('run-game'),
  runPrefill: document.getElementById('run-prefill'),
  runPostgame: document.getElementById('run-postgame'),
  culpritDialog: document.getElementById('culprit-dialog'),
  culpritQuestion: document.getElementById('culprit-question'),
  culpritSelect: document.getElementById('culprit-select'),
  locationDialog: document.getElementById('location-dialog'),
  locationForm: document.getElementById('location-form'),
  locationSelect: document.getElementById('location-select'),
  typeGeneration: document.getElementById('type-generation'),
  typeGrid: document.getElementById('type-grid'),
  typeReset: document.getElementById('type-reset'),
  defenseResult: document.getElementById('defense-result'),
};

const VIEWS = ['table', 'dashboard', 'history', 'types'];

// --------------------------------------------------------------- Helfer ---

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

/** Eine <option> - jeder ausgegebene Wert geht durch esc(). */
function option(value, label, selected) {
  return `<option value="${esc(value)}"${selected ? ' selected' : ''}>${esc(label)}</option>`;
}

function formatDate(value) {
  if (!value) return '';
  return new Intl.DateTimeFormat('de-DE', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value));
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

/** Schreiboperation mit einheitlicher Fehlerbehandlung. */
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
        await loadRun(state.currentRunId);
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

function speciesDex(species) {
  return (species && catalog()?.index.dex.get(species)) || null;
}

async function ensureCatalog(gameId) {
  if (!gameId || state.catalogs[gameId]) return;
  const fetched = await api(`/games/${encodeURIComponent(gameId)}`);
  // Indizes einmal bauen statt pro Zelle: der Katalog aendert sich zur Laufzeit
  // nicht, die Tabelle schlaegt aber fuer jede Zelle darin nach.
  fetched.index = {
    locations: new Map(fetched.locations.map((location) => [location.id, location])),
    dex: new Map(
      fetched.locations.flatMap((location) => location.encounters.map((entry) => [entry.species, entry.dex])),
    ),
  };
  state.catalogs[gameId] = fetched;
}

/** Wie oft jeder Spieler eine Art im Run schon eingetragen hat (Dupes-Clause).
 *
 * Einmal pro Zeichenvorgang statt einmal pro Zelle - sonst waechst der Aufwand
 * quadratisch mit der Zeilenzahl.
 */
function speciesCounts() {
  const counts = new Map();
  for (const row of state.run?.encounters || []) {
    for (const [playerId, pick] of Object.entries(row.picks || {})) {
      if (!pick.species) continue;
      let perPlayer = counts.get(playerId);
      if (!perPlayer) counts.set(playerId, (perPlayer = new Map()));
      perPlayer.set(pick.species, (perPlayer.get(pick.species) || 0) + 1);
    }
  }
  return counts;
}

// -------------------------------------------------------------- Rendern ---

function pickCell(row, player, cell) {
  const pick = row.picks[player.id] || { species: null, name: '', status: 'alive' };
  const counts = cell.counts.get(player.id) || new Map();
  // Diese Zeile zaehlt nicht gegen sich selbst.
  const usedElsewhere = (species) => (counts.get(species) || 0) - (pick.species === species ? 1 : 0) > 0;

  const selected = pick.species || (pick.name ? '__custom__' : '');
  let options = option('', '– leer –', selected === '');
  options += option('__lost__', LOST_LABEL, pick.name === LOST_LABEL);

  for (const [method, entries] of cell.byMethod) {
    options += `<optgroup label="${esc(method)}">`;
    for (const entry of entries) {
      const dupe = usedElsewhere(entry.species) ? ' ⚠' : '';
      options += option(entry.species, `${entry.name}${dupe}`, pick.species === entry.species);
    }
    options += '</optgroup>';
  }

  // Freitext oder ein per force gespeicherter Sonderfall, der nicht in der Liste steht.
  if (pick.name && pick.name !== LOST_LABEL && !cell.known.has(pick.species)) {
    options += option('__keep__', pick.name, true);
  }
  options += option('__custom__', 'Anderes …', false);

  const dex = speciesDex(pick.species);
  const isDead = pick.status === 'dead';

  return `
    <td class="col-player">
      <div class="pick">
        <img class="pick-image" alt="" aria-hidden="true" loading="lazy"
             ${dex ? `src="${ARTWORK_BASE}/${esc(dex)}.png" onload="this.classList.add('loaded')"` : ''}>
        <div class="pick-controls">
          <div class="pick-row">
            <select class="pick-select${isDead ? ' dead' : ''}" data-action="species" data-player="${esc(player.id)}"
                    aria-label="Pokémon von ${esc(player.name)}">${options}</select>
            <button type="button" class="kill-button${isDead ? ' is-dead' : ''}" data-action="kill"
                    data-player="${esc(player.id)}" title="${isDead ? 'Wiederbeleben (entkoppelt)' : 'Als tot melden – koppelt die ganze Reihe'}">☠</button>
          </div>
          ${usedElsewhere(pick.species) ? '<span class="dupe-hint">⚠ Art schon gefangen</span>' : ''}
        </div>
      </div>
    </td>`;
}

/** Spiegelt team_ready() der API: ein Link braucht bei allen ein lebendes Pokémon.
 *
 * 'caught' allein reicht nicht - das steht schon, sobald einer etwas eingetragen
 * hat. Ohne diese Pruefung zeigten wir einen Stern, den die API mit 422 ablehnt.
 */
function teamReady(row) {
  const picks = Object.values(row.picks || {});
  if (row.outcome !== 'caught' || !picks.length) return false;
  return picks.every((pick) => (pick.species || (pick.name || '').trim()) && pick.status !== 'dead');
}

/** Nur vollstaendig gefangene Reihen lassen sich ins Team nehmen.
 *
 * Bei allen anderen bleibt der Platz leer - ein ausgegrauter Stern sah zu sehr
 * nach "anklickbar" aus. Der Platzhalter haelt die Ortsnamen in einer Flucht.
 */
function teamToggle(row) {
  if (!teamReady(row)) {
    return '<span class="team-toggle-spacer" aria-hidden="true"></span>';
  }
  return `<button type="button" class="team-toggle${row.in_team ? ' is-active' : ''}" data-action="team"
                  aria-pressed="${row.in_team}"
                  title="${row.in_team ? 'Aus dem Team nehmen' : 'Ins Team nehmen'}">${row.in_team ? '★' : '☆'}</button>`;
}

/** Was alle Zellen einer Zeile gemeinsam brauchen - einmal statt je Spieler. */
function rowContext(row, counts) {
  const location = catalogLocation(row.location_id);
  const encounters = location?.encounters || [];
  const byMethod = new Map();
  for (const entry of encounters) {
    const key = entry.methods.join(' / ');
    if (!byMethod.has(key)) byMethod.set(key, []);
    byMethod.get(key).push(entry);
  }
  return { counts, byMethod, known: new Set(encounters.map((entry) => entry.species)) };
}

function culpritOptions(selected) {
  return (
    option('', '–', !selected) +
    state.players.map((player) => option(player.id, player.name, selected === player.id)).join('') +
    option(NO_CULPRIT, 'Niemand', selected === NO_CULPRIT)
  );
}

function rowHtml(row, counts = speciesCounts()) {
  // row-caught bleibt bewusst ungestylt: gefangen und in der Box ist der Normalfall.
  const classes = [`row-${row.outcome}`];
  if (row.in_team) classes.push('row-team');

  const cell = rowContext(row, counts);
  const outcomeOptions = Object.entries(OUTCOME_LABELS)
    .map(([value, label]) => option(value, label, row.outcome === value))
    .join('');
  const responsibleOptions = culpritOptions(row.responsible_player);

  return `
    <tr data-row="${esc(row.id)}" class="${classes.join(' ')}">
      <td class="location">
        <div class="location-cell">
          ${teamToggle(row)}
          <strong>${esc(row.encounter)}${row.postgame ? '<span class="postgame-tag">Postgame</span>' : ''}</strong>
        </div>
      </td>
      ${state.players.map((player) => pickCell(row, player, cell)).join('')}
      <td class="col-meta"><select data-action="outcome" aria-label="Status">${outcomeOptions}</select></td>
      <td class="col-meta"><select data-action="responsible" aria-label="Schuldiger">${responsibleOptions}</select></td>
    </tr>`;
}

function renderTable() {
  if (!state.run) return;
  const sort = el.sortSelect.value;
  const head = (key, label, cls) =>
    `<th class="${cls} sortable${sort === key ? ' is-sorted' : ''}" data-sort="${key}"
         role="button" tabindex="0" title="Nach ${label} sortieren">${label}${sort === key ? ' ▾' : ''}</th>`;

  el.tableHead.innerHTML =
    head('order', 'Ort', 'col-location') +
    state.players.map((player) => `<th class="col-player">${esc(player.name)}</th>`).join('') +
    head('status', 'Status', 'col-meta') +
    '<th class="col-meta">Schuldiger</th>';
  const counts = speciesCounts();
  el.rows.innerHTML = sortedRows()
    .map((row) => rowHtml(row, counts))
    .join('');
  renderTeamCount();
}

/** Sortierte Kopie fuer die Anzeige - die Reihenfolge in state.run bleibt die der API. */
function sortedRows() {
  const rank = SORTERS[el.sortSelect.value] || SORTERS.order;
  return [...state.run.encounters].sort(
    (a, b) => rank(a) - rank(b) || a.order - b.order || a.id.localeCompare(b.id),
  );
}

function renderTeamCount() {
  const active = (state.run?.encounters || []).filter((row) => row.in_team).length;
  el.teamCount.textContent = `Team ${active}/${TEAM_SIZE}`;
  el.teamCount.classList.toggle('full', active >= TEAM_SIZE);
}

function replaceRow(row) {
  const index = state.run.encounters.findIndex((entry) => entry.id === row.id);
  if (index >= 0) state.run.encounters[index] = row;
  const tr = el.rows.querySelector(`tr[data-row="${row.id}"]`);
  if (!tr) return;
  // Fokus rausnehmen, bevor die Zeile ersetzt wird: ein fokussiertes <select>
  // feuert beim Zerstoeren sonst noch ein change-Event, das als weitere
  // Aenderung durchginge.
  if (document.activeElement && tr.contains(document.activeElement)) document.activeElement.blur();
  tr.outerHTML = rowHtml(row);
  renderTeamCount();
}

function renderCaps() {
  const current = catalog();
  const caps = current?.level_caps || [];
  const progress = state.run?.progress ?? 0;

  el.capList.innerHTML = caps
    .map((cap, index) => {
      const cls = index < progress ? 'cap done' : index === progress ? 'cap current' : 'cap';
      return `<div class="${cls}">
        <span class="cap-level">${esc(cap.cap)}</span>
        <span>${esc(cap.leader)}</span>
        <span class="cap-where">${esc(cap.place)}</span>
      </div>`;
    })
    .join('');

  const next = caps[progress];
  el.progressLabel.textContent = next ? `Nächster: ${next.leader} (Lv ${next.cap})` : 'Alles geschafft';
  el.progressDown.disabled = progress <= 0;
  el.progressUp.disabled = progress >= caps.length;
}

function renderRunPickers() {
  const games = state.games;
  const selectedGame = el.gameSelect.value || state.run?.game_id || games[0]?.id || '';

  el.gameSelect.innerHTML = games
    .map((game) => option(game.id, game.name, game.id === selectedGame))
    .join('');

  const runsForGame = state.runs.filter((run) => run.game_id === selectedGame);
  el.runSelect.innerHTML = runsForGame
    .map((run) => {
      const label = `${run.name}${run.status === 'completed' ? ' · abgeschlossen' : ''}`;
      return option(run.id, label, run.id === state.currentRunId);
    })
    .join('');

  const summary = state.runs.find((run) => run.id === state.currentRunId);
  el.runStatus.textContent = summary?.status === 'completed' ? 'Abgeschlossen' : 'Aktiv';
  el.runStatus.classList.toggle('completed', summary?.status === 'completed');
  el.lastUpdated.textContent = state.updatedAt ? `Stand: ${formatDate(state.updatedAt)}` : '';
  el.addLocationButton.disabled = !catalog();
}

// ------------------------------------------------------------ Dashboard ---

function renderStats(data) {
  const unassigned = data.unassigned_deaths + data.unassigned_failed_encounters;
  const cards = [
    ['Tode', data.total_deaths],
    ['Vergeigte Encounter', data.total_failed_encounters],
    ['Schuld gesamt', data.total_blame],
    ['Ohne Schuldigen', unassigned],
  ];
  el.statGrid.innerHTML = cards
    .map(
      ([label, value]) =>
        `<div class="stat-card"><span class="stat-label">${esc(label)}</span><span class="stat-value">${esc(value)}</span></div>`,
    )
    .join('');

  // Der Schuldigste steht oben - darum geht es hier ja.
  const ranked = [...(data.players || [])].sort(
    (a, b) => (data.blame_by_player[b.id] || 0) - (data.blame_by_player[a.id] || 0),
  );

  el.playerStats.innerHTML = ranked
    .map(
      (player) => `<tr>
        <td>${esc(player.name)}</td>
        <td>${esc(data.deaths_by_player[player.id] || 0)}</td>
        <td>${esc(data.failed_encounters_by_player[player.id] || 0)}</td>
        <td><strong>${esc(data.blame_by_player[player.id] || 0)}</strong></td>
      </tr>`,
    )
    .join('');

  el.runStats.innerHTML = data.runs
    .map(
      (run) => `<tr>
        <td><strong>${esc(run.name)}</strong><span class="subline">${esc(run.game_name || run.game_id)}</span></td>
        <td>${esc(run.deaths)}</td>
        <td>${esc(run.failed_encounters)}</td>
      </tr>`,
    )
    .join('');
}

function renderScopeOptions() {
  const scope = el.statScope.value || 'all';
  const options = [option('all', 'Alle Runs', false)];
  for (const game of state.games) options.push(option(`game:${game.id}`, game.name, false));
  for (const run of state.runs) options.push(option(`run:${run.id}`, run.name, false));
  el.statScope.innerHTML = options.join('');
  el.statScope.value = scope;
}

async function loadStats() {
  const scope = el.statScope.value || 'all';
  let query = '';
  if (scope.startsWith('game:')) query = `?game_id=${encodeURIComponent(scope.slice(5))}`;
  else if (scope.startsWith('run:')) query = `?run_id=${encodeURIComponent(scope.slice(4))}`;
  try {
    renderStats(await api(`/stats${query}`));
  } catch (error) {
    showError(`Statistik konnte nicht geladen werden: ${error.message}`);
  }
}

async function loadHistory() {
  try {
    const data = await api('/history?limit=60');
    el.historyRows.innerHTML = data.entries
      .map(
        (entry) => `<tr>
          <td>${formatDate(entry.at)}</td>
          <td>${esc(entry.summary)}</td>
          <td>${
            entry.undone
              ? '<span class="status-badge">zurückgenommen</span>'
              : // Ob sich ein Eintrag zuruecknehmen laesst, entscheidet die API.
                // Fehlt das Feld (aeltere API), gilt die Liste aus 'rules'.
                (entry.undoable ?? UNDOABLE_ACTIONS.includes(entry.action))
                ? `<button type="button" data-undo="${esc(entry.id)}">Rückgängig</button>`
                : ''
          }</td>
        </tr>`,
      )
      .join('');
  } catch (error) {
    showError(`Historie konnte nicht geladen werden: ${error.message}`);
  }
}

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
  el.gameSelect.value = data.game_id;
  renderRunPickers();
  renderCaps();
  renderTable();
  updateHash();
}

function updateHash() {
  if (!state.run) return;
  const parts = [`game=${encodeURIComponent(state.run.game_id)}`, `run=${encodeURIComponent(state.run.run_id)}`];
  if (state.view !== 'table') parts.push(`view=${state.view}`);
  const next = `#${parts.join('&')}`;
  if (window.location.hash !== next) window.history.replaceState(null, '', next);
}

function setView(view) {
  state.view = view;
  document.querySelectorAll('.view-button').forEach((button) => button.classList.toggle('active', button.dataset.view === view));
  document.querySelectorAll('.view').forEach((section) => { section.hidden = section.id !== `${view}-view`; });
  if (view === 'dashboard') {
    renderScopeOptions();
    loadStats();
  }
  if (view === 'history') loadHistory();
  updateHash();
}

// -------------------------------------------------------- Interaktionen ---

function rowOf(target) {
  const tr = target.closest('tr[data-row]');
  if (!tr) return null;
  return state.run.encounters.find((row) => row.id === tr.dataset.row) || null;
}

async function patchRow(rowId, body, query = '') {
  const updated = await write(() =>
    api(`/runs/${encodeURIComponent(state.currentRunId)}/encounters/${encodeURIComponent(rowId)}${query}`, {
      method: 'PATCH',
      body,
    }),
  );
  if (updated) replaceRow(updated);
  return updated;
}

/** Schreibt nur, wenn sich wirklich etwas aendert - schluckt Phantom-Events. */
async function patchPick(row, playerId, changes, query = '') {
  const pick = row.picks[playerId] || {};
  const differs = Object.entries(changes).some(([key, value]) => (pick[key] ?? null) !== (value ?? null));
  if (!differs) {
    replaceRow(row);
    return null;
  }
  return patchRow(row.id, { picks: { [playerId]: changes } }, query);
}

async function handleSpeciesChange(row, playerId, select) {
  const value = select.value;
  const location = catalogLocation(row.location_id);

  if (value === '__keep__') return;

  if (value === '__custom__') {
    const entered = window.prompt('Pokémon eintragen:', row.picks[playerId]?.name || '');
    if (entered === null) {
      replaceRow(row);
      return;
    }
    await patchPick(row, playerId, { species: null, name: entered.trim() }, '?force=true');
    return;
  }

  if (value === '') {
    await patchPick(row, playerId, { species: null, name: '' });
    return;
  }

  if (value === '__lost__') {
    // Wer den Encounter auf "verloren" setzt, hat ihn vergeigt - das ist der Schuldige.
    const body = { picks: { [playerId]: { species: null, name: LOST_LABEL } } };
    if (!row.responsible_player) body.responsible_player = playerId;
    await patchRow(row.id, body);
    return;
  }

  const entry = (location?.encounters || []).find((candidate) => candidate.species === value);
  await patchPick(row, playerId, { species: value, name: entry ? entry.name : value });
}

// Die API verlangt bei Tod und verlorenem Encounter einen Schuldigen - sonst
// faellt der Vorfall aus der Statistik. Also gleich hier abfragen.
let culpritResolve = null;

function askCulprit(row) {
  el.culpritQuestion.textContent = `Wer ist schuld an „${row.encounter}“?`;
  el.culpritSelect.innerHTML =
    state.players.map((player) => option(player.id, player.name, false)).join('') +
    option(NO_CULPRIT, 'Niemand – keiner war schuld', false);
  // returnValue ueberlebt das Schliessen: ohne Reset gilt ein frueheres "ok"
  // beim naechsten Abbrechen weiter und wir schreiben einen Schuldigen, den
  // niemand bestaetigt hat.
  el.culpritDialog.returnValue = '';
  el.culpritDialog.showModal();
  return new Promise((resolve) => {
    culpritResolve = resolve;
  });
}

el.culpritDialog.addEventListener('close', () => {
  const resolve = culpritResolve;
  culpritResolve = null;
  if (resolve) resolve(el.culpritDialog.returnValue === 'ok' ? el.culpritSelect.value : null);
});

async function handleOutcomeChange(row, outcome) {
  if ((outcome === 'failed' || outcome === 'dead') && !row.responsible_player) {
    const culprit = await askCulprit(row);
    if (culprit === null) {
      replaceRow(row); // abgebrochen - Auswahl zuruecksetzen
      return;
    }
    await patchRow(row.id, { outcome, responsible_player: culprit });
    return;
  }
  await patchRow(row.id, { outcome });
}

async function handleKill(row, playerId) {
  const pick = row.picks[playerId];
  if (pick?.status === 'dead') {
    // Wiederbeleben ist immer eine Ausnahme - deshalb ohne Kopplung.
    await patchRow(row.id, { picks: { [playerId]: { status: 'alive' } } }, '?couple=false');
    return;
  }
  const body = { picks: { [playerId]: { status: 'dead' } } };
  if (!row.responsible_player) body.responsible_player = playerId;
  await patchRow(row.id, body);
}

el.rows.addEventListener('change', async (event) => {
  const target = event.target;
  // Events von Elementen, die gerade aus dem DOM geflogen sind, gehoeren zu
  // einer schon gespeicherten Aenderung - sonst schreiben wir sie doppelt.
  if (!target.isConnected) return;
  const row = rowOf(target);
  if (!row) return;
  const action = target.dataset.action;

  if (action === 'species') await handleSpeciesChange(row, target.dataset.player, target);
  else if (action === 'outcome') await handleOutcomeChange(row, target.value);
  else if (action === 'responsible') await patchRow(row.id, { responsible_player: target.value || null });
});

el.rows.addEventListener('click', async (event) => {
  const target = event.target.closest('[data-action]');
  if (!target || !target.isConnected) return;
  const row = rowOf(target);
  if (!row) return;

  if (target.dataset.action === 'kill') await handleKill(row, target.dataset.player);
  else if (target.dataset.action === 'team') await patchRow(row.id, { in_team: !row.in_team });
});

el.gameSelect.addEventListener('change', async () => {
  const runsForGame = state.runs.filter((run) => run.game_id === el.gameSelect.value);
  renderRunPickers();
  if (runsForGame.length) await loadRun(runsForGame[0].id);
  else {
    // Auch die Run-ID loesen, sonst holt der naechste Poll den Run des vorigen
    // Spiels zurueck und ueberschreibt die Auswahl mitten in der Bedienung.
    state.run = null;
    state.currentRunId = null;
    el.rows.innerHTML = '<tr><td colspan="9">Für dieses Spiel gibt es noch keinen Run.</td></tr>';
    el.capList.innerHTML = '';
    el.progressLabel.textContent = '–';
  }
});

el.runSelect.addEventListener('change', () => loadRun(el.runSelect.value));

function setSort(key) {
  if (!SORTERS[key]) return;
  el.sortSelect.value = key;
  window.localStorage.setItem(SORT_KEY, key);
  renderTable();
}

el.sortSelect.addEventListener('change', () => setSort(el.sortSelect.value));

el.tableHead.addEventListener('click', (event) => {
  const header = event.target.closest('[data-sort]');
  if (header) setSort(header.dataset.sort);
});

el.tableHead.addEventListener('keydown', (event) => {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  const header = event.target.closest('[data-sort]');
  if (!header) return;
  event.preventDefault();
  setSort(header.dataset.sort);
});
el.statScope.addEventListener('change', loadStats);

document.querySelectorAll('.view-button').forEach((button) => {
  button.addEventListener('click', () => setView(button.dataset.view));
});

el.historyRows.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-undo]');
  if (!button) return;
  const done = await write(() => api(`/history/${encodeURIComponent(button.dataset.undo)}/undo`, { method: 'POST' }));
  if (done) {
    await loadRun(state.currentRunId);
    await loadHistory();
  }
});

async function changeProgress(delta) {
  if (!state.run) return;
  const caps = catalog()?.level_caps || [];
  const next = Math.min(Math.max(state.run.progress + delta, 0), caps.length);
  if (next === state.run.progress) return;
  const updated = await write(() =>
    api(`/runs/${encodeURIComponent(state.currentRunId)}`, { method: 'PATCH', body: { progress: next } }),
  );
  if (updated) {
    state.run.progress = updated.progress;
    renderCaps();
    renderTable();
  }
}

el.progressUp.addEventListener('click', () => changeProgress(1));
el.progressDown.addEventListener('click', () => changeProgress(-1));

// --------------------------------------------------------------- Dialoge --

document.querySelectorAll('dialog [data-close]').forEach((button) => {
  button.addEventListener('click', () => button.closest('dialog').close());
});

el.newRunButton.addEventListener('click', () => {
  el.runGame.innerHTML = state.games
    .map((game) => option(game.id, game.name, game.id === el.gameSelect.value))
    .join('');
  el.runName.value = `Run ${state.runs.length + 1}`;
  el.runDialog.showModal();
});

el.runForm.addEventListener('submit', async () => {
  const created = await write(() =>
    api('/runs', {
      method: 'POST',
      body: {
        name: el.runName.value.trim(),
        game_id: el.runGame.value,
        prefill: el.runPrefill.checked,
        include_postgame: el.runPostgame.checked,
        make_current: true,
      },
    }),
  );
  if (created) {
    await loadRuns();
    await loadRun(created.id);
  }
});

el.addLocationButton.addEventListener('click', () => {
  const current = catalog();
  if (!current || !state.run) return;
  const present = new Set(state.run.encounters.map((row) => row.location_id).filter(Boolean));
  const missing = current.locations.filter((location) => !present.has(location.id));
  if (!missing.length) {
    showError('Alle Orte dieses Spiels stehen bereits in der Tabelle.');
    return;
  }
  el.locationSelect.innerHTML = missing
    .map((location) => option(location.id, `${location.name}${location.postgame ? ' (Postgame)' : ''}`, false))
    .join('');
  el.locationDialog.showModal();
});

el.locationForm.addEventListener('submit', async () => {
  const location = catalogLocation(el.locationSelect.value);
  if (!location) return;
  const created = await write(() =>
    api(`/runs/${encodeURIComponent(state.currentRunId)}/encounters`, {
      method: 'POST',
      body: {
        id: location.id,
        location_id: location.id,
        order: location.order,
        encounter: location.name,
        postgame: Boolean(location.postgame),
        picks: Object.fromEntries(state.players.map((player) => [player.id, { species: null, name: '' }])),
      },
    }),
  );
  if (created) await loadRun(state.currentRunId);
});

// --------------------------------------------------------- Typenrechner ---

// Reihenfolge wie im Spiel, nicht alphabetisch - so liegt das Raster so, wie man
// es aus jedem Pokedex kennt.
const TYPE_NAMES = {
  normal: 'Normal', fighting: 'Kampf', flying: 'Flug',
  poison: 'Gift', ground: 'Boden', rock: 'Gestein',
  bug: 'Käfer', ghost: 'Geist', steel: 'Stahl',
  fire: 'Feuer', water: 'Wasser', grass: 'Pflanze',
  electric: 'Elektro', psychic: 'Psycho', ice: 'Eis',
  dragon: 'Drache', dark: 'Unlicht', fairy: 'Fee',
};

const TYPE_ORDER = Object.keys(TYPE_NAMES);

/** Heutige Tabelle (ab Generation 6): angreifender Typ -> Abweichungen von 1x. */
const MODERN_CHART = {
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

/**
 * Aeltere Generationen als Abweichung von der heutigen Tabelle. Beide Listen sind
 * aus den past_damage_relations der PokeAPI abgeleitet und nicht aus dem Kopf: es
 * sind genau vier Aenderungen bis Generation 1 und zwei bis Generation 5, alles
 * andere ist seit jeher gleich. `without` haelt die Typen heraus, die es damals
 * noch nicht gab - sie duerfen weder waehlbar sein noch im Ergebnis auftauchen.
 */
const GENERATIONS = [
  {
    id: 'gen1',
    label: 'Generation 1 (Rot/Blau/Gelb)',
    without: ['steel', 'dark', 'fairy'],
    // Geist gegen Psycho ist der beruehmte Programmierfehler der ersten Spiele:
    // gedacht war sehr effektiv, im Spiel passierte gar nichts.
    changes: { poison: { bug: 2 }, bug: { poison: 2 }, ghost: { psychic: 0 }, ice: { fire: 1 } },
  },
  {
    id: 'gen2',
    label: 'Generationen 2–5 (bis Schwarz 2/Weiß 2)',
    without: ['fairy'],
    changes: { ghost: { steel: 0.5 }, dark: { steel: 0.5 } },
  },
  {
    id: 'gen6',
    label: 'Generation 6+ (ab X/Y)',
    without: [],
    changes: {},
  },
];

// Alle Faktoren sind Zweierpotenzen und damit exakt vergleichbar - gerundet wird nichts.
const DEFENSE_BUCKETS = [
  { factor: 4, heading: 'Nimmt 4× Schaden von', tone: 'worse' },
  { factor: 2, heading: 'Nimmt 2× Schaden von', tone: 'bad' },
  { factor: 1, heading: 'Nimmt 1× Schaden von', tone: 'plain' },
  { factor: 0.5, heading: 'Nimmt ½× Schaden von', tone: 'good' },
  { factor: 0.25, heading: 'Nimmt ¼× Schaden von', tone: 'better' },
  { factor: 0, heading: 'Nimmt 0× Schaden von', tone: 'best' },
];

function generation() {
  return GENERATIONS.find((entry) => entry.id === state.generation) || GENERATIONS[1];
}

function generationTypes(gen) {
  return TYPE_ORDER.filter((type) => !gen.without.includes(type));
}

/** Angreifender Typ -> Schaden gegen diese Typenkombination. */
function defenseFactors(gen, types) {
  const factors = {};
  for (const attack of generationTypes(gen)) {
    const row = { ...MODERN_CHART[attack], ...gen.changes[attack] };
    factors[attack] = types.reduce((factor, type) => factor * (row[type] ?? 1), 1);
  }
  return factors;
}

function typeChip(type) {
  return `<span class="type-chip type-${esc(type)}">${esc(TYPE_NAMES[type])}</span>`;
}

function defenseHtml(gen, types) {
  if (!types.length) {
    return '<p class="muted">Wähle links einen Typ – oder zwei für eine Kombination.</p>';
  }
  const factors = defenseFactors(gen, types);
  const order = generationTypes(gen);
  return DEFENSE_BUCKETS.map((bucket) => {
    const hits = order.filter((type) => factors[type] === bucket.factor);
    if (!hits.length) return '';
    return `
      <div class="defense-group ${esc(bucket.tone)}">
        <h3>${esc(bucket.heading)}</h3>
        <div class="type-chips">${hits.map(typeChip).join('')}</div>
      </div>`;
  }).join('');
}

function renderTypeCalculator() {
  const gen = generation();
  const available = generationTypes(gen);
  // Ein Generationswechsel kann die Auswahl ungueltig machen (Fee in Platin).
  state.typeSelection = state.typeSelection.filter((type) => available.includes(type));

  el.typeGeneration.innerHTML = GENERATIONS.map((entry) => option(entry.id, entry.label, entry.id === gen.id)).join('');
  el.typeGrid.innerHTML = available.map((type) => {
    const active = state.typeSelection.includes(type);
    return `<button type="button" class="type-button type-${esc(type)}${active ? ' is-active' : ''}"
      data-type="${esc(type)}" aria-pressed="${active ? 'true' : 'false'}"
      ><span class="type-mark">${active ? '✓' : ''}</span>${esc(TYPE_NAMES[type])}</button>`;
  }).join('');
  el.typeReset.disabled = !state.typeSelection.length;
  el.defenseResult.innerHTML = defenseHtml(gen, state.typeSelection);
}

/**
 * Beim dritten Typ faellt der aelteste heraus, statt den Klick zu schlucken -
 * eine tote Schaltflaeche liest sich sonst wie ein Fehler.
 */
function toggleType(type) {
  const selection = state.typeSelection;
  const at = selection.indexOf(type);
  if (at >= 0) selection.splice(at, 1);
  else selection.push(type);
  while (selection.length > MAX_TYPES) selection.shift();
  renderTypeCalculator();
}

el.typeGrid.addEventListener('click', (event) => {
  const button = event.target.closest('button[data-type]');
  if (button) toggleType(button.dataset.type);
});

el.typeGeneration.addEventListener('change', () => {
  state.generation = el.typeGeneration.value;
  window.localStorage.setItem(GENERATION_KEY, state.generation);
  renderTypeCalculator();
});

el.typeReset.addEventListener('click', () => {
  state.typeSelection = [];
  renderTypeCalculator();
});

// -------------------------------------------------------------- Polling ---

function isEditing() {
  const active = document.activeElement;
  return Boolean(active && active.closest('#encounter-rows, dialog'));
}

async function poll() {
  if (document.hidden || pendingWrites > 0 || isEditing()) return;
  try {
    const seen = state.updatedAt;
    // Ueber loadRuns() statt eigenem Fetch: nur so greift der Rueckfall auf den
    // aktuellen Run des Servers, wenn der eigene inzwischen geloescht wurde.
    await loadRuns();
    if (state.updatedAt === seen) return;
    // Nur laden, was zum gewaehlten Spiel gehoert - sonst zieht der Poll die
    // Ansicht auf ein Spiel zurueck, das gerade niemand sehen will.
    const current = state.runs.find((run) => run.id === state.currentRunId);
    const selectedGame = el.gameSelect.value;
    if (current && (!selectedGame || current.game_id === selectedGame)) await loadRun(current.id);
    if (state.view === 'dashboard') await loadStats();
    if (state.view === 'history') await loadHistory();
  } catch {
    // Ein verpasster Poll ist kein Fehler, der die Seite stoeren soll.
  }
}

// ----------------------------------------------------------------- Start --

async function init() {
  try {
    const savedSort = window.localStorage.getItem(SORT_KEY);
    if (savedSort && SORTERS[savedSort]) el.sortSelect.value = savedSort;

    state.games = await api('/games');
    await loadRuns();

    const hash = new URLSearchParams(window.location.hash.slice(1));
    const wantedRun = hash.get('run');
    if (wantedRun && state.runs.some((run) => run.id === wantedRun)) state.currentRunId = wantedRun;

    await loadRun(state.currentRunId);

    const wantedView = hash.get('view');
    if (VIEWS.includes(wantedView)) setView(wantedView);

    window.setInterval(poll, POLL_INTERVAL_MS);
  } catch (error) {
    showError(`Die Tabelle konnte nicht geladen werden: ${error.message}`);
  }
}

// Der Rechner haengt an keinem Run und keinem Katalog - er steht deshalb auch
// dann noch, wenn init() an der API scheitert.
state.generation = window.localStorage.getItem(GENERATION_KEY) || DEFAULT_GENERATION;
renderTypeCalculator();
init();
