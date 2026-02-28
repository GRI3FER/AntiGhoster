// ════════════════════════════════════════
// STATE
// ════════════════════════════════════════
const S = {
  step: 1,
  settings: {},
  rawContacts: [],
  rawGroups: [],
  people: [],
  allPeople: [],
  overdueCache: {}
};

// ════════════════════════════════════════
// INIT
// ════════════════════════════════════════
async function init() {
  const r = await fetch('/api/settings');
  S.settings = await r.json();
  S.people = deepClone(S.settings.people || []);

  if (S.settings.setup_complete) {
    showApp();
  } else {
    loadRaw();
    showSetup();
  }
  checkStatus();
}

function deepClone(x) { return JSON.parse(JSON.stringify(x)); }

// ════════════════════════════════════════
// SETUP
// ════════════════════════════════════════
function showSetup() {
  document.getElementById('setup').classList.remove('hidden');
  document.getElementById('app').classList.remove('visible');
  goStep(1);
}

function showApp() {
  document.getElementById('setup').classList.add('hidden');
  document.getElementById('app').classList.add('visible');
  loadPeople();
  setInterval(loadPeople, 120000);
}

function goStep(n) {
  S.step = n;
  document.querySelectorAll('.wstep').forEach(el => el.classList.remove('active'));
  document.getElementById(`wstep-${n}`).classList.add('active');
  for (let i = 1; i <= 2; i++) {
    const d = document.getElementById(`dot-${i}`);
    d.className = 'step-dot' + (i < n ? ' done' : i === n ? ' active' : '');
  }
  document.getElementById('btn-back').style.visibility = n === 1 ? 'hidden' : 'visible';
  document.getElementById('btn-next').textContent = n === 2 ? 'Open Dashboard →' : 'Continue →';
  if (n === 1) renderPeopleList();
}

function wizardNext() {
  if (S.step < 2) goStep(S.step + 1);
  else finishSetup();
}
function wizardBack() { if (S.step > 1) goStep(S.step - 1); }

