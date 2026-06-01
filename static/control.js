let currentRace = null;
let currentIndex = 0;
let currentTotalEvents = 0;
let currentEvent = null;
let autoPlaying = false;
let autoTimer = null;
let currentOdds = null;

const DEFAULT_AUTO_INTERVAL_MS = 2500;
const MIN_AUTO_INTERVAL_MS = 500;

const BET_LABELS = {
  win: '単勝',
  place: '複勝',
  exacta: '連単',
  quinella: '連複',
  trifecta: '三連単',
  perfect: 'パーフェクト',
};

const BET_TARGET_COUNTS = {
  win: 1,
  place: 1,
  exacta: 2,
  quinella: 2,
  trifecta: 3,
};

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

function pct(value) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

function oddsText(value) {
  return `${Number(value || 0).toFixed(1)}倍`;
}

function oddsByName(name) {
  if (!currentOdds) return null;
  return currentOdds.tanks.find(t => t.name === name) || null;
}

function oddsMatchesRace(odds, race) {
  return !!odds && !!race && odds.rank === race.rank && odds.program === race.program;
}

function clearOddsView(message = '現在のレースに対応するオッズは未計算です。') {
  currentOdds = null;
  document.getElementById('oddsStatus').textContent = message;
  document.getElementById('oddsSummary').innerHTML = '';
  document.getElementById('oddsTable').innerHTML = '';
  renderBetPreview();
}

function availableTanks() {
  return currentRace?.tanks || currentOdds?.tanks || [];
}

function targetCountForBet(type) {
  if (type === 'perfect') return availableTanks().length || 6;
  return BET_TARGET_COUNTS[type] || 1;
}

function betPositionLabel(type, index) {
  if (type === 'win' || type === 'place') return '対象';
  if (type === 'quinella') return `${index + 1}台目`;
  return `${index + 1}着`;
}

function getSelectedTargets() {
  return Array.from(document.querySelectorAll('.bet-target')).map(select => select.value).filter(Boolean);
}

function hasDuplicateTargets(targets) {
  return new Set(targets).size !== targets.length;
}

function betTargetKey(type, targets) {
  const selected = type === 'quinella' ? [...targets].sort() : targets;
  return selected.join('|');
}

function selectedBetOdds() {
  if (!currentOdds) return null;
  const type = document.getElementById('betType').value;
  const targets = getSelectedTargets();

  if (targets.length !== targetCountForBet(type) || hasDuplicateTargets(targets)) return null;
  if (type === 'win') return oddsByName(targets[0])?.winOdds ?? null;
  if (type === 'place') return oddsByName(targets[0])?.placeOdds ?? null;
  return currentOdds.comboOdds?.[type]?.[betTargetKey(type, targets)] ?? 99.9;
}

function formatBetTargets(type, targets) {
  if (!targets.length) return '';
  if (type === 'quinella') return targets.join(' + ');
  return targets.join(' → ');
}

function updateBetTargetOptions() {
  const betType = document.getElementById('betType').value;
  const betTargets = document.getElementById('betTargets');
  const betTargetLabel = document.getElementById('betTargetLabel');
  const tanks = availableTanks();
  const previousTargets = getSelectedTargets();
  const count = targetCountForBet(betType);

  betTargets.innerHTML = Array.from({length: count}, (_, index) => {
    const preferred = previousTargets[index];
    const selectedName = tanks.some(t => t.name === preferred) ? preferred : tanks[index % Math.max(1, tanks.length)]?.name;
    const options = tanks.map(t => `<option value="${t.name}" ${t.name === selectedName ? 'selected' : ''}>${t.name}</option>`).join('');
    return `
      <label class="bet-target-select">${betPositionLabel(betType, index)}
        <select class="bet-target" data-position="${index}">${options}</select>
      </label>
    `;
  }).join('');
  betTargetLabel.classList.toggle('muted-control', tanks.length === 0);
  renderBetPreview();
}

function selectedBet() {
  const targets = getSelectedTargets();
  return {
    type: document.getElementById('betType').value,
    target: targets.join('|'),
    targets,
    stake: Number(document.getElementById('betStake').value || 0),
  };
}

function renderBetPreview() {
  const preview = document.getElementById('betOddsPreview');
  if (!preview) return;
  const type = document.getElementById('betType').value;
  const targets = getSelectedTargets();
  if (!currentOdds) {
    preview.textContent = 'オッズ計算後に選択中のオッズを表示します。';
    return;
  }
  if (targets.length !== targetCountForBet(type)) {
    preview.textContent = '対象戦車を選択してください。';
    return;
  }
  if (hasDuplicateTargets(targets)) {
    preview.textContent = '同じ戦車を重複して選べません。';
    return;
  }
  preview.textContent = `${BET_LABELS[type]} ${formatBetTargets(type, targets)} / ${oddsText(selectedBetOdds())}`;
}

