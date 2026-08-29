// LoLQ Config Editor - Layouts-first architecture

const ROLES = ['top', 'jungle', 'mid', 'bot', 'utility'];
const ROLE_LABELS = { top: 'Top', jungle: 'Jungle', mid: 'Mid', bot: 'Bot', utility: 'Utility' };
const ROLE_SHORT = { top: 'T', jungle: 'J', mid: 'M', bot: 'B', utility: 'U' };

// Hardcoded fallback for spell key mapping (used if DDragon summoner.json fails)
const SPELL_KEYS_FALLBACK = {
  flash: 'SummonerFlash', ignite: 'SummonerDot', smite: 'SummonerSmite',
  teleport: 'SummonerTeleport', heal: 'SummonerHeal', exhaust: 'SummonerExhaust',
  barrier: 'SummonerBarrier', cleanse: 'SummonerBoost', ghost: 'SummonerHaste',
  clarity: 'SummonerMana', mark: 'SummonerSnowball'
};

const CDRAGON_BASE = 'https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default';

const STAT_SHARDS = [
  [{ id: 5008, name: 'Adaptive Force', cfg: 'adaptive force', icon: `${CDRAGON_BASE}/v1/perk-images/statmods/statmodsadaptiveforceicon.png` },
   { id: 5005, name: 'Attack Speed', cfg: 'attack speed', icon: `${CDRAGON_BASE}/v1/perk-images/statmods/statmodsattackspeedicon.png` },
   { id: 5007, name: 'Ability Haste', cfg: 'ability haste', icon: `${CDRAGON_BASE}/v1/perk-images/statmods/statmodscdrscalingicon.png` }],
  [{ id: 5008, name: 'Adaptive Force', cfg: 'adaptive force', icon: `${CDRAGON_BASE}/v1/perk-images/statmods/statmodsadaptiveforceicon.png` },
   { id: 5010, name: 'Movement Speed', cfg: 'movement speed', icon: `${CDRAGON_BASE}/v1/perk-images/statmods/statmodsmovementspeedicon.png` },
   { id: 5001, name: 'Health Scaling', cfg: 'health scaling', icon: `${CDRAGON_BASE}/v1/perk-images/statmods/statmodshealthplusicon.png` }],
  [{ id: 5011, name: 'Health', cfg: 'health', icon: `${CDRAGON_BASE}/v1/perk-images/statmods/statmodshealthscalingicon.png` },
   { id: 5013, name: 'Tenacity', cfg: 'tenacity', icon: `${CDRAGON_BASE}/v1/perk-images/statmods/statmodstenacityicon.png` },
   { id: 5001, name: 'Health Scaling', cfg: 'health scaling', icon: `${CDRAGON_BASE}/v1/perk-images/statmods/statmodshealthplusicon.png` }]
];

// State
const state = {
  config: null, // { bans, layouts, roles, fallback }
  champions: {},
  championList: [],
  spellKeys: {}, // name -> DDragon key (e.g. "flash" -> "SummonerFlash")
  spellList: [],  // available spell names
  runes: [],
  ddVersion: ''
};

// Rune picker state
let runePicker = {
  primaryTreeId: null, secondaryTreeId: null,
  primaryRunes: [null, null, null, null],
  secondarySlots: {},
  statShards: [null, null, null],
  callback: null
};

// ===================== HELPERS =====================

function champIcon(name) {
  const c = state.champions[name];
  return c ? `https://ddragon.leagueoflegends.com/cdn/${state.ddVersion}/img/champion/${c.id}.png` : '';
}

function spellIcon(name) {
  const n = name?.toLowerCase();
  const key = state.spellKeys[n] || SPELL_KEYS_FALLBACK[n];
  return key ? `https://ddragon.leagueoflegends.com/cdn/${state.ddVersion}/img/spell/${key}.png` : '';
}

function runeIcon(path) {
  return `https://ddragon.leagueoflegends.com/cdn/img/${path}`;
}

function norm(s) {
  return (s || '').replace(/[^a-z0-9]/gi, '').toLowerCase();
}

function runeToConfig(name) {
  return name.toLowerCase().replace(/[^a-z ]/g, '').replace(/\s+/g, ' ').trim();
}