async function finishSetup() {
  const settings = {
    setup_complete: true,
    people: S.people.filter(p => p.display_name.trim()),
  };
  await fetch('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(settings)});
  S.settings = settings;
  showApp();
}

async function loadRaw() {
  try {
    const r = await fetch('/api/contacts/raw');
    const d = await r.json();
    S.rawContacts = d.contacts || [];
    S.rawGroups   = d.groups   || [];
    if (S.step === 1) renderPeopleList();
  } catch {}
}

//Notification helper
function checkOverdueNotifications() {
  if (Notification.permission !== "granted") return;

  S.allPeople.forEach(p => {
    const isOverdue = p.days_since !== null && p.days_since >= 14;
    const wasOverdue = S.overdueCache[p.id];

    if (isOverdue && !wasOverdue) {
      new Notification(`${p.display_name} is now being ghosted`, {
        body: `Time to lock in and message ${p.display_name}`,
      }); 
    }

    S.overdueCache[p.id] = isOverdue;
  });
}

// ════════════════════════════════════════
// STEP 1 — PEOPLE BUILDER
// ════════════════════════════════════════
function addPerson(name='') {
  S.people.push({ id: 'p_' + Date.now() + '_' + Math.random().toString(36).slice(2), display_name: name, chat_ids: [] });
  renderPeopleList();
  // Focus the new input
  setTimeout(() => {
    const inputs = document.querySelectorAll('.person-name-input');
    if (inputs.length) inputs[inputs.length - 1].focus();
  }, 50);
}

function removePerson(id) {
  S.people = S.people.filter(p => p.id !== id);
  renderPeopleList();
}

function getPeopleList() { return S._editPerson ? [S._editPerson] : S.people; }

function updatePersonName(id, name) {
  const p = getPeopleList().find(p => p.id === id);
  if (!p) return;
  p.display_name = name;
  if (S._editPerson) document.getElementById('editPanelTitle').textContent = name || 'Add person';
  clearTimeout(window._suggTimer);
  window._suggTimer = setTimeout(() => {
    const inp = document.getElementById(`linksearch-${id}`);
    if (inp) { inp.value = name; renderLinkResults(id); showLinkResults(id); }
  }, 250);
}

function linkChat(personId, chatId) {
  const p = getPeopleList().find(p => p.id === personId);
  if (p && !p.chat_ids.includes(chatId)) p.chat_ids.push(chatId);
  refreshCardChips(personId);
  const inp = document.getElementById(`linksearch-${personId}`);
  if (inp) { inp.value = ''; }
  hideLinkResults(personId);
}

function unlinkChat(personId, chatId) {
  const p = getPeopleList().find(p => p.id === personId);
  if (p) p.chat_ids = p.chat_ids.filter(id => id !== chatId);
  refreshCardChips(personId);
}

function refreshCardChips(id) {
  const p    = getPeopleList().find(p => p.id === id);
  const card = document.getElementById(`pcard-${p.id}`);
  if (!card) return;
  card.classList.toggle('has-chats', p.chat_ids.length > 0);
  let chipsEl = card.querySelector('.person-chats');
  if (p.chat_ids.length) {
    const html = p.chat_ids.map(cid => {
      const c = S.rawContacts.find(x => x.id === cid) || S.rawGroups.find(x => x.id === cid);
      if (!c) return '';
      const initials = (c.name||'?').split(' ').map(w=>w[0]).join('').slice(0,2).toUpperCase();
      const av      = c.avatar ? `<img src="${avatarUrl(c.avatar)}" onerror="this.parentElement.innerHTML='${initials}'">` : initials;
      const isGroup = c.is_group || c.member_count > 1;
      const tag     = isGroup ? `<span style="font-family:'DM Mono',monospace;font-size:.55rem;color:var(--purple)">group</span>` : '';
      return `<div class="chat-chip">
        <div class="chat-chip-av">${av}</div>
        <span class="chat-chip-name">${e(c.name)}</span>
        <span class="chat-chip-net">${e(c.network)}</span>
        ${tag}
        <button class="chat-chip-x" onclick="unlinkChat('${p.id}','${cid}')" title="Remove">✕</button>
      </div>`;
    }).join('');
    if (chipsEl) { chipsEl.innerHTML = html; }
    else {
      const newEl = document.createElement('div');
      newEl.className = 'person-chats';
      newEl.innerHTML = html;
      card.querySelector('.person-header').insertAdjacentElement('afterend', newEl);
    }
  } else {
    if (chipsEl) chipsEl.remove();
  }
}

// Link search dropdown
function showLinkResults(personId) {
  renderLinkResults(personId);
  const res = document.getElementById(`linkresults-${personId}`);
  if (res) res.classList.remove('hidden');
}

function hideLinkResults(personId) {
  const res = document.getElementById(`linkresults-${personId}`);
  if (res) res.classList.add('hidden');
}

function renderLinkResults(personId) {
  const inp = document.getElementById(`linksearch-${personId}`);
  const res = document.getElementById(`linkresults-${personId}`);
  if (!inp || !res) return;

  const q      = inp.value.toLowerCase().trim();
  const linked = getLinkedIds();

  // Combine DMs and group chats, excluding already-linked ones
  const allChats = [
    ...S.rawContacts.map(c => ({...c, _isGroup: false})),
    ...S.rawGroups.filter(g => g.member_count > 1).map(g => ({...g, _isGroup: true})),
  ].filter(c => !linked.has(c.id));

  let candidates;
  if (q) {
    candidates = allChats
      .filter(c =>
        (c.name||'').toLowerCase().includes(q) ||
        (c.handle||'').toLowerCase().includes(q) ||
        (c.network||'').toLowerCase().includes(q)
      )
      .map(c => ({ c, score: fuzzyScore(c, q) }))
      .sort((a, b) => b.score - a.score)
      .map(x => x.c);
  } else {
    const withTs = allChats.filter(c => c.days_since !== null).sort((a,b) => a.days_since - b.days_since);
    const noTs   = allChats.filter(c => c.days_since === null).sort((a,b) => (a.name||'').localeCompare(b.name||''));
    candidates   = [...withTs, ...noTs];
  }

  if (!candidates.length) {
    res.innerHTML = `<div style="padding:10px 12px;color:var(--text3);font-size:.78rem">No contacts found</div>`;
    res.classList.remove('hidden');
    return;
  }

  res.innerHTML = candidates.map(c => {
    const initials = (c.name||'?').split(' ').map(w=>w[0]).join('').slice(0,2).toUpperCase();
    const av      = c.avatar ? `<img src="${avatarUrl(c.avatar)}" onerror="this.parentElement.innerHTML='${initials}'">` : initials;
    const isGroup = c._isGroup || c.is_group;
    const meta    = isGroup
      ? `${e(c.network)} · ${c.member_count} people`
      : `${e(c.network)}${c.handle ? ' · ' + e(c.handle) : ''}`;
    const groupTag = isGroup ? `<span style="font-family:'DM Mono',monospace;font-size:.58rem;color:var(--purple);background:rgba(167,139,250,.1);border:1px solid rgba(167,139,250,.2);padding:1px 6px;border-radius:4px;margin-left:4px">group</span>` : '';
    return `<div class="link-result-item" onmousedown="linkChat('${personId}','${c.id}')">
      <div class="link-result-av">${av}</div>
      <div class="link-result-info">
        <span class="link-result-name">${e(c.name)}${groupTag}</span>
        <span class="link-result-net">${meta}</span>
      </div>
      <span class="link-result-days">${c.days_since !== null ? c.days_since + 'd' : '—'}</span>
    </div>`;
  }).join('');
  res.classList.remove('hidden');
}

// Hide results when clicking outside
document.addEventListener('click', e => {
  if (!e.target.closest('.link-search-wrap')) {
    document.querySelectorAll('.link-results').forEach(el => el.classList.add('hidden'));
  }
});

function refreshCardSuggestions() {} // no-op

function getLinkedIds() {
  const groupIds = new Set(S.rawGroups.map(g => g.id));
  return new Set(
    getPeopleList().flatMap(p => p.chat_ids.filter(id => !groupIds.has(id)))
  );
}

function fuzzyScore(contact, query) {
  if (!query) return 0;
  const q = query.toLowerCase().trim();
  const n = (contact.name || '').toLowerCase();
  const h = (contact.handle || '').toLowerCase();
  if (n === q || h === q) return 100;
  if (n.startsWith(q) || h.startsWith(q)) return 80;
  if (n.includes(q) || h.includes(q)) return 60;
  const qTokens = q.split(/\s+/);
  const nTokens = n.split(/\s+/);
  const hits = qTokens.filter(qt => nTokens.some(nt => nt.startsWith(qt)));
  if (hits.length) return 40 + (hits.length / qTokens.length) * 20;
  return 0;
}

function renderPeopleList() {
  const el = document.getElementById('people-list');
  if (!el) return;
  const list = S._editPerson ? [S._editPerson] : S.people;
  if (!list.length) { el.innerHTML = ''; return; }

  el.innerHTML = list.map((person, i) => {
    const chipsHtml = person.chat_ids.map(cid => {
      const c = S.rawContacts.find(x => x.id === cid) || S.rawGroups.find(x => x.id === cid);
      if (!c) return '';
      const initials = (c.name||'?').split(' ').map(w=>w[0]).join('').slice(0,2).toUpperCase();
      const av      = c.avatar ? `<img src="${avatarUrl(c.avatar)}" onerror="this.parentElement.innerHTML='${initials}'">` : initials;
      const isGroup = c.is_group || c.member_count > 1;
      const tag     = isGroup ? `<span style="font-family:'DM Mono',monospace;font-size:.55rem;color:var(--purple)">group</span>` : '';
      return `<div class="chat-chip">
        <div class="chat-chip-av">${av}</div>
        <span class="chat-chip-name">${e(c.name)}</span>
        <span class="chat-chip-net">${e(c.network)}</span>
        ${tag}
        <button class="chat-chip-x" onclick="unlinkChat('${person.id}','${cid}')" title="Remove">✕</button>
      </div>`;
    }).join('');

    return `
      <div class="person-card${person.chat_ids.length ? ' has-chats' : ''}" id="pcard-${person.id}">
        <div class="person-header">
          <span class="person-num">${i+1}</span>
          <input class="person-name-input" placeholder="Their name" value="${ea(person.display_name)}"
            oninput="updatePersonName('${person.id}', this.value)"
            onfocus="if(this.value){updatePersonName('${person.id}',this.value)}"
            onkeydown="if(event.key==='Enter')addPerson()">
          <button class="person-del" onclick="removePerson('${person.id}')" title="Remove">✕</button>
        </div>
        ${person.chat_ids.length ? `<div class="person-chats">${chipsHtml}</div>` : ''}
        <div class="person-link-row">
          <div class="link-search-wrap">
            <input class="link-search" placeholder="Search Beeper contacts to link…"
              id="linksearch-${person.id}"
              oninput="renderLinkResults('${person.id}')"
              onfocus="showLinkResults('${person.id}')"
              autocomplete="off">
            <div class="link-results hidden" id="linkresults-${person.id}"></div>
          </div>
        </div>
      </div>`;
  }).join('');
}

function initPeopleSlots() {
  if (!S.people.length) {
    S.people.push({ id: 'p_init_0', display_name: '', chat_ids: [] });
  }
  renderPeopleList();
}

// ════════════════════════════════════════
// EDIT PANEL
// ════════════════════════════════════════
let _editPersonId = null;

async function openAddPanel() {
  _editPersonId = null;
  S._editPerson = { id: 'p_new_' + Date.now(), display_name: '', chat_ids: [] };
  document.getElementById('editPanelTitle').textContent = 'Add person';
  document.getElementById('editPanelDelete').style.display = 'none';
  if (!S.rawContacts.length) await loadRaw();
  _renderEditPanelCard();
  document.getElementById('editPanel').classList.add('open');
  document.getElementById('editOverlay').classList.add('open');
  document.getElementById('app').classList.add('panel-open');
  setTimeout(() => document.querySelector('#ep-name')?.focus(), 150);
}

async function openEditPanel(personId) {
  const p = (S.settings.people || []).find(p => p.id === personId);
  if (!p) return;
  _editPersonId = personId;
  S._editPerson = deepClone(p);
  document.getElementById('editPanelTitle').textContent = 'Edit ' + (p.display_name || 'person');
  document.getElementById('editPanelDelete').style.display = 'block';
  if (!S.rawContacts.length) await loadRaw();
  _renderEditPanelCard();
  document.getElementById('editPanel').classList.add('open');
  document.getElementById('editOverlay').classList.add('open');
  document.getElementById('app').classList.add('panel-open');
}

function _renderEditPanelCard() {
  const p    = S._editPerson;
  const body = document.getElementById('editPanelBody');

  const chipsHtml = (p.chat_ids || []).map(cid => {
    const c = S.rawContacts.find(x => x.id === cid) || S.rawGroups.find(x => x.id === cid);
    if (!c) return '';
    const ini = (c.name||'?').split(' ').map(w=>w[0]).join('').slice(0,2).toUpperCase();
    const av  = c.avatar ? `<img src="${avatarUrl(c.avatar)}" onerror="this.parentElement.innerHTML='${ini}'">` : ini;
    const tag = (c.is_group || c.member_count > 1) ? `<span style="font-family:'DM Mono',monospace;font-size:.55rem;color:var(--purple)">group</span>` : '';
    return `<div class="chat-chip">
      <div class="chat-chip-av">${av}</div>
      <span class="chat-chip-name">${e(c.name)}</span>
      <span class="chat-chip-net">${e(c.network)}</span>
      ${tag}
      <button class="chat-chip-x" onclick="_epUnlink('${cid}')" title="Remove">✕</button>
    </div>`;
  }).join('');

  body.innerHTML = `
    <label class="ep-label">Name</label>
    <input id="ep-name" placeholder="Their name (e.g. Sarah)"
      value="${ea(p.display_name)}"
      oninput="S._editPerson.display_name=this.value;document.getElementById('editPanelTitle').textContent=this.value||(_editPersonId?'Edit person':'Add person')">
    <label class="ep-label" style="margin-top:20px">Link chats</label>
    <div class="ep-search-wrap">
      <input id="ep-search" placeholder="Search contacts to link…"
        oninput="_epSearch()" onfocus="_epSearch();_epPositionDropdown()" autocomplete="off">
    </div>
    ${chipsHtml ? `<label class="ep-label" style="margin-top:20px">Linked chats</label><div class="ep-chips">${chipsHtml}</div>` : '<p style="margin-top:10px;font-size:.8rem;color:var(--text3);font-family:\'DM Sans\',sans-serif;line-height:1.6">Search above to link Instagram, WhatsApp, or group chats.</p>'}`;

  // Clear search when re-rendering
  document.getElementById('ep-results')?.classList.add('hidden');
  // Re-attach focus listener for dropdown positioning
  setTimeout(() => {
    const s = document.getElementById('ep-search');
    if (s) { s.addEventListener('focus', _epPositionDropdown); s.addEventListener('input', _epPositionDropdown); }
  }, 0);
}

function _epPositionDropdown() {
  const inp = document.getElementById('ep-search');
  const res = document.getElementById('ep-results');
  if (!inp || !res) return;
  const rect = inp.getBoundingClientRect();
  res.style.top   = (rect.bottom + 4) + 'px';
  res.style.left  = rect.left + 'px';
  res.style.width = rect.width + 'px';
}

function _epSearch() {
  const inp  = document.getElementById('ep-search');
  const res  = document.getElementById('ep-results');
  const p    = S._editPerson;
  if (!inp || !res || !p) return;

  const q       = inp.value.toLowerCase().trim();
  const myIds   = new Set(p.chat_ids);
  const takenDMs = new Set(
    (S.settings.people || [])
      .filter(x => x.id !== p.id)
      .flatMap(x => x.chat_ids)
      .filter(id => !S.rawGroups.find(g => g.id === id))
  );

  let candidates = [
    ...S.rawContacts.map(c => ({...c, _isGroup: false})),
    ...S.rawGroups.filter(g => g.member_count > 1).map(g => ({...g, _isGroup: true})),
  ].filter(c => !takenDMs.has(c.id) && !myIds.has(c.id));

  if (q) {
    candidates = candidates
      .filter(c => (c.name||'').toLowerCase().includes(q) || (c.handle||'').toLowerCase().includes(q) || (c.network||'').toLowerCase().includes(q))
      .map(c => ({c, score: fuzzyScore(c, q)}))
      .sort((a,b) => b.score - a.score)
      .map(x => x.c);
  } else {
    const withTs = candidates.filter(c => c.days_since !== null).sort((a,b) => a.days_since - b.days_since);
    const noTs   = candidates.filter(c => c.days_since === null).sort((a,b) => (a.name||'').localeCompare(b.name||''));
    candidates   = [...withTs, ...noTs];
  }

  if (!candidates.length) {
    res.innerHTML = `<div style="padding:10px 12px;color:var(--text3);font-size:.78rem">No contacts found</div>`;
    _epPositionDropdown();
    res.classList.remove('hidden');
    return;
  }

  res.innerHTML = candidates.map(c => {
    const ini     = (c.name||'?').split(' ').map(w=>w[0]).join('').slice(0,2).toUpperCase();
    const av      = c.avatar ? `<img src="${avatarUrl(c.avatar)}" onerror="this.parentElement.innerHTML='${ini}'">` : ini;
    const isGroup = c._isGroup || c.is_group;
    const meta    = isGroup ? `${e(c.network)} · ${c.member_count} people` : `${e(c.network)}${c.handle ? ' · '+e(c.handle) : ''}`;
    const gtag    = isGroup ? `<span style="font-family:'DM Mono',monospace;font-size:.58rem;color:var(--purple);background:rgba(167,139,250,.1);border:1px solid rgba(167,139,250,.2);padding:1px 6px;border-radius:4px;margin-left:4px">group</span>` : '';
    return `<div class="link-result-item" onmousedown="_epLink('${c.id}')">
      <div class="link-result-av">${av}</div>
      <div class="link-result-info">
        <span class="link-result-name">${e(c.name)}${gtag}</span>
        <span class="link-result-net">${meta}</span>
      </div>
      <span class="link-result-days">${c.days_since !== null ? c.days_since+'d' : '—'}</span>
    </div>`;
  }).join('');
  _epPositionDropdown();
  res.classList.remove('hidden');
}

function _epLink(chatId) {
  const p = S._editPerson;
  if (!p || p.chat_ids.includes(chatId)) return;
  p.chat_ids.push(chatId);
  document.getElementById('ep-search').value = '';
  document.getElementById('ep-results').classList.add('hidden');
  // Only re-render the body (name + chips), not the search section
  _renderEditPanelCard();
  // Re-focus search
  setTimeout(() => document.getElementById('ep-search')?.focus(), 50);
}

function _epUnlink(chatId) {
  const p = S._editPerson;
  if (!p) return;
  p.chat_ids = p.chat_ids.filter(id => id !== chatId);
  _renderEditPanelCard();
}

function closeEditPanel() {
  document.getElementById('editPanel').classList.remove('open');
  document.getElementById('editOverlay').classList.remove('open');
  document.getElementById('app').classList.remove('panel-open');
  S._editPerson = null;
}

async function saveEditPerson() {
  const p = S._editPerson;
  if (!p || !p.display_name.trim()) {
    const inp = document.getElementById('ep-name');
    if (inp) { inp.focus(); inp.style.borderColor='var(--red)'; setTimeout(()=>inp.style.borderColor='',1000); }
    return;
  }
  const people = deepClone(S.settings.people || []);
  if (_editPersonId) {
    const idx = people.findIndex(x => x.id === _editPersonId);
    if (idx >= 0) people[idx] = p; else people.push(p);
  } else {
    people.push(p);
  }
  const settings = { ...S.settings, people, setup_complete: true };
  await fetch('/api/settings', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(settings) });
  S.settings = settings;
  closeEditPanel();
  await loadPeople(true);
}

