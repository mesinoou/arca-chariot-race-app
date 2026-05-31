const TYPEWRITER_SPEED_MS = 28;
const CINEMA_EMPHASIS_CLASSES = [
  'cinema-log--accident',
  'cinema-log--hit',
  'cinema-log--crit',
  'cinema-log--goal',
  'cinema-log--success',
];

let lastIndex = -1;
let lastRaceKey = '';
let typewriterTimer = null;
let typewriterRunId = 0;

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

function stopTypewriter() {
  typewriterRunId += 1;
  if (typewriterTimer !== null) {
    clearTimeout(typewriterTimer);
    typewriterTimer = null;
  }
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

  document.getElementById('raceTitle').textContent = `${race.rank}級 ${race.programLabel}`;
  document.getElementById('roundName').textContent = event.roundName || (event.round ? `第${event.round}R` : '開幕');
  document.getElementById('seedBox').textContent = `seed: ${race.seed} / event ${state.index + 1}/${race.events.length}`;
  document.getElementById('eventTitle').textContent = event.title || '実況';
  updateCinemaEmphasis(event);
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
