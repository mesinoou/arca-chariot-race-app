let lastIndex = -1;

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

function renderDisplay(state) {
  if (!state || !state.ok || !state.race) return;
  const race = state.race;
  const event = state.event;
  const board = event.board || {};

  document.getElementById('raceTitle').textContent = `${race.rank}級 ${race.programLabel}`;
  document.getElementById('roundName').textContent = event.roundName || (event.round ? `第${event.round}R` : '開幕');
  document.getElementById('seedBox').textContent = `seed: ${race.seed} / event ${state.index + 1}/${race.events.length}`;
  document.getElementById('eventTitle').textContent = event.title || '実況';
  document.getElementById('eventText').textContent = event.text || '';

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
    if (state.ok && state.index !== lastIndex) {
      lastIndex = state.index;
      renderDisplay(state);
    }
  } catch (e) {
    console.error(e);
  }
}

setInterval(poll, 600);
poll();