async function deleteEditPerson() {
  if (!_editPersonId) { closeEditPanel(); return; }
  const people = (S.settings.people || []).filter(p => p.id !== _editPersonId);
  const settings = { ...S.settings, people };
  await fetch('/api/settings', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(settings) });
  S.settings = settings;
  closeEditPanel();
  await loadPeople(true);
}

async function openSettings() { await openAddPanel(); }

// Close ep-results when clicking outside
document.addEventListener('click', ev => {
  if (!ev.target.closest('#ep-search') && !ev.target.closest('#ep-results')) {
    document.getElementById('ep-results')?.classList.add('hidden');
  }
});

// ════════════════════════════════════════
// DASHBOARD
// ════════════════════════════════════════
async function loadPeople(bustCache = false) {
  document.getElementById('refreshBtn').classList.add('loading');
  try {
    const url = bustCache ? '/api/people?bust=1' : '/api/people';
    const r = await fetch(url);
    const d = await r.json();
    if (d.error) { showError(d.error); return; }
    S.allPeople = d.people || [];

    checkOverdueNotifications();

    updateStats();
    render();
    document.getElementById('statsBar').style.display = 'flex';
  } catch { showError('Could not reach app.py. Is it still running?'); }
  finally { document.getElementById('refreshBtn').classList.remove('loading'); }
}

