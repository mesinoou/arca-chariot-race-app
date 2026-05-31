let currentRace = null;
let currentIndex = 0;
let currentTotalEvents = 0;
let currentEvent = null;
let autoPlaying = false;
let autoTimer = null;

const DEFAULT_AUTO_INTERVAL_MS = 2500;
const MIN_AUTO_INTERVAL_MS = 500;

async function postJSON(url, body = {}) {
  const res = await fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  return await res.json();
}

function stateIndex(state) {
  return state.current_index ?? state.index ?? 0;
}

function stateTotalEvents(state) {
  return state.total_events ?? state.race?.events?.length ?? 0;
}

function stateCurrentEvent(state) {
  const index = stateIndex(state);
  return state.event || state.race?.events?.[index] || {};
}

function currentEventNumber(state) {
  return state.current_event_number ?? (stateIndex(state) + 1);
}

function isLastEvent(state) {
  const totalEvents = stateTotalEvents(state);
  return state.is_last_event ?? (totalEvents > 0 && stateIndex(state) >= totalEvents - 1);
}

function getAutoIntervalMs() {
  const input = document.getElementById('autoInterval');
  const rawValue = Number(input.value || DEFAULT_AUTO_INTERVAL_MS);
  const safeValue = Number.isFinite(rawValue) ? rawValue : DEFAULT_AUTO_INTERVAL_MS;
  return Math.max(MIN_AUTO_INTERVAL_MS, Math.round(safeValue));
}

function eventDelayMs(event) {
  const baseDelay = getAutoIntervalMs();
  const eventType = event?.type || '';
  if (eventType === 'accident' || eventType === 'goal' || eventType === 'round_start') {
    return Math.round(baseDelay * 1.45);
  }
  return baseDelay;
}

function setAutoStatus(text) {
  document.getElementById('autoStatus').textContent = text;
}

function updateAutoControls(updateStatus = true) {
  const startButton = document.getElementById('autoStart');
  const stopButton = document.getElementById('autoStop');
  const canPlay = !!currentRace && currentTotalEvents > 0 && currentIndex < currentTotalEvents - 1;
  startButton.disabled = autoPlaying || !canPlay;
  stopButton.disabled = !autoPlaying;

  if (!updateStatus) return;

  if (!autoPlaying && !currentRace) {
    setAutoStatus('自動再生: レース未生成');
  } else if (!autoPlaying && currentRace && !canPlay) {
    setAutoStatus('自動再生: 最終イベントです');
  } else if (!autoPlaying) {
    setAutoStatus('自動再生: 停止中');
  }
}

function stopAutoPlay(message = '自動再生: 停止中') {
  autoPlaying = false;
  if (autoTimer !== null) {
    clearTimeout(autoTimer);
    autoTimer = null;
  }
  setAutoStatus(message);
  updateAutoControls(false);
}

function scheduleAutoPlay(event = currentEvent) {
  if (!autoPlaying) return;
  if (autoTimer !== null) {
    clearTimeout(autoTimer);
  }
  autoTimer = setTimeout(runAutoStep, eventDelayMs(event));
}

async function runAutoStep() {
  if (!autoPlaying) return;

  const state = await postJSON('/api/next');
  if (!autoPlaying) return;

  if (!state.ok) {
    stopAutoPlay('自動再生: 停止中');
    return;
  }

  renderControl(state);
  if (isLastEvent(state)) {
    stopAutoPlay('自動再生: 最終イベントで停止');
    return;
  }

  scheduleAutoPlay(stateCurrentEvent(state));
}

function startAutoPlay() {
  if (autoPlaying) return;
  if (!currentRace || currentTotalEvents <= 0) {
    setAutoStatus('自動再生: レース未生成');
    updateAutoControls();
    return;
  }
  if (currentIndex >= currentTotalEvents - 1) {
    setAutoStatus('自動再生: 最終イベントです');
    updateAutoControls();
    return;
  }

  autoPlaying = true;
  setAutoStatus(`自動再生: 再生中 (${getAutoIntervalMs()}ms)`);
  updateAutoControls();
  scheduleAutoPlay(currentEvent);
}

function renderControl(state) {
  if (!state || !state.race) return;
  currentRace = state.race;
  currentIndex = stateIndex(state);
  currentTotalEvents = stateTotalEvents(state);
  currentEvent = stateCurrentEvent(state);

  document.getElementById('currentEvent').textContent =
    `[${currentEventNumber(state)}/${currentTotalEvents}] ${currentEvent.title || '実況'}\n${currentEvent.text || ''}`;

  const tankList = document.getElementById('tankList');
  tankList.innerHTML = currentRace.tanks.map(t => `
    <div class="tank-row">
      <strong>${t.name}</strong> / ${t.style} / ${t.rank}級 / 車格${t.grade_points}<br>
      機${t.mobility} 操${t.handling} 装${t.armor} 火${t.firepower} 安${t.stability} 駆${t.drive} 弾${t.ammo} HP${t.hp}
    </div>
  `).join('');

  const eventList = document.getElementById('eventList');
  eventList.innerHTML = currentRace.events.map((e, i) => `
    <div class="event-row ${i === currentIndex ? 'active' : ''}">
      ${i + 1}. ${e.title || '実況'}<br><small>${e.text || ''}</small>
    </div>
  `).join('');

  if (autoPlaying && isLastEvent(state)) {
    stopAutoPlay('自動再生: 最終イベントで停止');
  } else {
    updateAutoControls();
  }
}

async function refresh() {
  const state = await fetch('/api/state').then(r => r.json());
  if (state.ok) renderControl(state);
}

document.getElementById('newRace').addEventListener('click', async () => {
  const rank = document.getElementById('rank').value;
  const program = document.getElementById('program').value;
  const seed = document.getElementById('seed').value;
  const state = await postJSON('/api/new_race', {rank, program, seed});
  renderControl(state);
});

document.getElementById('nextEvent').addEventListener('click', async () => {
  const state = await postJSON('/api/next');
  await refresh();
});

document.getElementById('prevEvent').addEventListener('click', async () => {
  const state = await postJSON('/api/prev');
  await refresh();
});

document.getElementById('resetView').addEventListener('click', async () => {
  const state = await postJSON('/api/reset_view');
  await refresh();
});

document.getElementById('autoStart').addEventListener('click', startAutoPlay);

document.getElementById('autoStop').addEventListener('click', () => {
  stopAutoPlay('自動再生: 停止中');
});

document.getElementById('autoInterval').addEventListener('change', () => {
  const input = document.getElementById('autoInterval');
  input.value = getAutoIntervalMs();
  if (autoPlaying) {
    setAutoStatus(`自動再生: 再生中 (${getAutoIntervalMs()}ms)`);
  }
});

updateAutoControls();
refresh();