function findRuneInData(name) {
  const n = norm(name);
  if (!n) return null;
  for (const tree of state.runes) {
    for (const slot of tree.slots) {
      for (const rune of slot.runes) {
        if (norm(rune.name) === n) return { ...rune, treeId: tree.id };
      }
    }
  }
  for (const tree of state.runes) {
    for (const slot of tree.slots) {
      for (const rune of slot.runes) {
        if (norm(rune.name).includes(n) || n.includes(norm(rune.name)))
          return { ...rune, treeId: tree.id };
      }
    }
  }
  return null;
}

function nextLayoutId() {
  const ids = Object.keys(state.config.layouts).map(Number).filter(n => !isNaN(n));
  return String((ids.length ? Math.max(...ids) : 0) + 1);
}

function esc(s) {
  return (s || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.remove('hidden');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add('hidden'), 2000);
}

// ===================== DATA LOADING =====================

async function loadDDragon() {
  const vers = await fetch('https://ddragon.leagueoflegends.com/api/versions.json').then(r => r.json());
  state.ddVersion = vers[0];

  // Fetch champions, runes, and spells in parallel (spells can fail gracefully)
  const [cData, rData, sData] = await Promise.all([
    fetch(`https://ddragon.leagueoflegends.com/cdn/${state.ddVersion}/data/en_US/champion.json`).then(r => r.json()),
    fetch(`https://ddragon.leagueoflegends.com/cdn/${state.ddVersion}/data/en_US/runesReforged.json`).then(r => r.json()),
    fetch(`https://ddragon.leagueoflegends.com/cdn/${state.ddVersion}/data/en_US/summoner.json`).then(r => r.json()).catch(() => null)
  ]);

  // Champions
  state.champions = {};
  state.championList = [];
  for (const [id, c] of Object.entries(cData.data)) {
    state.champions[c.name] = { id, key: c.key, name: c.name };
    state.championList.push(c.name);
  }
  state.championList.sort();
  state.runes = rData;

  // Summoner spells - build name->key map from API, skip arena/URF/placeholder spells
  state.spellKeys = {};
  state.spellList = [];
  if (sData?.data) {
    const skip = /Cherry|Poro|URF|Placeholder/i;
    for (const [id, s] of Object.entries(sData.data)) {
      if (skip.test(id)) continue;
      const name = s.name.toLowerCase();
      if (!state.spellKeys[name]) {
        state.spellKeys[name] = id;
        state.spellList.push(name);
      }
    }
  }
  // Fallback if API returned nothing useful
  if (state.spellList.length === 0) {
    state.spellKeys = { ...SPELL_KEYS_FALLBACK };
    state.spellList = Object.keys(SPELL_KEYS_FALLBACK);
  }
}

async function loadConfig() {
  state.config = await fetch('/api/config').then(r => r.json());
  if (!state.config.layouts) state.config.layouts = {};
  if (!state.config.roles) {
    state.config.roles = {};
    ROLES.forEach(r => state.config.roles[r] = []);
  }
  ROLES.forEach(r => { if (!state.config.roles[r]) state.config.roles[r] = []; });
  if (!state.config.bans) state.config.bans = [];
  if (!state.config.fallback) state.config.fallback = { mode: 'random_default', layout_id: '' };
}

async function saveConfig() {
  const el = document.getElementById('save-status');
  try {
    await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(state.config)
    });
    if (el) { el.textContent = 'Saved'; el.className = 'save-status ok'; }
    clearTimeout(el?._t);
    if (el) el._t = setTimeout(() => { el.textContent = ''; el.className = 'save-status'; }, 1500);
  } catch (e) {
    if (el) { el.textContent = 'Save failed'; el.className = 'save-status err'; }
  }
}

let _autoSaveTimer = null;
function autoSave() {
  clearTimeout(_autoSaveTimer);
  _autoSaveTimer = setTimeout(saveConfig, 150);
}

// ===================== RENDERING =====================

function render() {
  renderBans();
  renderPool();
  renderRoles();
  renderFallback();
}