function updateStats() {
  const w = S.allPeople.filter(p => p.days_since !== null);
  document.getElementById('statTotal').textContent   = S.allPeople.length;
  document.getElementById('statOverdue').textContent = w.filter(p => p.days_since >= 14).length;
  document.getElementById('statFresh').textContent   = w.filter(p => p.days_since <= 7).length;
}

function render() {
  const q = document.getElementById('searchInput').value.toLowerCase();
  let people = [...S.allPeople];

  if (!people.length) {
    document.getElementById('mainContent').innerHTML = `
      <div class="empty-state">
        <div class="icon">👋</div>
        <h2>No one added yet</h2>
        <p>Set up the people you want to keep in touch with.</p>
        <button class="btn btn-primary" style="margin-top:20px" onclick="openSettings()">Add people →</button>
      </div>`;
    return;
  }

  if (q) people = people.filter(p => (p.display_name||'').toLowerCase().includes(q));

  // Sort: longest since last texted first, waiting_on_you second, no data last
  people.sort((a, b) => {
    const aD = a.days_since;
    const bD = b.days_since;
    if (aD !== null && bD !== null) return bD - aD;          // both have data — most neglected first
    if (aD !== null) return -1;                               // a has data, b doesn't — a first
    if (bD !== null) return 1;                                // b has data, a doesn't — b first
    if (a.waiting_on_you && !b.waiting_on_you) return -1;    // waiting_on_you before no data
    if (!a.waiting_on_you && b.waiting_on_you) return 1;
    return 0;
  });

  if (!people.length) {
    document.getElementById('mainContent').innerHTML =
      `<div class="empty-state"><div class="icon">🔍</div><h2>No one found</h2><p>Try a different name.</p></div>`;
    return;
  }

  const html = `<div class="people-grid" id="peopleGrid">${people.map(p => pcardHTML(p)).join('')}</div>`;
  document.getElementById('mainContent').innerHTML = html;
  document.querySelectorAll('.pcard').forEach((el, i) => {
    el.style.animationDelay = `${i * 20}ms`;
  });
}

