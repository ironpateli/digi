// ── State ──────────────────────────────────────────────────────────────────────
let currentId     = null;
let currentMeeting = null;
let allMeetings   = [];
let carryTaskId   = null;

// ── Utilities ──────────────────────────────────────────────────────────────────
const $ = s => document.querySelector(s);

const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

async function api(url, opts = {}) {
  const r = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...opts });
  if (r.status === 204) return null;
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || 'Something went wrong');
  return d;
}

function toast(msg, type = 'success') {
  const el = Object.assign(document.createElement('div'), {
    className: `toast toast-${type}`,
    textContent: msg
  });
  $('#toastContainer').appendChild(el);
  requestAnimationFrame(() => el.classList.add('show'));
  setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 350); }, 3500);
}

function confirmDialog(msg) {
  return new Promise(resolve => {
    $('#confirmMsg').textContent = msg;
    const dlg = $('#confirmDialog');
    dlg.showModal();
    const done = val => { dlg.close(); cleanup(); resolve(val); };
    const onYes = () => done(true);
    const onNo  = () => done(false);
    const cleanup = () => {
      $('#confirmYes').removeEventListener('click', onYes);
      $('#confirmNo').removeEventListener('click', onNo);
    };
    $('#confirmYes').addEventListener('click', onYes);
    $('#confirmNo').addEventListener('click', onNo);
  });
}

// ── Dashboard ──────────────────────────────────────────────────────────────────
async function load() {
  try {
    const d = await api('/api/dashboard');
    allMeetings = d.meetings;
    $('#openCount').textContent = d.open_tasks;
    $('#meetingList').innerHTML = d.meetings.length
      ? d.meetings.map(m => `
          <button class="meeting ${m.id === currentId ? 'active' : ''}" data-id="${m.id}">
            <div class="meeting-row">
              <b>${esc(m.title)}</b>
              <span class="badge badge-${m.status.replace(/_/g, '-')}">${m.status.replace(/_/g, ' ')}</span>
            </div>
            <small>${m.type.replace(/_/g, ' ')} · ${new Date(m.scheduled_at).toLocaleDateString()}</small>
          </button>`).join('')
      : '<p class="empty-hint">No meetings yet. Create one!</p>';
    document.querySelectorAll('.meeting').forEach(x =>
      x.addEventListener('click', () => show(x.dataset.id)));
    if (currentId) renderDetail();
  } catch (e) {
    toast(e.message, 'error');
  }
}

