const TYPEWRITER_SPEED_MS = 28;
const DICE_ROLL_DURATION_MS = 900;
const DICE_ROLL_TICK_MS = 55;
const CINEMA_EMPHASIS_CLASSES = [
  'cinema-log--accident',
  'cinema-log--hit',
  'cinema-log--crit',
  'cinema-log--goal',
  'cinema-log--success',
];
const DICE_RESULT_CLASSES = [
  'dice-panel--success',
  'dice-panel--failure',
  'dice-panel--crit',
  'dice-panel--fumble',
];
const TRACK_AREAS = ['後列', '中列', '前列'];
const BOTTOM_MODE_CLASSES = ['mode-normal', 'mode-opposed', 'mode-cutin', 'normal-has-dice'];
const DICE_TARGETS = {
  normal: {
    panel: 'normalDicePanel',
    label: 'normalDiceLabel',
    die1: 'normalDiceDie1',
    die2: 'normalDiceDie2',
    sum: 'normalDiceSum',
    formula: 'normalDiceFormula',
    bonus: 'normalDiceBonus',
    total: 'normalDiceTotal',
    targetLabel: 'normalDiceTargetLabel',
    target: 'normalDiceTarget',
    result: 'normalDiceResult',
  },
  active: {
    panel: 'activeDicePanel',
    label: 'activeDiceLabel',
    die1: 'activeDiceDie1',
    die2: 'activeDiceDie2',
    sum: 'activeDiceSum',
    formula: 'activeDiceFormula',
    bonus: 'activeDiceBonus',
    total: 'activeDiceTotal',
    targetLabel: 'activeDiceTargetLabel',
    target: 'activeDiceTarget',
    result: 'activeDiceResult',
  },
  passive: {
    panel: 'passiveDicePanel',
    label: 'passiveDiceLabel',
    die1: 'passiveDiceDie1',
    die2: 'passiveDiceDie2',
    sum: 'passiveDiceSum',
    formula: 'passiveDiceFormula',
    bonus: 'passiveDiceBonus',
    total: 'passiveDiceTotal',
    targetLabel: 'passiveDiceTargetLabel',
    target: 'passiveDiceTarget',
    result: 'passiveDiceResult',
  },
};

let lastIndex = -1;
let lastRaceKey = '';
let typewriterTimer = null;
let typewriterRunId = 0;
let diceRollTimer = null;
let diceRollStopTimer = null;
let diceRunId = 0;
let displayOdds = null;

function boardRanking(board) {
  const arr = Object.values(board || {});
  const areaRank = {'後列': 0, '中列': 1, '前列': 2};
  return arr.sort((a, b) => {
    if (!!a.retired !== !!b.retired) return a.retired ? 1 : -1;
    if (areaRank[b.area] !== areaRank[a.area]) return areaRank[b.area] - areaRank[a.area];
    if ((b.lead || 0) !== (a.lead || 0)) return (b.lead || 0) - (a.lead || 0);
    return (b.hp || 0) - (a.hp || 0);
  });
}