function pcardHTML(p) {
  const initials = (p.display_name||'?').split(' ').map(w=>w[0]).join('').slice(0,2).toUpperCase();
  const av      = p.avatar ? `<img src="${avatarUrl(p.avatar)}" alt="" onerror="this.parentElement.innerHTML='${initials}'">` : initials;
  const urgency = p.urgency || 0;

  let dayLabel, badgeStyle;
  if (p.days_since !== null) {
    dayLabel = p.days_since === 0 ? 'today'
      : p.days_since === 1 ? 'yesterday'
      : `${p.days_since}d ago`;
    badgeStyle = '';
  } else if (p.waiting_on_you) {
    dayLabel   = 'reply?';
    badgeStyle = `background:rgba(167,139,250,.12);color:var(--purple);`;
  } else {
    dayLabel   = '—';
    badgeStyle = '';
  }

  const nets = (p.networks||[]).map(n => `<span class="net-pill">${e(n)}</span>`).join('');

  const groupChats  = (p.linked_chats||[]).filter(c => c.is_group && c.member_count > 1);
  const allMembers  = groupChats.flatMap(c => (c.members||[]).map(m => ({...m, groupName: c.name})));
  const hasGroups   = allMembers.length > 0;

  return `
    <div class="pcard u${urgency}" id="pcard-dash-${e(p.id)}" data-person-id="${e(p.id)}">
      <div class="pcard-top">
        <div class="pcard-av">
          ${av}
          <div class="urgency-ring"></div>
        </div>
        <div class="pcard-info">
          <div class="pcard-name">${e(p.display_name)}</div>
          <div class="pcard-networks">${nets}</div>
        </div>
        <span class="pcard-badge" style="${badgeStyle}">${dayLabel}</span>
        <button class="pcard-edit-btn" onclick="openEditPanel('${e(p.id)}')" title="Edit">✎</button>
      </div>
      ${hasGroups ? `<button class="pcard-expand" onclick="toggleMembers('${e(p.id)}', this)">
        ↓ ${allMembers.length} group member${allMembers.length !== 1 ? 's' : ''}
      </button>
      <div class="pcard-members" id="members-${e(p.id)}" style="display:none">
        ${allMembers.map(m => {
          const mi  = (m.name||'?').split(' ').map(w=>w[0]).join('').slice(0,2).toUpperCase();
          const mav = m.avatar ? `<img src="${avatarUrl(m.avatar)}" onerror="this.parentElement.innerHTML='${mi}'">` : mi;
          return `<div class="pcard-member">
            <div class="pcard-member-av">${mav}</div>
            <span class="pcard-member-name">${e(m.name||'Unknown')}</span>
            ${m.handle ? `<span class="pcard-member-handle">${e(m.handle)}</span>` : ''}
          </div>`;
        }).join('')}
      </div>` : ''}
    </div>`;
}