function renderBans() {
  const el = document.getElementById('bans-section');
  const bans = state.config.bans;
  el.innerHTML = `
    <div class="section-header"><h2>Bans</h2></div>
    <div id="bans-list" class="bans-list">
      ${bans.map((b, i) => `
        <div class="ban-item" data-index="${i}">
          <img src="${champIcon(b)}" alt="${esc(b)}" onerror="this.style.display='none'">
          <span>${b}</span>
          <button class="btn-x" onclick="removeBan(${i})">&times;</button>
        </div>
      `).join('')}
    </div>
    <button class="btn-add" onclick="addBan()">+ Add Ban</button>
  `;
  new Sortable(document.getElementById('bans-list'), {
    animation: 150,
    onEnd: e => {
      const item = state.config.bans.splice(e.oldIndex, 1)[0];
      state.config.bans.splice(e.newIndex, 0, item);
      autoSave();
    }
  });
}

function renderPool() {
  const grid = document.getElementById('pool-grid');
  const layoutIds = Object.keys(state.config.layouts);
  if (layoutIds.length === 0) {
    grid.innerHTML = '<p class="text-muted" style="padding:8px">No layouts yet. Click "+ New Layout" to add one.</p>';
    return;
  }
  grid.innerHTML = layoutIds.map(lid => {
    const layout = state.config.layouts[lid];
    const name = layout.champion || '???';
    const spells = layout.spells || [];
    const runes = layout.runes || [];

    let keystoneHtml = '';
    if (runes.length > 0) {
      const ks = findRuneInData(runes[0]);
      if (ks && ks.icon) {
        keystoneHtml = `<img src="${runeIcon(ks.icon)}" class="keystone-icon" title="${runes[0]}">`;
      }
    }

    const spellHtml = spells.map(s => `<img src="${spellIcon(s)}" class="spell-icon" title="${s}">`).join('');

    const roleBtns = ROLES.map(r => {
      const active = (state.config.roles[r] || []).includes(lid);
      return `<button class="pool-role-btn ${active ? 'active' : ''}" onclick="toggleLayoutRole('${lid}','${r}')" title="${ROLE_LABELS[r]}">${ROLE_SHORT[r]}</button>`;
    }).join('');

    return `
      <div class="pool-card" data-layout-id="${lid}">
        <div class="pool-card-top">
          <div class="pool-card-icon">
            <img src="${champIcon(name)}" alt="${esc(name)}" onerror="this.style.opacity=0.3" onclick="changeLayoutChampion('${lid}')">
          </div>
          <div class="pool-card-info">
            <div class="pool-card-name" onclick="changeLayoutChampion('${lid}')">${name}</div>
          </div>
          <div class="pool-card-actions">
            <button class="btn-sm" onclick="editLayoutSpells('${lid}')">Spells</button>
            <button class="btn-sm" onclick="editLayoutRunes('${lid}')">Runes</button>
            <button class="btn-sm btn-danger" onclick="removeLayout('${lid}')">&times;</button>
          </div>
        </div>
        <div class="pool-card-details">${spellHtml}${keystoneHtml}</div>
        <div class="pool-card-bottom">${roleBtns}</div>
      </div>
    `;
  }).join('');
}

function renderRoles() {
  const grid = document.getElementById('roles-grid');
  grid.innerHTML = ROLES.map(role => {
    const ids = state.config.roles[role] || [];
    const items = ids.map((lid, i) => {
      const layout = state.config.layouts[lid];
      if (!layout) return '';
      const name = layout.champion || '???';
      const spellImgs = (layout.spells || []).map(s => `<img src="${spellIcon(s)}" title="${s}">`).join('');
      return `
        <div class="role-item" data-lid="${lid}">
          <span class="role-item-num">${i + 1}</span>
          <div class="role-item-icon"><img src="${champIcon(name)}" alt="${esc(name)}" onerror="this.style.opacity=0.3"></div>
          <span class="role-item-name">${name}</span>
          <div class="role-item-spells">${spellImgs}</div>
          <button class="role-item-remove" onclick="removeFromRole('${role}','${lid}')">&times;</button>
        </div>
      `;
    }).join('');

    return `
      <div class="role-column">
        <div class="role-column-header">${ROLE_LABELS[role]}<span class="role-count">${ids.length}</span></div>
        <div class="role-column-items" id="role-items-${role}">${items}</div>
      </div>
    `;
  }).join('');

  // Setup SortableJS on each column
  ROLES.forEach(role => {
    const el = document.getElementById(`role-items-${role}`);
    if (el) {
      new Sortable(el, {
        animation: 150,
        group: { name: 'roles', pull: false, put: false },
        onEnd: e => {
          const ids = state.config.roles[role];
          const item = ids.splice(e.oldIndex, 1)[0];
          ids.splice(e.newIndex, 0, item);
          renderRoles();
          autoSave();
        }
      });
    }
  });
}