// ── Meeting detail ─────────────────────────────────────────────────────────────
async function show(id) {
  currentId = id;
  try {
    currentMeeting = await api('/api/meetings/' + id);
    renderDetail();
    load();
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function refreshDetail() {
  currentMeeting = await api('/api/meetings/' + currentId);
  renderDetail();
}

function renderDetail() {
  const m = currentMeeting;
  if (!m) return;

  const tasksHtml = m.tasks.length
    ? m.tasks.map(t => taskCard(t)).join('')
    : '<p class="empty-hint">No approved action items yet.</p>';

  const decsHtml = m.decisions.length
    ? `<ul class="decisions-list">${m.decisions.map(d =>
        `<li>
          <b>${esc(d.title)}</b> — ${esc(d.description)}
          ${d.rationale ? `<br><em class="rationale">${esc(d.rationale)}</em>` : ''}
        </li>`).join('')}</ul>`
    : '<p class="empty-hint">No decisions yet.</p>';

  $('#detail').innerHTML = `
    <div class="detail-header">
      <div>
        <div class="row gap-8 flex-wrap">
          <h2 class="m0">${esc(m.title)}</h2>
          <span class="badge badge-type">${m.type.replace(/_/g, ' ')}</span>
          <span class="badge badge-${m.status.replace(/_/g, '-')}">${m.status.replace(/_/g, ' ')}</span>
        </div>
        <p class="meta">${new Date(m.scheduled_at).toLocaleString()} · ${esc(m.timezone)}</p>
      </div>
      <div class="header-btns">
        <button class="btn-ghost" onclick="openEditNotes()">✏️ Edit notes</button>
        <button class="btn-danger-sm" onclick="deleteMeeting()">🗑 Delete</button>
      </div>
    </div>

    ${m.agenda ? `<p class="agenda-line"><b>Agenda:</b> ${esc(m.agenda)}</p>` : ''}
    ${m.manual_notes ? `<div class="section"><h3>Notes</h3><p class="pre-wrap">${esc(m.manual_notes)}</p></div>` : ''}

    ${m.approved_summary ? `
      <div class="section approved-summary">
        <h3>✅ Approved AI recap</h3>
        <p class="pre-wrap">${esc(m.approved_summary)}</p>
      </div>` : ''}

    <div class="section">
      <div class="section-hd">
        <h3>Action items</h3>
        <span class="badge">${m.tasks.length}</span>
      </div>
      ${tasksHtml}
    </div>

    <div class="section">
      <div class="section-hd">
        <h3>Decisions</h3>
        <span class="badge">${m.decisions.length}</span>
      </div>
      ${decsHtml}
    </div>

    <div class="section">
      <h3>🤖 AI transcript extraction</h3>
      <p class="hint">Paste raw meeting notes or a transcript. AI will extract a summary, decisions, and action items for your review — nothing is saved until you approve.</p>
      <textarea id="transcript" rows="7" placeholder="Paste a meeting transcript here…"></textarea>
      <div class="row gap-8 mt-12">
        <button class="btn-primary" id="extractBtn" onclick="extract()">Generate AI recap</button>
        <span id="aiStatus"></span>
      </div>
      <div id="proposal"></div>
    </div>`;
}

// ── Task card ──────────────────────────────────────────────────────────────────
function taskCard(t) {
  const closed  = ['completed', 'cancelled'].includes(t.status);
  const others  = allMeetings.filter(m => m.id !== currentId);
  const priCls  = `badge-pri-${t.priority}`;
  const statCls = `badge-st-${t.status.replace(/_/g, '-')}`;

  return `
    <div class="task task-${t.status.replace(/_/g, '-')}">
      <div class="task-top">
        <div class="task-info">
          <b>${esc(t.title)}</b>
          <div class="row gap-4 mt-4 flex-wrap">
            <span class="badge ${statCls}">${t.status.replace(/_/g, ' ')}</span>
            <span class="badge ${priCls}">${t.priority}</span>
            ${t.owner_name ? `<span class="badge">👤 ${esc(t.owner_name)}</span>` : ''}
            ${t.due_date   ? `<span class="badge">📅 ${t.due_date}</span>`         : ''}
          </div>
          ${t.description ? `<p class="task-desc">${esc(t.description)}</p>` : ''}
          ${t.outcome     ? `<p class="outcome-line"><b>Outcome:</b> ${esc(t.outcome)}</p>` : ''}
        </div>
        ${!closed ? `
          <div class="task-btns">
            ${t.status !== 'in_progress'
              ? `<button class="btn-sm"          onclick="quickStatus('${t.id}','in_progress')">▶ In progress</button>` : ''}
            ${t.status !== 'blocked'
              ? `<button class="btn-sm btn-warn" onclick="quickStatus('${t.id}','blocked')">⚠ Blocked</button>` : ''}
            <button class="btn-sm btn-success" onclick="closeTask('${t.id}','completed')">✓ Done</button>
            <button class="btn-sm btn-muted"   onclick="closeTask('${t.id}','cancelled')">✕ Cancel</button>
            ${others.length
              ? `<button class="btn-sm btn-carry" onclick="openCarry('${t.id}')">↗ Carry</button>` : ''}
          </div>` : ''}
      </div>
    </div>`;
}

// ── Task actions ───────────────────────────────────────────────────────────────
async function quickStatus(id, status) {
  try {
    await api('/api/tasks/' + id, { method: 'PATCH', body: JSON.stringify({ status }) });
    await refreshDetail();
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function closeTask(id, status) {
  const label   = status === 'completed' ? 'completing' : 'cancelling';
  const outcome = prompt(`Record an outcome before ${label} this task:`);
  if (outcome === null) return;
  if (!outcome.trim()) { toast('An outcome is required to close a task.', 'warn'); return; }
  try {
    await api('/api/tasks/' + id, { method: 'PATCH', body: JSON.stringify({ status, outcome: outcome.trim() }) });
    toast(status === 'completed' ? '✅ Task completed!' : 'Task cancelled.');
    await refreshDetail();
  } catch (e) {
    toast(e.message, 'error');
  }
}

// ── Carry forward ──────────────────────────────────────────────────────────────
function openCarry(taskId) {
  carryTaskId = taskId;
  const others = allMeetings.filter(m => m.id !== currentId);
  $('#carryMeetingSelect').innerHTML = others.map(m =>
    `<option value="${m.id}">${esc(m.title)}</option>`).join('');
  $('#carryNote').value = '';
  $('#carryDialog').showModal();
}

$('#cancelCarry').addEventListener('click', () => $('#carryDialog').close());

$('#carryForm').addEventListener('submit', async e => {
  e.preventDefault();
  try {
    await api('/api/tasks/' + carryTaskId + '/carry-forward', {
      method: 'POST',
      body: JSON.stringify({
        to_meeting_id: $('#carryMeetingSelect').value,
        note: $('#carryNote').value.trim() || null
      })
    });
    $('#carryDialog').close();
    toast('Task carried forward!');
    await refreshDetail();
  } catch (e) {
    toast(e.message, 'error');
  }
});

// ── Delete meeting ─────────────────────────────────────────────────────────────
async function deleteMeeting() {
  const ok = await confirmDialog(
    `Delete "${currentMeeting.title}"? All tasks, decisions, and transcripts will be permanently removed.`
  );
  if (!ok) return;
  try {
    await api('/api/meetings/' + currentId, { method: 'DELETE' });
    toast('Meeting deleted.');
    currentId      = null;
    currentMeeting = null;
    $('#detail').innerHTML = `
      <div class="empty">
        <h2>Select a meeting</h2>
        <p>Explore the seeded sample data or create a meeting and use AI to structure its transcript.</p>
      </div>`;
    load();
  } catch (e) {
    toast(e.message, 'error');
  }
}

// ── Edit notes ─────────────────────────────────────────────────────────────────
function openEditNotes() {
  $('#editAgenda').value = currentMeeting.agenda       || '';
  $('#editNotes').value  = currentMeeting.manual_notes || '';
  $('#editNotesDialog').showModal();
}

$('#cancelEditNotes').addEventListener('click', () => $('#editNotesDialog').close());

$('#editNotesForm').addEventListener('submit', async e => {
  e.preventDefault();
  try {
    const updated = await api('/api/meetings/' + currentId, {
      method: 'PATCH',
      body: JSON.stringify({
        agenda:       $('#editAgenda').value.trim() || null,
        manual_notes: $('#editNotes').value.trim()  || null
      })
    });
    currentMeeting = updated;
    $('#editNotesDialog').close();
    toast('Notes updated!');
    renderDetail();
  } catch (e) {
    toast(e.message, 'error');
  }
});

// ── AI extraction ──────────────────────────────────────────────────────────────
async function extract() {
  const text = $('#transcript').value.trim();
  if (text.length < 20) { toast('Enter at least 20 characters.', 'warn'); return; }
  const btn = $('#extractBtn');
  btn.disabled = true;
  $('#aiStatus').innerHTML = '<span class="spinner"></span> Generating…';
  $('#proposal').innerHTML = '';
  try {
    const r = await api('/api/meetings/' + currentId + '/transcripts', {
      method: 'POST',
      body: JSON.stringify({ content: text })
    });
    $('#aiStatus').textContent = '';
    const p = r.proposal;
    $('#proposal').innerHTML = `
      <div class="proposal-box">
        <h4>🔍 AI Proposal — review before approving</h4>
        <div class="prop-section">
          <b>Summary</b>
          <p>${esc(p.summary)}</p>
        </div>
        ${p.decisions.length ? `
          <div class="prop-section">
            <b>Decisions (${p.decisions.length})</b>
            <ul>${p.decisions.map(d =>
              `<li>${esc(d.title)}${d.rationale ? ` <em>— ${esc(d.rationale)}</em>` : ''}</li>`
            ).join('')}</ul>
          </div>` : ''}
        ${p.action_items.length ? `
          <div class="prop-section">
            <b>Action items (${p.action_items.length})</b>
            <ul>${p.action_items.map(a =>
              `<li>${esc(a.title)}${a.owner ? ` <em>— ${esc(a.owner)}</em>` : ''}
               <span class="badge badge-pri-${a.priority}">${a.priority}</span>
               ${a.due_date ? `<span class="badge">📅 ${a.due_date}</span>` : ''}</li>`
            ).join('')}</ul>
          </div>` : ''}
        ${p.risks_or_open_questions.length ? `
          <div class="prop-section">
            <b>Risks / open questions</b>
            <ul>${p.risks_or_open_questions.map(q => `<li>${esc(q)}</li>`).join('')}</ul>
          </div>` : ''}
        <div class="row gap-8 mt-12">
          <button class="btn-primary" onclick="approve('${r.run_id}')">✓ Approve &amp; save</button>
          <button class="btn-ghost"   onclick="discardProposal()">Discard</button>
        </div>
      </div>`;
  } catch (e) {
    $('#aiStatus').innerHTML = `<span class="notice">${esc(e.message)}</span>`;
  } finally {
    btn.disabled = false;
  }
}

function discardProposal() { $('#proposal').innerHTML = ''; }

async function approve(runId) {
  try {
    currentMeeting = await api('/api/ai-runs/' + runId + '/approve', { method: 'POST' });
    toast('✅ AI recap approved and saved!');
    renderDetail();
    load();
  } catch (e) {
    toast(e.message, 'error');
  }
}

// ── New meeting form ───────────────────────────────────────────────────────────
$('#newMeeting').addEventListener('click', () => $('#meetingDialog').showModal());

$('#cancelMeeting').addEventListener('click', () => {
  $('#meetingDialog').close();
  $('#meetingForm').reset();
});

$('#meetingForm').addEventListener('submit', async e => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    const m = await api('/api/meetings', {
      method: 'POST',
      body: JSON.stringify({
        title:        f.get('title'),
        type:         f.get('type'),
        scheduled_at: new Date(f.get('scheduled_at')).toISOString(),
        agenda:       f.get('agenda') || null
      })
    });
    $('#meetingDialog').close();
    e.target.reset();
    toast('Meeting created!');
    currentId      = m.id;
    currentMeeting = m;
    load();
  } catch (err) {
    toast(err.message, 'error');
  }
});

// ── Boot ───────────────────────────────────────────────────────────────────────
load();
