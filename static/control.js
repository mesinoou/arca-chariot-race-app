let currentRace = null;
let currentIndex = 0;

async function postJSON(url, body = {}) {
  const res = await fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  return await res.json();
}

function renderControl(state) {
  if (!state || !state.race) return;
  currentRace = state.race;
  currentIndex = state.index || 0;
  const event = state.event || currentRace.events[currentIndex];

  document.getElementById('currentEvent').textContent =
    `[${currentIndex + 1}/${currentRace.events.length}] ${event.title}\n${event.text}`;

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
      ${i + 1}. ${e.title}<br><small>${e.text}</small>
    </div>
  `).join('');
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
  renderControl({race: state.race, index: state.index, event: state.race.events[state.index]});
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

refresh();