function escapeHtml(value) {
  return safeText(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function displayOddsForName(name) {
  return displayOdds?.tanks?.find(row => row.name === name) || null;
}

function tankCard(t, event) {
  const retiredClass = t.retired ? 'retired' : '';
  const highlight = t.highlight || '';
  const actorClass = t.name === event.actor ? 'is-actor' : '';
  const targetClass = t.name === event.target ? 'is-target' : '';
  return `
    <div class="tank-card ${highlight} ${retiredClass} ${actorClass} ${targetClass}" data-name="${escapeHtml(t.name)}">
      <div class="tank-card-head"><span class="tank-name">${escapeHtml(t.name)}</span><span class="tank-style">${escapeHtml(t.style)}</span></div>
      <div class="tank-stats">
        <div class="stat-pill"><span>HP</span><strong>${t.hp}/${t.maxHp}</strong></div>
        <div class="stat-pill"><span>安定</span><strong>${t.stability}</strong></div>
        <div class="stat-pill"><span>駆動</span><strong>${t.drive ?? '-'}</strong></div>
        <div class="stat-pill"><span>先行</span><strong>${t.lead}</strong></div>
      </div>
    </div>
  `;
}

function safeText(value) {
  if (value === null || value === undefined) return '';
  return String(value);
}

function setText(id, value) {
  document.getElementById(id).textContent = safeText(value);
}

function stopTypewriter() {
  typewriterRunId += 1;
  if (typewriterTimer !== null) {
    clearTimeout(typewriterTimer);
    typewriterTimer = null;
  }
}

function stopDiceRoll() {
  diceRunId += 1;
  if (diceRollTimer !== null) {
    clearInterval(diceRollTimer);
    diceRollTimer = null;
  }
  if (diceRollStopTimer !== null) {
    clearTimeout(diceRollStopTimer);
    diceRollStopTimer = null;
  }
}

function randomDie() {
  return Math.floor(Math.random() * 6) + 1;
}

function dicePairFromSum(dice) {
  const pairs = [];
  for (let d1 = 1; d1 <= 6; d1 += 1) {
    const d2 = dice - d1;
    if (d2 >= 1 && d2 <= 6) {
      pairs.push([d1, d2]);
    }
  }
  return pairs.length ? pairs[Math.floor(pairs.length / 2)] : [1, 1];
}

function finalDiceValues(diceInfo) {
  if (Array.isArray(diceInfo.diceValues) && diceInfo.diceValues.length === 2) {
    return diceInfo.diceValues;
  }
  return dicePairFromSum(Number(diceInfo.dice || 2));
}

function formatBonus(value) {
  const numberValue = Number(value || 0);
  if (numberValue > 0) return `+${numberValue}`;
  return String(numberValue);
}

function diceTarget(role) {
  return DICE_TARGETS[role];
}

function setDiceText(role, key, value) {
  document.getElementById(diceTarget(role)[key]).textContent = safeText(value);
}

function setDiceResultClass(role, resultClass) {
  const dicePanel = document.getElementById(diceTarget(role).panel);
  dicePanel.classList.remove(...DICE_RESULT_CLASSES);
  if (resultClass) {
    dicePanel.classList.add(`dice-panel--${resultClass}`);
  }
}

function setDicePanelHidden(role, hidden) {
  document.getElementById(diceTarget(role).panel).hidden = hidden;
}

function renderDiceNumbers(role, d1, d2, diceInfo, finalFrame = false) {
  const diceSum = d1 + d2;
  const bonus = Number(diceInfo.bonus || 0);
  const displayedTotal = finalFrame ? diceInfo.total : diceSum + bonus;

  setDiceText(role, 'die1', d1);
  setDiceText(role, 'die2', d2);
  setDiceText(role, 'sum', diceSum);
  setDiceText(role, 'bonus', formatBonus(bonus));
  setDiceText(role, 'total', displayedTotal);
}

function renderDiceFinal(role, diceInfo) {
  const [d1, d2] = finalDiceValues(diceInfo);
  renderDiceNumbers(role, d1, d2, diceInfo, true);
  setDiceText(role, 'result', diceInfo.result || '判定');
  setDiceResultClass(role, diceInfo.resultClass || 'success');
}

function hideDicePanels() {
  stopDiceRoll();
  Object.keys(DICE_TARGETS).forEach(role => {
    setDiceResultClass(role, '');
    setDicePanelHidden(role, true);
  });
}

function showDicePanel(role, diceInfo, labelOverride = '') {
  setDicePanelHidden(role, false);
  setDiceResultClass(role, '');
  setDiceText(role, 'label', labelOverride || diceInfo.label || '判定');
  setDiceText(role, 'formula', diceInfo.breakdown || '');
  setDiceText(role, 'targetLabel', diceInfo.targetLabel || '目標');
  setDiceText(role, 'target', diceInfo.target ?? '-');
  setDiceText(role, 'result', '判定中');
}

function rollDicePanels(rolls) {
  if (!rolls.length) {
    hideDicePanels();
    return;
  }

  stopDiceRoll();
  rolls.forEach(({role, diceInfo, label}) => showDicePanel(role, diceInfo, label));

  const runId = diceRunId;
  const tick = () => {
    if (runId !== diceRunId) return;
    rolls.forEach(({role, diceInfo}) => {
      renderDiceNumbers(role, randomDie(), randomDie(), diceInfo, false);
    });
  };

  tick();
  diceRollTimer = setInterval(tick, DICE_ROLL_TICK_MS);
  diceRollStopTimer = setTimeout(() => {
    if (runId !== diceRunId) return;
    stopDiceRoll();
    rolls.forEach(({role, diceInfo}) => renderDiceFinal(role, diceInfo));
  }, DICE_ROLL_DURATION_MS);
}

function typewriterText(element, text) {
  const fullText = safeText(text);
  stopTypewriter();
  element.textContent = '';

  if (!fullText) {
    element.classList.remove('is-typing');
    return;
  }

  const runId = typewriterRunId;
  let cursor = 0;
  element.classList.add('is-typing');

  const tick = () => {
    if (runId !== typewriterRunId) return;

    cursor += 1;
    element.textContent = fullText.slice(0, cursor);

    if (cursor < fullText.length) {
      typewriterTimer = setTimeout(tick, TYPEWRITER_SPEED_MS);
      return;
    }

    typewriterTimer = null;
    element.classList.remove('is-typing');
  };

  tick();
}

function eventEmphasisClass(event) {
  const type = safeText(event.type);
  const title = safeText(event.title);
  const text = safeText(event.text);
  const combined = `${title} ${text}`;

  if (type === 'goal') return 'cinema-log--goal';
  if (type === 'accident' || combined.includes('事故') || combined.includes('大破') || combined.includes('横転')) {
    return 'cinema-log--accident';
  }
  if (type === 'hit' || combined.includes('命中')) return 'cinema-log--hit';
  if (combined.includes('大成功')) return 'cinema-log--crit';
  if (type === 'success') return 'cinema-log--success';
  return '';
}

function updateCinemaEmphasis(event) {
  const cinemaLog = document.getElementById('cinemaLog');
  cinemaLog.classList.remove(...CINEMA_EMPHASIS_CLASSES);

  const emphasisClass = eventEmphasisClass(event);
  if (emphasisClass) {
    cinemaLog.classList.add(emphasisClass);
  }
}

function raceKey(race) {
  if (!race) return '';
  return `${race.rank}:${race.program}:${race.seed}:${(race.events || []).length}`;
}

function setBottomMode(mode) {
  const bottomStage = document.getElementById('bottomStage');
  bottomStage.classList.remove(...BOTTOM_MODE_CLASSES);
  bottomStage.classList.add(`mode-${mode}`);
}

function setNormalDiceLayout(hasDice) {
  document.getElementById('bottomStage').classList.toggle('normal-has-dice', hasDice);
}

function isMajorEvent(event) {
  const combined = `${safeText(event.type)} ${safeText(event.title)} ${safeText(event.text)}`;
  return event.type === 'goal' || event.type === 'accident' ||
    combined.includes('ゴール') || combined.includes('大破') || combined.includes('横転');
}

function bottomModeForEvent(event) {
  if (isMajorEvent(event)) return 'cutin';
  if (event.diceInfo?.opposed) return 'opposed';
  return 'normal';
}

function latestActionsByActor(race, eventIndex, round) {
  const latest = new Map();
  (race.events || []).slice(0, eventIndex + 1).forEach(item => {
    if (!item.actor) return;
    if ((item.round ?? 0) !== round) return;
    latest.set(item.actor, item);
  });
  return latest;
}

function renderRaceOverview(board, event) {
  const lanes = {'後列': [], '中列': [], '前列': []};
  boardRanking(board).forEach(tank => {
    const area = TRACK_AREAS.includes(tank.area) ? tank.area : '中列';
    lanes[area].push(tank);
  });

  document.getElementById('overviewMeta').textContent =
    event.actor ? `注目: ${event.actor}${event.target ? ` / 標的: ${event.target}` : ''}` : '全体俯瞰';

  document.getElementById('raceOverview').innerHTML = TRACK_AREAS.map(area => `
    <div class="overview-lane">
      <div class="overview-lane-title">${area}<span>${lanes[area].length}</span></div>
      <div class="overview-tokens">
        ${lanes[area].map(tank => `
          <span class="overview-token ${tank.name === event.actor ? 'is-actor' : ''} ${tank.name === event.target ? 'is-target' : ''} ${tank.retired ? 'is-retired' : ''}">
            ${escapeHtml(tank.name)}
          </span>
        `).join('')}
      </div>
    </div>
  `).join('');
}

function summaryClass(event) {
  if (!event) return '';
  if (event.type === 'accident' || safeText(event.title).includes('事故')) return 'summary-row--accident';
  if (event.type === 'hit') return 'summary-row--hit';
  if (event.type === 'success' || event.type === 'placement' || event.type === 'move') return 'summary-row--success';
  if (event.type === 'failure') return 'summary-row--failure';
  return '';
}

function summaryLabel(event) {
  if (!event) return '待機';
  if (event.type === 'placement') return '配置';
  if (event.type === 'move') return '移動';
  if (event.type === 'hit') return '命中';
  if (event.type === 'accident') return '事故';
  if (event.type === 'failure') return '失敗';
  if (event.type === 'success') return '成功';
  if (event.type === 'final_roll') return '最終';
  return event.title || '行動';
}

function summaryText(event) {
  if (!event) return '行動待機';
  const text = safeText(event.text || event.title).replace(/\s+/g, ' ').trim();
  return text || safeText(event.title) || '行動済み';
}

function passiveDiceInfo(diceInfo) {
  const opposed = diceInfo.opposed || {};
  const defended = diceInfo.rawResult !== '命中';
  return {
    ...opposed,
    label: opposed.label || '受動側',
    target: diceInfo.total,
    targetLabel: '攻撃達成値',
    result: defended ? '回避成功' : '回避失敗',
    resultClass: defended ? 'success' : 'failure',
    breakdown: `回避 出目${opposed.dice ?? '-'}+補${formatBonus(opposed.bonus || 0)}=${opposed.total ?? '-'}`,
  };
}

function renderDuel(event, diceInfo) {
  const passive = passiveDiceInfo(diceInfo);
  setText('duelPassive', event.target || '受動側');
  setText('duelActive', event.actor || '能動側');
  setText('duelPassiveScore', passive.total ?? '-');
  setText('duelActiveScore', diceInfo.total ?? '-');
  setText('duelOutcome', diceInfo.result || '判定');
  setText('duelText', event.text || diceInfo.breakdown || '');
}

function renderCutin(event) {
  const cutinPanel = document.getElementById('cutinPanel');
  cutinPanel.classList.remove(...CINEMA_EMPHASIS_CLASSES);
  const emphasisClass = eventEmphasisClass(event);
  if (emphasisClass) cutinPanel.classList.add(emphasisClass);
  setText('cutinTitle', event.title || '重大イベント');
  typewriterText(document.getElementById('cutinText'), event.text || '');
}

function renderNormalCommentary(event) {
  document.getElementById('eventTitle').textContent = event.title || '実況';
  updateCinemaEmphasis(event);
  typewriterText(document.getElementById('eventText'), event.text);
}

function renderBottom(race, event, eventIndex, totalEvents, board) {
  const mode = bottomModeForEvent(event);
  setBottomMode(mode);

  if (mode === 'cutin') {
    hideDicePanels();
    renderCutin(event);
    return;
  }

  if (mode === 'opposed') {
    const active = event.diceInfo;
    const passive = passiveDiceInfo(active);
    renderDuel(event, active);
    rollDicePanels([
      {role: 'passive', diceInfo: passive, label: passive.label || '受動側'},
      {role: 'active', diceInfo: active, label: active.label || '能動側'},
    ]);
    stopTypewriter();
    return;
  }

  if (mode === 'normal') {
    hideDicePanels();
    if (event.diceInfo) {
      setNormalDiceLayout(true);
      rollDicePanels([{role: 'normal', diceInfo: event.diceInfo, label: event.diceInfo.label || '判定'}]);
    }
    renderNormalCommentary(event);
    return;
  }
}

function conciseActionName(event) {
  if (!event) return '待機';
  if (event.diceInfo?.label) return event.diceInfo.label;

  const text = safeText(event.text);
  const match = text.match(/^[^:：]+[:：]\s*([^→、。]+?)(?:\s|→|、|。|$)/);
  if (match && match[1]) return match[1].trim();

  return summaryLabel(event);
}

function conciseActionResult(event) {
  if (!event) return '未処理';
  if (event.diceInfo?.result) return event.diceInfo.result;

  const text = safeText(event.text);
  const moveMatch = text.match(/(後列|中列|前列)\s*(?:→|->|-)\s*(後列|中列|前列)/);
  if (moveMatch) return `${moveMatch[1]}→${moveMatch[2]}`;

  if (event.type === 'goal') return 'ゴール';
  if (event.type === 'accident') return '事故';
  if (event.type === 'hit') return '命中';
  if (event.type === 'failure') return '失敗';
  if (event.type === 'success') return '成功';
  if (event.type === 'placement') return '配置確定';
  if (event.type === 'move') return '移動確定';
  if (event.type === 'round_start') return '開始';
  return safeText(event.title) || '処理済';
}

function renderDisplay(state) {
  if (!state || !state.ok || !state.race) return;
  const race = state.race;
  const event = state.event || {};
  const board = event.board || {};
  const eventIndex = state.current_index ?? state.index ?? 0;
  const eventNumber = state.current_event_number ?? (eventIndex + 1);
  const totalEvents = state.total_events ?? race.events.length;
  displayOdds = state.odds || race.odds || null;

  document.getElementById('raceTitle').textContent = `${race.rank}級 ${race.programLabel}`;
  document.getElementById('roundName').textContent = event.roundName || (event.round ? `第${event.round}R` : '開幕');
  document.getElementById('seedBox').textContent = `seed: ${race.seed} / event ${eventNumber}/${totalEvents}`;
  renderRaceOverview(board, event);
  renderBottom(race, event, eventIndex, totalEvents, board);

  const lanes = {
    '後列': [],
    '中列': [],
    '前列': [],
  };
  for (const t of boardRanking(board)) {
    const area = TRACK_AREAS.includes(t.area) ? t.area : '中列';
    lanes[area].push(t);
  }
  document.getElementById('lane-back').innerHTML = lanes['後列'].map(t => tankCard(t, event)).join('');
  document.getElementById('lane-mid').innerHTML = lanes['中列'].map(t => tankCard(t, event)).join('');
  document.getElementById('lane-front').innerHTML = lanes['前列'].map(t => tankCard(t, event)).join('');

  const ranking = boardRanking(board);
  const latestByActor = latestActionsByActor(race, eventIndex, event.round ?? 0);
  document.getElementById('ranking').innerHTML = ranking.map(t => {
    const odds = displayOddsForName(t.name);
    const action = latestByActor.get(t.name);
    return `
      <li class="${t.retired ? 'retired' : ''}">
        ${escapeHtml(t.name)}
        <small>${escapeHtml(t.area)} 先${t.lead}${odds ? ` / 単${Number(odds.winOdds).toFixed(1)} 複${Number(odds.placeOdds).toFixed(1)}` : ''}</small>
        <span class="ranking-action-line">
          <span class="ranking-action"><strong>宣言</strong>${escapeHtml(conciseActionName(action))}</span>
          <span class="ranking-result"><strong>結果</strong>${escapeHtml(conciseActionResult(action))}</span>
        </span>
      </li>
    `;
  }).join('');
}

async function poll() {
  try {
    const state = await fetch('/api/state').then(r => r.json());
    const currentRaceKey = raceKey(state.race);
    if (state.ok && (state.index !== lastIndex || currentRaceKey !== lastRaceKey)) {
      lastIndex = state.index;
      lastRaceKey = currentRaceKey;
      renderDisplay(state);
    }
  } catch (e) {
    console.error(e);
  }
}

setInterval(poll, 600);
poll();
