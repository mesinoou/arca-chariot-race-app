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

let lastIndex = -1;
let lastRaceKey = '';
let typewriterTimer = null;
let typewriterRunId = 0;
let diceRollTimer = null;
let diceRollStopTimer = null;
let diceRunId = 0;

function areaId(area) {
  if (area === '後列') return 'lane-back';
  if (area === '中列') return 'lane-mid';
  return 'lane-front';
}

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

function tankCard(t) {
  const hpPct = Math.max(0, Math.min(100, Math.round((t.hp / t.maxHp) * 100)));
  const retiredClass = t.retired ? 'retired' : '';
  const highlight = t.highlight || '';
  return `
    <div class="tank-card ${highlight} ${retiredClass}" data-name="${t.name}">
      <div><span class="tank-name">${t.name}</span><span class="tank-style">${t.style}</span></div>
      <div class="tank-stats">
        <div class="stat-pill">HP ${t.hp}/${t.maxHp}</div>
        <div class="stat-pill">安 ${t.stability}</div>
        <div class="stat-pill">先 ${t.lead}</div>
        <div class="stat-pill">駆 ${t.drive}</div>
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

function setDiceResultClass(resultClass) {
  const dicePanel = document.getElementById('dicePanel');
  dicePanel.classList.remove(...DICE_RESULT_CLASSES);
  if (resultClass) {
    dicePanel.classList.add(`dice-panel--${resultClass}`);
  }
}

function renderDiceNumbers(d1, d2, diceInfo, finalFrame = false) {
  const diceSum = d1 + d2;
  const bonus = Number(diceInfo.bonus || 0);
  const displayedTotal = finalFrame ? diceInfo.total : diceSum + bonus;

  setText('diceDie1', d1);
  setText('diceDie2', d2);
  setText('diceSum', diceSum);
  setText('diceBonus', formatBonus(bonus));
  setText('diceTotal', displayedTotal);
}

function renderDiceFinal(diceInfo) {
  const [d1, d2] = finalDiceValues(diceInfo);
  renderDiceNumbers(d1, d2, diceInfo, true);
  setText('diceResult', diceInfo.result || '判定');
  setDiceResultClass(diceInfo.resultClass || 'success');
}

function hideDicePanel() {
  stopDiceRoll();
  document.getElementById('dicePanel').hidden = true;
  document.getElementById('bottomLayout').classList.remove('has-dice');
  setDiceResultClass('');
}

function showDicePanel(diceInfo) {
  const dicePanel = document.getElementById('dicePanel');
  dicePanel.hidden = false;
  document.getElementById('bottomLayout').classList.add('has-dice');
  setDiceResultClass('');
  setText('diceLabel', diceInfo.label || '判定');
  setText('diceFormula', diceInfo.breakdown || '');
  setText('diceTargetLabel', diceInfo.targetLabel || '目標');
  setText('diceTarget', diceInfo.target ?? '-');
  setText('diceResult', '判定中');
}

function rollDicePanel(diceInfo) {
  if (!diceInfo) {
    hideDicePanel();
    return;
  }

  stopDiceRoll();
  showDicePanel(diceInfo);

  const runId = diceRunId;
  const tick = () => {
    if (runId !== diceRunId) return;
    renderDiceNumbers(randomDie(), randomDie(), diceInfo, false);
  };

  tick();
  diceRollTimer = setInterval(tick, DICE_ROLL_TICK_MS);
  diceRollStopTimer = setTimeout(() => {
    if (runId !== diceRunId) return;
    stopDiceRoll();
    renderDiceFinal(diceInfo);
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

function renderDisplay(state) {
  if (!state || !state.ok || !state.race) return;
  const race = state.race;
  const event = state.event || {};
  const board = event.board || {};
  const eventIndex = state.current_index ?? state.index ?? 0;
  const eventNumber = state.current_event_number ?? (eventIndex + 1);
  const totalEvents = state.total_events ?? race.events.length;

  document.getElementById('raceTitle').textContent = `${race.rank}級 ${race.programLabel}`;
  document.getElementById('roundName').textContent = event.roundName || (event.round ? `第${event.round}R` : '開幕');
  document.getElementById('seedBox').textContent = `seed: ${race.seed} / event ${eventNumber}/${totalEvents}`;
  document.getElementById('eventTitle').textContent = event.title || '実況';
  updateCinemaEmphasis(event);
  rollDicePanel(event.diceInfo);
  typewriterText(document.getElementById('eventText'), event.text);

  const lanes = {
    '後列': [],
    '中列': [],
    '前列': [],
  };
  for (const t of boardRanking(board)) {
    const area = t.retired ? '後列' : t.area;
    lanes[area].push(t);
  }
  document.getElementById('lane-back').innerHTML = lanes['後列'].map(tankCard).join('');
  document.getElementById('lane-mid').innerHTML = lanes['中列'].map(tankCard).join('');
  document.getElementById('lane-front').innerHTML = lanes['前列'].map(tankCard).join('');

  const ranking = boardRanking(board);
  document.getElementById('ranking').innerHTML = ranking.map(t => `
    <li class="${t.retired ? 'retired' : ''}">${t.name} <small>${t.area} 先${t.lead}</small></li>
  `).join('');
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
