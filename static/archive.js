'use strict';

const PAGE_SIZE = 50;
let _offset = 0;
let _total = 0;
let _items = [];
let _sortCol = 'archived_at';
let _sortDir = 'desc';
let _categoryFilter = '';
let _tagFilter = '';
let _searchQuery = '';

async function loadArchive(offset = 0) {
  const params = new URLSearchParams({ limit: PAGE_SIZE, offset, sort_col: _sortCol, sort_dir: _sortDir });
  if (_searchQuery) params.set('search', _searchQuery);
  if (_categoryFilter) params.set('category', _categoryFilter);
  if (_tagFilter) params.set('tag', _tagFilter);
  const resp = await fetch(`/api/archive?${params}`);
  if (!resp.ok) return;
  const data = await resp.json();
  _total = data.total;
  _offset = offset;
  _items = data.items;
  renderTable();
  renderPagination();
  document.getElementById('total-count').textContent = `${_total} archived transcript${_total !== 1 ? 's' : ''}`;
}

function renderTable() {
  _currentIds = _items.map(i => i.id);
  const items = _items;
  // Update sort indicators on headers
  document.querySelectorAll('th[data-col]').forEach(th => {
    const indicator = th.dataset.col === _sortCol
      ? (_sortDir === 'asc' ? ' ↑' : ' ↓') : '';
    th.textContent = th.dataset.label + indicator;
  });

  const body = document.getElementById('archive-body');
  if (items.length === 0) {
    body.innerHTML = '<tr><td colspan="8" class="empty">No archived transcripts.</td></tr>';
    return;
  }
  body.innerHTML = items.map(item => `
    <tr data-id="${item.id}">
      <td><input type="checkbox" class="row-check" value="${item.id}"></td>
      <td>
        <button class="transcript-btn link-btn" data-id="${item.id}">${esc(item.title)}</button>
        ${item.is_watched ? '<span class="badge-watched" title="Watched">👁</span>' : ''}
        ${item.is_flagged ? '<span class="badge-flag" title="Flagged">★</span>' : ''}
        ${item.is_marked_for_deletion ? '<span class="badge-delete" title="Marked for deletion">🗑</span>' : ''}
        ${item.has_audio ? '<span class="audio-badge" title="Audio available">♪</span>' : ''}
      </td>
      <td>${item.duration ? fmtDuration(item.duration) : '—'}</td>
      <td class="summary-cell">${esc(item.summary || '')}</td>
      <td>${item.category ? `<span class="category-badge" title="${esc(item.category)}">${esc(item.category)}</span>` : '<span class="category-none">—</span>'}</td>
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
      loadArchive(0);
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
  const savedTs = localStorage.getItem('ytqueue_show_timestamps') === 'true';
  const takeawaysBlock = (data.key_takeaways && data.key_takeaways.length > 0)
    ? `<div class="modal-takeaways">
         <h4>Key Takeaways</h4>
         <ul>${data.key_takeaways.map(t => `<li>${esc(t)}</li>`).join('')}</ul>
       </div>`
    : '';

  backdrop.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-header">
        <div class="modal-title">
          <a href="${esc(data.youtube_url)}" target="_blank" rel="noopener">${esc(data.title)}</a>
        </div>
        <div class="modal-actions">
          <label class="ts-toggle-label">
            <input type="checkbox" id="modal-show-timestamps"${savedTs ? ' checked' : ''}> Timestamps
          </label>
          <button class="btn-copy" id="copy-btn">Copy text</button>
          <button class="modal-close" id="modal-close" aria-label="Close">×</button>
        </div>
      </div>
      <div class="modal-body">
        <div class="transcript-meta">
          ${duration ? duration + ' · ' : ''}${wordCount.toLocaleString()} words
        </div>
        ${takeawaysBlock}
        ${data.audio_url ? `<div class="modal-audio-wrap">
          <audio id="modal-audio-player" controls src="${data.audio_url}"></audio>
          <div class="playback-speed" id="playback-speed">
            <button class="speed-btn active" data-speed="1">1x</button>
            <button class="speed-btn" data-speed="1.25">1.25x</button>
            <button class="speed-btn" data-speed="1.5">1.5x</button>
            <button class="speed-btn" data-speed="2">2x</button>
          </div>
        </div>` : ''}
        <div class="transcript-body" id="transcript-body"></div>
      </div>
    </div>
  `;

  document.body.appendChild(backdrop);

  const segments = data.segments || [];
  const fullText = data.full_text || '';
  const audioEl = document.getElementById('modal-audio-player');
  const speedWrap = document.getElementById('playback-speed');
  if (speedWrap && audioEl) {
    speedWrap.addEventListener('click', (e) => {
      const btn = e.target.closest('.speed-btn');
      if (!btn) return;
      audioEl.playbackRate = parseFloat(btn.dataset.speed);
      speedWrap.querySelectorAll('.speed-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    });
  }

  function renderModalBody() {
    const body = document.getElementById('transcript-body');
    body.innerHTML = '';
    const showTs = document.getElementById('modal-show-timestamps').checked;

    if (showTs && segments.length > 0) {
      for (const seg of segments) {
        const div = document.createElement('div');
        div.className = 'segment';

        const timeSpan = document.createElement('span');
        timeSpan.className = 'segment-time' + (audioEl ? ' segment-time-clickable' : '');
        timeSpan.textContent = fmtDuration(seg.start);

        if (audioEl) {
          timeSpan.title = 'Click to seek audio';
          timeSpan.addEventListener('click', () => {
            audioEl.currentTime = seg.start;
            audioEl.play();
          });
        } else {
          const t = Math.floor(seg.start);
          timeSpan.addEventListener('click', () => {
            const sep = data.youtube_url.includes('vimeo.com') ? '#t=' : '&t=';
            window.open(data.youtube_url + sep + t, '_blank', 'noopener');
          });
        }

        div.appendChild(timeSpan);
        div.appendChild(document.createTextNode(seg.text));
        body.appendChild(div);
      }
    } else {
      body.textContent = fullText;
    }
  }

  const checkbox = document.getElementById('modal-show-timestamps');
  checkbox.addEventListener('change', () => {
    localStorage.setItem('ytqueue_show_timestamps', checkbox.checked);
    renderModalBody();
  });
  renderModalBody();

  document.getElementById('modal-close').addEventListener('click', closeModal);
  backdrop.addEventListener('click', (e) => { if (e.target === backdrop) closeModal(); });
  document.addEventListener('keydown', onModalKey);

  document.getElementById('copy-btn').addEventListener('click', () => {
    navigator.clipboard.writeText(fullText).then(() => {
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

  const btn = document.getElementById('score-btn');
  const status = document.getElementById('score-status');
  btn.disabled = true;
  status.textContent = `Scoring ${_total} transcripts…`;
  status.classList.remove('hidden');

  try {
    const resp = await fetch('/api/archive/score', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ criteria }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      const detail = data.detail;
      throw new Error(Array.isArray(detail) ? detail.map(e => e.msg).join(', ') : (detail || 'Failed to start'));
    }
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
        fetchScoreCriteria();
        loadArchive(_offset);
      }
    } catch (e) {
      console.warn('Score poll error:', e);
    }
  }, 2500);
}

initSortHeaders();
fetchScoreCriteria();
loadArchive();
loadCategories();

// ── Search ────────────────────────────────────────────────────────────────────

let _searchTimer = null;
document.getElementById('search-input').addEventListener('input', (e) => {
  clearTimeout(_searchTimer);
  _searchTimer = setTimeout(() => {
    _searchQuery = e.target.value.trim();
    loadArchive(0);
  }, 300);
});

async function fetchScoreCriteria() {
  try {
    const resp = await fetch('/api/archive/score/criteria');
    if (!resp.ok) return;
    const data = await resp.json();
    if (data.label) {
      updateScoreCriteriaLabel(data.label);
    }
  } catch (e) {
    console.warn('Failed to load score criteria:', e);
  }
}

function updateScoreCriteriaLabel(label) {
  const el = document.getElementById('score-criteria-label');
  if (el) el.textContent = label ? `”${label}”` : '';
  const indicator = document.getElementById('score-criteria-indicator');
  if (indicator) {
    indicator.textContent = label ? `Scored against: ${label}` : '';
    indicator.hidden = !label;
  }
}

// ── Categories ────────────────────────────────────────────────────────────────

async function loadCategories() {
  try {
    const resp = await fetch('/api/categories');
    if (!resp.ok) return;
    const cats = await resp.json();
    populateCategoryFilter(cats);
  } catch (e) {
    console.warn('Category load error:', e);
  }
}

function populateCategoryFilter(cats) {
  const sel = document.getElementById('category-filter');
  const current = sel.value;
  sel.innerHTML = '<option value="">All categories</option>';
  if (cats.length > 0) {
    cats.forEach(c => {
      const opt = document.createElement('option');
      opt.value = c.name;
      opt.textContent = c.name;
      sel.appendChild(opt);
    });
    const none = document.createElement('option');
    none.value = '_none_';
    none.textContent = 'Uncategorized';
    sel.appendChild(none);
  }
  if (current) sel.value = current;
}

document.getElementById('category-filter').addEventListener('change', (e) => {
  _categoryFilter = e.target.value;
  loadArchive(0);
});

document.getElementById('tag-filter').addEventListener('change', (e) => {
  _tagFilter = e.target.value;
  loadArchive(0);
});

let _categorizeTimer = null;

document.getElementById('categorize-btn').addEventListener('click', async () => {
  const btn = document.getElementById('categorize-btn');
  const status = document.getElementById('categorize-status');
  btn.disabled = true;
  status.textContent = 'Starting…';
  status.classList.remove('hidden');
  try {
    const resp = await fetch('/api/categories/generate', { method: 'POST' });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || 'Failed to start');
    }
    pollCategorizeStatus();
  } catch (e) {
    status.textContent = 'Error: ' + e.message;
    btn.disabled = false;
  }
});

function pollCategorizeStatus() {
  if (_categorizeTimer) clearInterval(_categorizeTimer);
  _categorizeTimer = setInterval(async () => {
    try {
      const resp = await fetch('/api/categories/status');
      const data = await resp.json();
      const status = document.getElementById('categorize-status');
      if (data.error) {
        clearInterval(_categorizeTimer);
        _categorizeTimer = null;
        status.textContent = 'Error: ' + data.error;
        document.getElementById('categorize-btn').disabled = false;
        return;
      }
      if (data.running) {
        const pct = data.total > 0 ? Math.round(data.done / data.total * 100) : 0;
        status.textContent = data.done === 0
          ? 'Deriving taxonomy…'
          : `Assigning: ${data.done}/${data.total} (${pct}%)`;
      } else {
        clearInterval(_categorizeTimer);
        _categorizeTimer = null;
        status.textContent = 'Done';
        setTimeout(() => status.classList.add('hidden'), 3000);
        document.getElementById('categorize-btn').disabled = false;
        await loadCategories();
        loadArchive(_offset);
      }
    } catch (e) {
      console.warn('Categorize poll error:', e);
    }
  }, 2500);
}
