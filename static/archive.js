'use strict';

const PAGE_SIZE = 50;
let _offset = 0;
let _total = 0;
let _items = [];
let _sortCol = 'archived_at';
let _sortDir = 'desc';

async function loadArchive(offset = 0) {
  const resp = await fetch(`/api/archive?limit=${PAGE_SIZE}&offset=${offset}`);
  if (!resp.ok) return;
  const data = await resp.json();
  _total = data.total;
  _offset = offset;
  _items = data.items;
  renderTable();
  renderPagination();
  document.getElementById('total-count').textContent = `${_total} archived transcript${_total !== 1 ? 's' : ''}`;
}

function getSorted() {
  const col = _sortCol;
  const dir = _sortDir === 'asc' ? 1 : -1;
  return [..._items].sort((a, b) => {
    let av = a[col], bv = b[col];
    if (av === null || av === undefined) av = col === 'relevance_score' ? -1 : '';
    if (bv === null || bv === undefined) bv = col === 'relevance_score' ? -1 : '';
    if (typeof av === 'string') return dir * av.localeCompare(bv);
    return dir * (av - bv);
  });
}

function renderTable() {
  _currentIds = _items.map(i => i.id);
  const items = getSorted();
  // Update sort indicators on headers
  document.querySelectorAll('th[data-col]').forEach(th => {
    const indicator = th.dataset.col === _sortCol
      ? (_sortDir === 'asc' ? ' ↑' : ' ↓') : '';
    th.textContent = th.dataset.label + indicator;
  });

  const body = document.getElementById('archive-body');
  if (items.length === 0) {
    body.innerHTML = '<tr><td colspan="7" class="empty">No archived transcripts.</td></tr>';
    return;
  }
  body.innerHTML = items.map(item => `
    <tr data-id="${item.id}">
      <td><input type="checkbox" class="row-check" value="${item.id}"></td>
      <td>
        <button class="transcript-btn link-btn" data-id="${item.id}">${esc(item.title)}</button>
        ${item.is_flagged ? '<span class="badge-flag" title="Flagged">★</span>' : ''}
        ${item.is_marked_for_deletion ? '<span class="badge-delete" title="Marked for deletion">🗑</span>' : ''}
        ${item.has_audio ? '<span class="audio-badge" title="Audio available">♪</span>' : ''}
      </td>
      <td>${item.duration ? fmtDuration(item.duration) : '—'}</td>
      <td class="summary-cell">${esc(item.summary || '')}</td>
      <td>${item.relevance_score !== null && item.relevance_score !== undefined ? Math.round(item.relevance_score * 100) + '%' : '—'}</td>
      <td>${item.batch_id ? `<a href="/triage.html?batch=${esc(item.batch_id)}">${esc(item.batch_id.slice(0, 8))}…</a>` : '—'}</td>
      <td>${new Date(item.archived_at * 1000).toLocaleDateString()}</td>
    </tr>
  `).join('');

  document.getElementById('select-all').addEventListener('change', (e) => {
    document.querySelectorAll('.row-check').forEach(cb => { cb.checked = e.target.checked; });
    updateDeleteBtn();
  });
  document.querySelectorAll('.row-check').forEach(cb => {
    cb.addEventListener('change', updateDeleteBtn);
  });
  document.querySelectorAll('.transcript-btn').forEach(btn => {
    btn.addEventListener('click', () => openTranscriptModal(parseInt(btn.dataset.id)));
  });
  updateDeleteBtn();
}

function initSortHeaders() {
  document.querySelectorAll('th[data-col]').forEach(th => {
    th.style.cursor = 'pointer';
    th.addEventListener('click', () => {
      if (_sortCol === th.dataset.col) {
        _sortDir = _sortDir === 'asc' ? 'desc' : 'asc';
      } else {
        _sortCol = th.dataset.col;
        _sortDir = th.dataset.col === 'relevance_score' ? 'desc' : 'asc';
      }
      renderTable();
    });
  });
}

function renderPagination() {
  const el = document.getElementById('pagination');
  const pages = Math.ceil(_total / PAGE_SIZE);
  const currentPage = Math.floor(_offset / PAGE_SIZE);
  if (pages <= 1) { el.innerHTML = ''; return; }
  let html = '';
  for (let i = 0; i < pages; i++) {
    html += `<button class="page-btn ${i === currentPage ? 'active' : ''}" data-offset="${i * PAGE_SIZE}">${i + 1}</button>`;
  }
  el.innerHTML = html;
  el.querySelectorAll('.page-btn').forEach(btn => {
    btn.addEventListener('click', () => loadArchive(parseInt(btn.dataset.offset)));
  });
}

function updateDeleteBtn() {
  const checked = document.querySelectorAll('.row-check:checked');
  const btn = document.getElementById('delete-btn');
  if (checked.length > 0) {
    btn.classList.remove('hidden');
    btn.textContent = `Delete ${checked.length} selected`;
  } else {
    btn.classList.add('hidden');
  }
}