function renderFallback() {
  const el = document.getElementById('fallback-section');
  const fb = state.config.fallback;
  const layoutIds = Object.keys(state.config.layouts);

  const layoutOptions = layoutIds.map(lid => {
    const l = state.config.layouts[lid];
    const selected = fb.layout_id === lid ? 'selected' : '';
    return `<option value="${lid}" ${selected}>${l.champion || '???'}</option>`;
  }).join('');

  el.innerHTML = `
    <div class="section-header"><h2>Fallback</h2></div>
    <p class="text-muted" style="margin-bottom:10px">When assigned a role with no layouts configured:</p>
    <div class="fallback-options">
      <label class="fallback-radio ${fb.mode === 'random_default' ? 'active' : ''}" onclick="setFallbackMode('random_default')">
        <input type="radio" name="fb" ${fb.mode === 'random_default' ? 'checked' : ''}>
        Random champion + default runes
      </label>
      <label class="fallback-radio ${fb.mode === 'fallback_layout' ? 'active' : ''}" onclick="setFallbackMode('fallback_layout')">
        <input type="radio" name="fb" ${fb.mode === 'fallback_layout' ? 'checked' : ''}>
        Use layout:
        <select onchange="setFallbackLayout(this.value)" onclick="event.stopPropagation()">
          <option value="">-- select --</option>
          ${layoutOptions}
        </select>
      </label>
    </div>
  `;
}

// ===================== HANDLERS =====================

function removeBan(i) {
  state.config.bans.splice(i, 1);
  renderBans();
  autoSave();
}

function addBan() {
  openChampionPicker(name => {
    if (!state.config.bans.includes(name)) {
      state.config.bans.push(name);
      renderBans();
      autoSave();
    }
  });
}

function addLayout() {
  openChampionPicker(name => {
    const lid = nextLayoutId();
    state.config.layouts[lid] = { champion: name, spells: [], runes: [] };
    renderPool();
    renderFallback();
    autoSave();
  });
}

function removeLayout(lid) {
  delete state.config.layouts[lid];
  // Remove from all roles
  ROLES.forEach(r => {
    state.config.roles[r] = (state.config.roles[r] || []).filter(id => id !== lid);
  });
  // Clear fallback if it referenced this layout
  if (state.config.fallback.layout_id === lid) {
    state.config.fallback.layout_id = '';
  }
  renderPool();
  renderRoles();
  renderFallback();
  autoSave();
}

function changeLayoutChampion(lid) {
  openChampionPicker(name => {
    state.config.layouts[lid].champion = name;
    renderPool();
    renderRoles();
    renderFallback();
    autoSave();
  });
}

function editLayoutSpells(lid) {
  const layout = state.config.layouts[lid];
  openSpellPicker(layout.spells || [], spells => {
    layout.spells = spells;
    renderPool();
    renderRoles();
    autoSave();
  });
}

function editLayoutRunes(lid) {
  const layout = state.config.layouts[lid];
  openRunePicker(layout.runes || [], runes => {
    layout.runes = runes;
    renderPool();
    renderRoles();
    autoSave();
  });
}

function toggleLayoutRole(lid, role) {
  const ids = state.config.roles[role];
  const idx = ids.indexOf(lid);
  if (idx >= 0) {
    ids.splice(idx, 1);
  } else {
    ids.push(lid);
  }
  renderPool();
  renderRoles();
  autoSave();
}

function removeFromRole(role, lid) {
  const ids = state.config.roles[role];
  const idx = ids.indexOf(lid);
  if (idx >= 0) {
    ids.splice(idx, 1);
    renderPool();
    renderRoles();
    autoSave();
  }
}

function setFallbackMode(mode) {
  state.config.fallback.mode = mode;
  if (mode === 'random_default') state.config.fallback.layout_id = '';
  renderFallback();
  autoSave();
}

function setFallbackLayout(lid) {
  state.config.fallback.mode = 'fallback_layout';
  state.config.fallback.layout_id = lid;
  renderFallback();
  autoSave();
}

// ===================== MODALS =====================