function toggleMembers(personId, btn) {
  const el = document.getElementById(`members-${personId}`);
  if (!el) return;
  const open = el.style.display !== 'none';
  el.style.display = open ? 'none' : 'flex';
  el.style.flexDirection = 'column';
  btn.textContent = open
    ? `↓ ${el.children.length} group member${el.children.length !== 1 ? 's' : ''}`
    : `↑ hide members`;
}

function showError(msg) {
  document.getElementById('mainContent').innerHTML =
    `<div class="empty-state"><div class="icon">⚠️</div><h2>Connection error</h2><p>${msg}</p></div>`;
}

async function checkStatus() {
  const pill = document.getElementById('statusPill');
  const text = document.getElementById('statusText');
  try {
    const r = await fetch('/api/status');
    if (r.ok) { pill.className='status-pill connected'; text.textContent='beeper connected'; }
    else throw 0;
  } catch { pill.className='status-pill error'; text.textContent='not connected'; }
}

// ════════════════════════════════════════
// CONTACT LOG SEARCH
// ════════════════════════════════════════
async function openLog() {
  document.getElementById('logPanel').classList.add('open');
  document.getElementById('logOverlay').classList.add('open');
  if (!S.rawContacts.length) await loadRaw();
  document.getElementById('logSearchInput').focus();
  renderLog();
}