document.getElementById('delete-btn').addEventListener('click', async () => {
  const ids = [...document.querySelectorAll('.row-check:checked')].map(cb => parseInt(cb.value));
  if (!ids.length) return;
  if (!confirm(`Delete ${ids.length} transcript(s)? This cannot be undone.`)) return;
  const resp = await fetch('/api/archive/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids }),
  });
  if (resp.ok) loadArchive(_offset);
});

// ── Transcript modal ──────────────────────────────────────────────────────────

async function openTranscriptModal(id) {
  try {
    const resp = await fetch(`/api/archive/${id}`);
    if (!resp.ok) throw new Error('Could not load transcript');
    const data = await resp.json();
    showModal(data);
  } catch (e) {
    alert('Error: ' + e.message);
  }
}

function showModal(data) {
  const existing = document.getElementById('transcript-modal');
  if (existing) existing.remove();

  const backdrop = document.createElement('div');
  backdrop.className = 'modal-backdrop';
  backdrop.id = 'transcript-modal';

  const duration = data.duration ? fmtDuration(data.duration) : '';
  const wordCount = data.full_text ? data.full_text.split(/\s+/).filter(Boolean).length : 0;

  backdrop.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-header">
        <div class="modal-title">
          <a href="${esc(data.youtube_url)}" target="_blank" rel="noopener">${esc(data.title)}</a>
        </div>
        <div class="modal-actions">
          <button class="btn-copy" id="copy-btn">Copy text</button>
          <button class="modal-close" id="modal-close" aria-label="Close">×</button>
        </div>
      </div>
      <div class="modal-body">
        <div class="transcript-meta">
          ${duration ? duration + ' · ' : ''}${wordCount.toLocaleString()} words
        </div>
        <div class="transcript-text">${esc(data.full_text || '')}</div>
      </div>
    </div>
  `;

  document.body.appendChild(backdrop);

  document.getElementById('modal-close').addEventListener('click', closeModal);
  backdrop.addEventListener('click', (e) => { if (e.target === backdrop) closeModal(); });
  document.addEventListener('keydown', onModalKey);

  document.getElementById('copy-btn').addEventListener('click', () => {
    navigator.clipboard.writeText(data.full_text || '').then(() => {
      const btn = document.getElementById('copy-btn');
      btn.textContent = 'Copied!';
      btn.classList.add('copied');
      setTimeout(() => { btn.textContent = 'Copy text'; btn.classList.remove('copied'); }, 2000);
    });
  });
}

function closeModal() {
  const modal = document.getElementById('transcript-modal');
  if (modal) modal.remove();
  document.removeEventListener('keydown', onModalKey);
}

function onModalKey(e) {
  if (e.key === 'Escape') closeModal();
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function esc(str) {
  return String(str || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function fmtDuration(secs) {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

// ── Archive scoring ───────────────────────────────────────────────────────────

let _scoreTimer = null;
let _currentIds = [];

document.getElementById('score-btn').addEventListener('click', async () => {
  const criteria = document.getElementById('score-criteria').value.trim();
  if (!criteria) { alert('Enter filter criteria first.'); return; }
  if (!_currentIds.length) return;

  const btn = document.getElementById('score-btn');
  const status = document.getElementById('score-status');
  btn.disabled = true;
  status.textContent = `Scoring ${_currentIds.length} transcripts…`;
  status.classList.remove('hidden');

  try {
    const resp = await fetch('/api/archive/score', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ criteria, ids: _currentIds }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'Failed to start');
    localStorage.setItem('ytqueue_score_criteria', criteria);
    pollScoreStatus();
  } catch (e) {
    status.textContent = 'Error: ' + e.message;
    btn.disabled = false;
  }
});

function pollScoreStatus() {
  if (_scoreTimer) clearInterval(_scoreTimer);
  _scoreTimer = setInterval(async () => {
    try {
      const resp = await fetch('/api/archive/score/status');
      const data = await resp.json();
      if (!data.running) {
        clearInterval(_scoreTimer);
        _scoreTimer = null;
        document.getElementById('score-btn').disabled = false;
        const status = document.getElementById('score-status');
        status.textContent = 'Done';
        setTimeout(() => status.classList.add('hidden'), 3000);
        updateScoreCriteriaLabel(localStorage.getItem('ytqueue_score_criteria') || '');
        loadArchive(_offset);
      }
    } catch (e) {
      console.warn('Score poll error:', e);
    }
  }, 2500);
}

initSortHeaders();
restoreScoreCriteria();
loadArchive();

function restoreScoreCriteria() {
  const saved = localStorage.getItem('ytqueue_score_criteria');
  if (saved) {
    document.getElementById('score-criteria').value = saved;
    updateScoreCriteriaLabel(saved);
  }
}

function updateScoreCriteriaLabel(criteria) {
  const el = document.getElementById('score-criteria-label');
  if (el) el.textContent = criteria ? `"${criteria}"` : '';
}