function renderOdds(odds) {
  currentOdds = odds;
  if (!odds) return;

  document.getElementById('oddsStatus').textContent =
    `${odds.rank}級 ${odds.programLabel} / ${odds.simulations}回 / sim seed ${odds.seed}`;
  document.getElementById('oddsSummary').innerHTML = `
    <div class="odds-chip">連単・連複・三連単・パーフェクト対応</div>
  `;
  document.getElementById('oddsTable').innerHTML = `
    <table>
      <thead>
        <tr>
          <th>戦車名</th><th>タイプ</th><th>勝率</th><th>3着内率</th><th>リタイア率</th><th>単勝</th><th>複勝</th>
        </tr>
      </thead>
      <tbody>
        ${odds.tanks.map(t => `
          <tr>
            <td>${t.name}</td>
            <td>${t.style}</td>
            <td>${pct(t.winRate)}</td>
            <td>${pct(t.top3Rate)}</td>
            <td>${pct(t.retirementRate)}</td>
            <td>${oddsText(t.winOdds)}</td>
            <td>${oddsText(t.placeOdds)}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
  updateBetTargetOptions();
}

function renderBetResult(result) {
  const targets = result.targets || [];
  const targetText = targets.length ? ` / ${formatBetTargets(result.type, targets)}` : '';
  const hitText = result.hit ? '的中' : '不的中';
  document.getElementById('betResult').innerHTML = `
    <strong>${hitText}</strong> ${BET_LABELS[result.type]}${targetText}<br>
    掛け金 ${result.stake} / オッズ ${oddsText(result.odds)} / 払戻額 ${result.payout} / 利益 ${result.profit}
  `;
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
  const raceOdds = state.odds || currentRace.odds || null;
  if (oddsMatchesRace(raceOdds, currentRace)) {
    renderOdds(raceOdds);
  } else if (currentOdds && !oddsMatchesRace(currentOdds, currentRace)) {
    clearOddsView();
  }

  document.getElementById('currentEvent').textContent =
    `[${currentEventNumber(state)}/${currentTotalEvents}] ${currentEvent.title || '実況'}\n${currentEvent.text || ''}`;

  const tankList = document.getElementById('tankList');
  tankList.innerHTML = currentRace.tanks.map(t => `
    <div class="tank-row">
      <strong>${t.name}</strong> / ${t.style} / ${t.rank}級 / 車格${t.grade_points}<br>
      機${t.mobility} 操${t.handling} 装${t.armor} 火${t.firepower} 安${t.stability} 駆${t.drive} 弾${t.ammo} HP${t.hp}
      ${oddsByName(t.name) ? `<br>単勝 ${oddsText(oddsByName(t.name).winOdds)} / 複勝 ${oddsText(oddsByName(t.name).placeOdds)}` : ''}
    </div>
  `).join('');
  updateBetTargetOptions();

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

document.getElementById('calculateOdds').addEventListener('click', async () => {
  const button = document.getElementById('calculateOdds');
  button.disabled = true;
  document.getElementById('oddsStatus').textContent = 'オッズ計算中...';
  const rank = document.getElementById('rank').value;
  const program = document.getElementById('program').value;
  const simulations = document.getElementById('oddsSimulations').value;
  const result = await postJSON('/api/calculate_odds', {rank, program, simulations});
  button.disabled = false;
  if (!result.ok) {
    document.getElementById('oddsStatus').textContent = result.error || 'オッズ計算に失敗しました';
    return;
  }
  renderOdds(result.odds);
  await refresh();
});

document.getElementById('betType').addEventListener('change', updateBetTargetOptions);
document.getElementById('betTargets').addEventListener('change', renderBetPreview);
document.getElementById('betStake').addEventListener('input', renderBetPreview);

document.getElementById('evaluateBet').addEventListener('click', async () => {
  if (!currentRace) {
    document.getElementById('betResult').textContent = '先にレースを生成してください。';
    return;
  }
  if (!currentOdds) {
    document.getElementById('betResult').textContent = '先にオッズを計算してください。';
    return;
  }
  if (currentIndex < currentTotalEvents - 1) {
    document.getElementById('betResult').textContent = 'レース終了後に払戻計算できます。';
    return;
  }
  const bet = selectedBet();
  if (bet.targets.length !== targetCountForBet(bet.type)) {
    document.getElementById('betResult').textContent = '対象戦車を選択してください。';
    return;
  }
  if (hasDuplicateTargets(bet.targets)) {
    document.getElementById('betResult').textContent = '同じ戦車を重複して選べません。';
    return;
  }
  const result = await postJSON('/api/evaluate_bet', {bet});
  if (!result.ok) {
    document.getElementById('betResult').textContent = result.error || '払戻計算に失敗しました';
    return;
  }
  renderBetResult(result.result);
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
updateBetTargetOptions();
refresh();