function closeLog() {
  document.getElementById('logPanel').classList.remove('open');
  document.getElementById('logOverlay').classList.remove('open');
}

function renderLog() {
  const q   = document.getElementById('logSearchInput').value.toLowerCase().trim();
  const el  = document.getElementById('logResults');
  const all = [...S.rawContacts, ...S.rawGroups];

  if (!q) {
    el.innerHTML = '<div class="log-empty">Type to search through all your Beeper contacts.</div>';
    return;
  }

  const matches = all.filter(c =>
    (c.name||'').toLowerCase().includes(q) ||
    (c.handle||'').toLowerCase().includes(q) ||
    (c.network||'').toLowerCase().includes(q)
  ).slice(0, 40);

  if (!matches.length) {
    el.innerHTML = '<div class="log-empty">No contacts found.</div>';
    return;
  }

  el.innerHTML = matches.map(c => {
    const initials = (c.name||'?').split(' ').map(w=>w[0]).join('').slice(0,2).toUpperCase();
    const av   = c.avatar ? `<img src="${avatarUrl(c.avatar)}" onerror="this.parentElement.innerHTML='${initials}'">` : initials;
    const dayLabel = c.days_since === null ? '—'
      : c.days_since === 0 ? 'today'
      : c.days_since === 1 ? 'yesterday'
      : `${c.days_since}d`;
    return `
      <div class="log-item">
        <div class="log-item-av">${av}</div>
        <div class="log-item-info">
          <div class="log-item-name">${e(c.name)}</div>
          <div class="log-item-meta">${e(c.network)}${c.handle ? ' · ' + e(c.handle) : ''}${c.is_group ? ` · ${c.member_count} people` : ''}</div>
        </div>
        <span class="log-item-days">${dayLabel}</span>
      </div>`;
  }).join('');
}



document.getElementById('searchInput').addEventListener('input', render);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeLog(); });
function e(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function ea(s) { return e(s); }
function avatarUrl(raw) {
  if (!raw) return null;
  if (raw.startsWith('file:///') || raw.startsWith('mxc://')) {
    return '/api/avatar?path=' + encodeURIComponent(raw);
  }
  return raw;
}

// ════════════════════════════════════════
// BOOT
// ════════════════════════════════════════
async function boot() {
  await init();
  // If setup mode, load raw contacts and init 5 empty slots
  if (!S.settings.setup_complete) {
    initPeopleSlots();
  }
}
boot();