function openModal(html) {
  document.getElementById('modal-content').innerHTML = html;
  document.getElementById('modal-overlay').classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

function closeModal(e) {
  if (e && e.target !== document.getElementById('modal-overlay')) return;
  closeModalForce();
}

function closeModalForce() {
  document.getElementById('modal-overlay').classList.add('hidden');
  document.body.style.overflow = '';
}

// --- Champion Picker ---
function openChampionPicker(callback) {
  window._champCb = callback;
  openModal(`
    <div class="modal-header"><h3>Select Champion</h3></div>
    <input type="text" id="champ-search" class="search-input" placeholder="Search champions..." oninput="filterChampions()">
    <div id="champ-grid" class="champ-grid">
      ${state.championList.map(name => `
        <div class="champ-option" onclick="pickChampion('${esc(name)}')">
          <img src="${champIcon(name)}" alt="${esc(name)}" loading="lazy">
          <span>${name}</span>
        </div>
      `).join('')}
    </div>
  `);
  setTimeout(() => document.getElementById('champ-search')?.focus(), 50);
}

function filterChampions() {
  const q = norm(document.getElementById('champ-search').value);
  document.querySelectorAll('.champ-option').forEach(el => {
    const name = norm(el.querySelector('span').textContent);
    el.style.display = name.includes(q) ? '' : 'none';
  });
}

function pickChampion(name) {
  closeModalForce();
  window._champCb?.(name);
}

// --- Spell Picker ---
let _spellOrder = []; // ordered [spell1, spell2] for D, F

function openSpellPicker(current, callback) {
  window._spellCb = callback;
  _spellOrder = (current || []).map(s => s.toLowerCase()).slice(0, 2);
  renderSpellPicker();
}

function renderSpellPicker() {
  const slot = (i, label) => {
    const s = _spellOrder[i];
    if (s) {
      return `<div class="spell-slot">
        <span class="spell-slot-key">${label}</span>
        <div class="spell-slot-icon"><img src="${spellIcon(s)}" alt="${s}"></div>
        <span class="spell-slot-name">${s[0].toUpperCase() + s.slice(1)}</span>
      </div>`;
    }
    return `<div class="spell-slot">
      <span class="spell-slot-key">${label}</span>
      <div class="spell-slot-icon empty"></div>
      <span class="spell-slot-name text-muted">-</span>
    </div>`;
  };

  openModal(`
    <div class="modal-header">
      <h3>Summoner Spells</h3>
      <p class="text-muted">Click spells in order: first click = D, second = F</p>
    </div>
    <div class="spell-order-preview">
      ${slot(0, 'D')}
      <span class="spell-order-arrow"></span>
      ${slot(1, 'F')}
    </div>
    <div id="spell-grid" class="spell-grid">
      ${state.spellList.map(s => {
        const idx = _spellOrder.indexOf(s);
        const cls = idx >= 0 ? 'selected' : '';
        const badge = idx === 0 ? 'D' : idx === 1 ? 'F' : '';
        return `
        <div class="spell-option ${cls}" onclick="toggleSpell('${s}')" data-spell="${s}">
          <img src="${spellIcon(s)}" alt="${s}">
          <span>${s[0].toUpperCase() + s.slice(1)}</span>
        </div>`;
      }).join('')}
    </div>
    <div class="modal-footer">
      <button class="btn-secondary" onclick="clearSpells()">Clear</button>
      <button class="btn-secondary" onclick="closeModalForce()">Cancel</button>
      <button class="btn-primary" onclick="applySpells()">Apply</button>
    </div>
  `);
}

function toggleSpell(spell) {
  const idx = _spellOrder.indexOf(spell);
  if (idx >= 0) {
    _spellOrder.splice(idx, 1);
  } else if (_spellOrder.length < 2) {
    _spellOrder.push(spell);
  } else {
    // Replace second slot
    _spellOrder[1] = spell;
  }
  renderSpellPicker();
}

function clearSpells() {
  _spellOrder = [];
  renderSpellPicker();
}

function applySpells() {
  closeModalForce();
  window._spellCb?.([..._spellOrder]);
}

// --- Rune Picker ---
function openRunePicker(currentRunes, callback) {
  runePicker = {
    primaryTreeId: null, secondaryTreeId: null,
    primaryRunes: [null, null, null, null],
    secondarySlots: {},
    statShards: [null, null, null],
    callback
  };

  if (currentRunes && currentRunes.length > 0) {
    for (let i = 0; i < Math.min(4, currentRunes.length); i++) {
      const found = findRuneInData(currentRunes[i]);
      if (found && found.treeId) {
        if (!runePicker.primaryTreeId) runePicker.primaryTreeId = found.treeId;
        runePicker.primaryRunes[i] = found.id;
      }
    }
    for (let i = 4; i < Math.min(6, currentRunes.length); i++) {
      const found = findRuneInData(currentRunes[i]);
      if (found && found.treeId) {
        if (!runePicker.secondaryTreeId) runePicker.secondaryTreeId = found.treeId;
        const tree = state.runes.find(t => t.id === found.treeId);
        if (tree) {
          for (let si = 1; si < tree.slots.length; si++) {
            if (tree.slots[si].runes.some(r => r.id === found.id)) {
              runePicker.secondarySlots[si] = found.id;
              break;
            }
          }
        }
      }
    }
    for (let i = 6; i < Math.min(9, currentRunes.length); i++) {
      const row = i - 6;
      const n = norm(currentRunes[i]);
      // Exact match only: substring matching broke here because "health" is
      // a substring of "healthscaling", so it matched before ever reaching
      // the real "health scaling" entry later in the row.
      const shard = STAT_SHARDS[row].find(s => norm(s.cfg) === n);
      if (shard) runePicker.statShards[row] = shard.id;
    }
  }

  renderRunePickerModal();
}

function renderRunePickerModal() {
  const primaryTree = state.runes.find(t => t.id === runePicker.primaryTreeId);
  const secondaryTree = state.runes.find(t => t.id === runePicker.secondaryTreeId);

  openModal(`
    <div class="modal-header"><h3>Edit Runes</h3></div>
    <div class="rune-picker">
      <div class="rune-trees-select">
        ${state.runes.map(tree => {
          let cls = 'tree-icon';
          if (tree.id === runePicker.primaryTreeId) cls += ' primary-selected';
          else if (tree.id === runePicker.secondaryTreeId) cls += ' secondary-selected';
          return `<div class="${cls}" onclick="selectTree(${tree.id})" title="${tree.name}">
            <img src="${runeIcon(tree.icon)}" alt="${tree.name}">
            <span>${tree.name}</span>
          </div>`;
        }).join('')}
      </div>

      <div class="rune-columns">
        <div class="rune-column primary-column">
          <h4>${primaryTree ? primaryTree.name : 'Primary'}</h4>
          ${primaryTree ? primaryTree.slots.map((slot, si) => `
            <div class="rune-slot">
              ${slot.runes.map(rune => `
                <div class="rune-option ${si === 0 ? 'keystone' : ''} ${runePicker.primaryRunes[si] === rune.id ? 'selected' : ''}"
                     onclick="selectPrimaryRune(${si},${rune.id})" title="${rune.name}">
                  <img src="${runeIcon(rune.icon)}" alt="${rune.name}">
                </div>
              `).join('')}
            </div>
          `).join('') : '<p class="text-muted" style="text-align:center;padding:20px">Click a tree above</p>'}
        </div>

        <div class="rune-column secondary-column">
          <h4>${secondaryTree ? secondaryTree.name : 'Secondary'}</h4>
          ${secondaryTree ? secondaryTree.slots.slice(1).map((slot, si) => {
            const idx = si + 1;
            return `<div class="rune-slot">
              ${slot.runes.map(rune => `
                <div class="rune-option ${runePicker.secondarySlots[idx] === rune.id ? 'selected' : ''}"
                     onclick="selectSecondaryRune(${idx},${rune.id})" title="${rune.name}">
                  <img src="${runeIcon(rune.icon)}" alt="${rune.name}">
                </div>
              `).join('')}
            </div>`;
          }).join('') : '<p class="text-muted" style="text-align:center;padding:20px">Click a different tree</p>'}
        </div>
      </div>

      <div class="stat-shards">
        <h4>Stat Shards</h4>
        ${STAT_SHARDS.map((row, ri) => `
          <div class="shard-row">
            ${row.map(shard => `
              <div class="shard-option ${runePicker.statShards[ri] === shard.id ? 'selected' : ''}"
                   onclick="selectStatShard(${ri},${shard.id})" title="${shard.name}"><img src="${shard.icon}" class="shard-icon" onerror="this.style.display='none'"></div>
            `).join('')}
          </div>
        `).join('')}
      </div>
    </div>

    <div class="modal-footer">
      <button class="btn-secondary" onclick="clearRunes()">Clear</button>
      <button class="btn-secondary" onclick="closeModalForce()">Cancel</button>
      <button class="btn-primary" onclick="applyRunes()">Apply</button>
    </div>
  `);
}

function selectTree(treeId) {
  if (runePicker.primaryTreeId === treeId) {
    runePicker.primaryTreeId = null;
    runePicker.primaryRunes = [null, null, null, null];
    if (runePicker.secondaryTreeId) {
      runePicker.primaryTreeId = runePicker.secondaryTreeId;
      runePicker.secondaryTreeId = null;
      runePicker.secondarySlots = {};
    }
  } else if (runePicker.secondaryTreeId === treeId) {
    runePicker.secondaryTreeId = null;
    runePicker.secondarySlots = {};
  } else if (!runePicker.primaryTreeId) {
    runePicker.primaryTreeId = treeId;
    runePicker.primaryRunes = [null, null, null, null];
  } else if (!runePicker.secondaryTreeId) {
    runePicker.secondaryTreeId = treeId;
    runePicker.secondarySlots = {};
  } else {
    runePicker.secondaryTreeId = treeId;
    runePicker.secondarySlots = {};
  }
  renderRunePickerModal();
}

function selectPrimaryRune(slot, runeId) {
  runePicker.primaryRunes[slot] = runePicker.primaryRunes[slot] === runeId ? null : runeId;
  renderRunePickerModal();
}

function selectSecondaryRune(slot, runeId) {
  const slots = Object.keys(runePicker.secondarySlots).map(Number);
  if (slots.includes(slot)) {
    if (runePicker.secondarySlots[slot] === runeId) {
      delete runePicker.secondarySlots[slot];
    } else {
      runePicker.secondarySlots[slot] = runeId;
    }
  } else if (slots.length < 2) {
    runePicker.secondarySlots[slot] = runeId;
  } else {
    delete runePicker.secondarySlots[slots[0]];
    runePicker.secondarySlots[slot] = runeId;
  }
  renderRunePickerModal();
}

function selectStatShard(row, id) {
  runePicker.statShards[row] = runePicker.statShards[row] === id ? null : id;
  renderRunePickerModal();
}

function applyRunes() {
  const runes = [];
  const primaryTree = state.runes.find(t => t.id === runePicker.primaryTreeId);
  const secondaryTree = state.runes.find(t => t.id === runePicker.secondaryTreeId);

  if (primaryTree) {
    for (let i = 0; i < 4; i++) {
      const id = runePicker.primaryRunes[i];
      if (id) {
        const rune = primaryTree.slots[i].runes.find(r => r.id === id);
        if (rune) runes.push(runeToConfig(rune.name));
      }
    }
  }
  if (secondaryTree) {
    const sortedSlots = Object.keys(runePicker.secondarySlots).map(Number).sort();
    for (const si of sortedSlots) {
      const id = runePicker.secondarySlots[si];
      const rune = secondaryTree.slots[si].runes.find(r => r.id === id);
      if (rune) runes.push(runeToConfig(rune.name));
    }
  }
  for (let i = 0; i < 3; i++) {
    const id = runePicker.statShards[i];
    if (id) {
      const shard = STAT_SHARDS[i].find(s => s.id === id);
      if (shard) runes.push(shard.cfg);
    }
  }

  closeModalForce();
  runePicker.callback?.(runes);
}

function clearRunes() {
  closeModalForce();
  runePicker.callback?.([]);
}

// ===================== KEYBOARD =====================
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModalForce();
});

// ===================== INIT =====================
async function init() {
  try {
    await loadDDragon();
    await loadConfig();
    document.getElementById('loading').classList.add('hidden');
    document.getElementById('app').classList.remove('hidden');
    render();
  } catch (e) {
    document.getElementById('loading').innerHTML =
      `<p style="color:var(--red)">Failed to load: ${e.message}</p>
       <button onclick="location.reload()" class="btn-primary" style="margin-top:12px">Retry</button>`;
  }
}

init();
