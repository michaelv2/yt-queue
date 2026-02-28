'use strict';

const POLL_INTERVAL = 2500;

const params = new URLSearchParams(location.search);
const batchId = params.get('batch');
const isGlobalMode = !batchId;

if (isGlobalMode) {
  // Hide batch-specific UI in global mode
  document.getElementById('batch-progress').classList.add('hidden');
  document.getElementById('summarize-btn').classList.add('hidden');
  document.getElementById('summarize-status').classList.add('hidden');
}

let _entries = [];
let _pollTimer = null;
let _batchDone = false;

// ── Data loading ──────────────────────────────────────────────────────────────

async function loadTriage() {
  try {
    const url = batchId ? `/api/triage/${batchId}` : '/api/triage';
    const resp = await fetch(url);
    if (!resp.ok) throw new Error('Failed to load triage data');
    _entries = await resp.json();
    render();
  } catch (e) {
    document.getElementById('card-grid').innerHTML =
      `<p class="empty error">Error: ${esc(e.message)}</p>`;
  }
}

async function pollBatch() {
  if (!batchId) return;
  try {
    const resp = await fetch(`/api/batches/${batchId}`);
    if (!resp.ok) return;
    const batch = await resp.json();
    updateBatchProgress(batch);

    if (batch.status === 'complete' || batch.status === 'failed') {
      clearInterval(_pollTimer);
      _pollTimer = null;
      _batchDone = true;
      hideBatchProgress();
    }

    // Reload triage data each poll while in progress
    await loadTriage();
  } catch (e) {
    console.warn('Poll error:', e);
  }
}

function updateBatchProgress(batch) {
  const wrap = document.getElementById('batch-progress');
  const bar = document.getElementById('batch-prog-bar');
  const label = document.getElementById('batch-prog-label');
  const pct = batch.total > 0
    ? Math.round((batch.completed + batch.failed) / batch.total * 100)
    : 0;
  wrap.classList.remove('hidden');
  bar.style.width = pct + '%';
  const skippedPart = batch.skipped ? ` · ${batch.skipped} skipped` : '';
  label.textContent = `${batch.completed} / ${batch.total} complete · ${batch.failed} failed · ${batch.in_progress} in progress${skippedPart}`;
}

function hideBatchProgress() {
  document.getElementById('batch-progress').classList.add('hidden');
}

// ── Rendering ─────────────────────────────────────────────────────────────────

function getFilteredSorted() {
  const filterVal = document.getElementById('filter-select').value;
  const sortVal = document.getElementById('sort-select').value;

  const categoryVal = document.getElementById('category-filter').value;

  let items = [..._entries];

  if (filterVal === 'flagged') {
    items = items.filter(e => e.is_flagged);
  } else if (filterVal === 'high') {
    items = items.filter(e => e.relevance_score !== null && e.relevance_score >= 0.7);
  } else if (filterVal === 'medium') {
    items = items.filter(e => e.relevance_score !== null && e.relevance_score >= 0.4);
  }

  if (categoryVal === '_none_') {
    items = items.filter(e => !e.category);
  } else if (categoryVal) {
    items = items.filter(e => e.category === categoryVal);
  }

  if (sortVal === 'relevance') {
    items.sort((a, b) => {
      const sa = a.relevance_score ?? -1;
      const sb = b.relevance_score ?? -1;
      return sb - sa;
    });
  } else {
    items.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
  }

  return items;
}

function render() {
  const grid = document.getElementById('card-grid');
  const meta = document.getElementById('triage-meta');

  const items = getFilteredSorted();

  const hasScores = _entries.some(e => e.relevance_score !== null);
  meta.innerHTML = `
    <span class="triage-count">${_entries.length} video${_entries.length !== 1 ? 's' : ''}</span>
    ${hasScores ? '' : '<span class="no-score-note">(no relevance scores — set filter criteria and LLM provider to score)</span>'}
  `;

  if (items.length === 0) {
    grid.innerHTML = '<p class="empty">No videos match the current filter.</p>';
    return;
  }

  grid.innerHTML = items.map(entry => cardHtml(entry)).join('');

  // Attach flag toggle listeners
  grid.querySelectorAll('.flag-btn').forEach(btn => {
    btn.addEventListener('click', () => toggleFlag(parseInt(btn.dataset.id)));
  });

  // Attach transcript view listeners
  grid.querySelectorAll('.transcript-btn').forEach(btn => {
    btn.addEventListener('click', () => openTranscriptModal(parseInt(btn.dataset.id)));
  });

  // Attach deletion mark listeners
  grid.querySelectorAll('.delete-mark-btn').forEach(btn => {
    btn.addEventListener('click', () => toggleMarkDelete(parseInt(btn.dataset.id)));
  });

  // Attach watch toggle listeners
  grid.querySelectorAll('.watch-toggle-btn').forEach(btn => {
    btn.addEventListener('click', () => toggleWatch(parseInt(btn.dataset.id)));
  });
}

function cardHtml(entry) {
  const scoreHtml = entry.relevance_score !== null
    ? `<span class="score-badge score-${scoreClass(entry.relevance_score)}">${Math.round(entry.relevance_score * 100)}%</span>`
    : '';
  const prevDeletedHtml = entry.was_previously_deleted
    ? `<span class="prev-deleted-badge" title="Previously deleted">⚠</span>`
    : '';
  const cardClass = [
    entry.is_flagged ? 'flagged' : '',
    entry.is_marked_for_deletion ? 'marked-for-deletion' : '',
  ].filter(Boolean).join(' ');
  const thumbUrl = `https://img.youtube.com/vi/${esc(entry.video_id)}/mqdefault.jpg`;
  return `
    <div class="card ${cardClass}" data-id="${entry.id}">
      <a href="${esc(entry.youtube_url)}" target="_blank" rel="noopener" class="card-thumb-link">
        <img class="card-thumb" src="${thumbUrl}" alt="${esc(entry.title)}" loading="lazy">
      </a>
      <div class="card-body">
        <div class="card-header">
          ${scoreHtml}
          ${prevDeletedHtml}
          <div class="card-actions">
            <button class="watch-toggle-btn ${entry.is_watched ? 'watched' : ''}"
                    data-id="${entry.id}"
                    title="${entry.is_watched ? 'Mark unwatched' : 'Mark watched'}">
              👁
            </button>
            <button class="flag-btn ${entry.is_flagged ? 'flagged' : ''}"
                    data-id="${entry.id}"
                    title="${entry.is_flagged ? 'Unflag' : 'Flag'}">
              ${entry.is_flagged ? '★' : '☆'}
            </button>
            <button class="delete-mark-btn ${entry.is_marked_for_deletion ? 'marked' : ''}"
                    data-id="${entry.id}"
                    title="${entry.is_marked_for_deletion ? 'Unmark for deletion' : 'Mark for deletion'}">
              🗑
            </button>
          </div>
        </div>
        <h3 class="card-title">
          <a href="${esc(entry.youtube_url)}" target="_blank" rel="noopener">${esc(entry.title)}</a>
        </h3>
        ${entry.duration ? `<span class="card-duration">${fmtDuration(entry.duration)}</span>` : ''}
        <p class="card-summary">${esc(entry.summary) || '<em>No summary available</em>'}</p>
        <div class="card-footer">
          <button class="transcript-btn" data-id="${entry.id}">View transcript</button>
          <a href="${esc(entry.youtube_url)}" target="_blank" rel="noopener" class="watch-btn">Watch →</a>
        </div>
      </div>
    </div>
  `;
}

function scoreClass(score) {
  if (score >= 0.7) return 'high';
  if (score >= 0.4) return 'medium';
  return 'low';
}

// ── Flag + deletion toggles ───────────────────────────────────────────────────

async function toggleFlag(id) {
  const entry = _entries.find(e => e.id === id);
  if (!entry) return;
  const newFlagged = !entry.is_flagged;
  try {
    const resp = await fetch(`/api/archive/${id}/flag?flagged=${newFlagged}`, { method: 'POST' });
    if (!resp.ok) throw new Error('Flag update failed');
    entry.is_flagged = newFlagged;
    render();
  } catch (e) {
    alert('Error: ' + e.message);
  }
}

async function toggleMarkDelete(id) {
  const entry = _entries.find(e => e.id === id);
  if (!entry) return;
  const newMarked = !entry.is_marked_for_deletion;
  try {
    const resp = await fetch(`/api/archive/${id}/mark_delete?marked=${newMarked}`, { method: 'POST' });
    if (!resp.ok) throw new Error('Mark update failed');
    entry.is_marked_for_deletion = newMarked;
    render();
  } catch (e) {
    alert('Error: ' + e.message);
  }
}

async function toggleWatch(id) {
  const entry = _entries.find(e => e.id === id);
  if (!entry) return;
  const newWatched = !entry.is_watched;
  try {
    const resp = await fetch(`/api/archive/${id}/watch?watched=${newWatched}`, { method: 'POST' });
    if (!resp.ok) throw new Error('Watch update failed');
    entry.is_watched = newWatched;
    render();
  } catch (e) {
    alert('Error: ' + e.message);
  }
}

// ── Summarize ─────────────────────────────────────────────────────────────────

let _summarizeTimer = null;

function confirmAction(message) {
  return new Promise(resolve => {
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.id = 'confirm-modal';
    backdrop.innerHTML = `
      <div class="modal modal-sm" role="dialog" aria-modal="true">
        <div class="modal-body">
          <p class="confirm-msg">${esc(message)}</p>
          <div class="confirm-actions">
            <button id="confirm-cancel" class="btn-summarize">Cancel</button>
            <button id="confirm-ok" class="btn-danger">Generate</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(backdrop);
    const close = result => { backdrop.remove(); resolve(result); };
    document.getElementById('confirm-cancel').addEventListener('click', () => close(false));
    document.getElementById('confirm-ok').addEventListener('click', () => close(true));
    backdrop.addEventListener('click', e => { if (e.target === backdrop) close(false); });
  });
}

document.getElementById('summarize-btn').addEventListener('click', async () => {
  if (!batchId) return;
  const ok = await confirmAction(
    'Re-generate summaries for all videos in this batch? Existing summaries will be overwritten.'
  );
  if (!ok) return;
  const btn = document.getElementById('summarize-btn');
  const status = document.getElementById('summarize-status');
  btn.disabled = true;
  status.textContent = 'Starting…';
  status.classList.remove('hidden');
  try {
    const resp = await fetch(`/api/batches/${batchId}/summarize`, { method: 'POST' });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'Failed to start');
    if (data.status === 'already_running') {
      status.textContent = 'Already running…';
    } else {
      status.textContent = `Summarizing ${data.count} video${data.count !== 1 ? 's' : ''}…`;
    }
    pollSummarize();
  } catch (e) {
    status.textContent = 'Error: ' + e.message;
    btn.disabled = false;
  }
});

function pollSummarize() {
  if (_summarizeTimer) clearInterval(_summarizeTimer);
  _summarizeTimer = setInterval(async () => {
    try {
      const resp = await fetch(`/api/batches/${batchId}/summarize`);
      const data = await resp.json();
      await loadTriage();
      if (!data.running) {
        clearInterval(_summarizeTimer);
        _summarizeTimer = null;
        const btn = document.getElementById('summarize-btn');
        const status = document.getElementById('summarize-status');
        btn.disabled = false;
        status.textContent = 'Done';
        setTimeout(() => status.classList.add('hidden'), 3000);
      }
    } catch (e) {
      console.warn('Summarize poll error:', e);
    }
  }, 3000);
}

// ── Controls ──────────────────────────────────────────────────────────────────

document.getElementById('filter-select').addEventListener('change', render);
document.getElementById('sort-select').addEventListener('change', render);
document.getElementById('category-filter').addEventListener('change', render);

async function loadCategories() {
  try {
    const resp = await fetch('/api/categories');
    if (!resp.ok) return;
    const cats = await resp.json();
    const sel = document.getElementById('category-filter');
    const current = sel.value;
    sel.innerHTML = '<option value="">All categories</option>';
    cats.forEach(c => {
      const opt = document.createElement('option');
      opt.value = c.name;
      opt.textContent = c.name;
      sel.appendChild(opt);
    });
    if (cats.length > 0) {
      const none = document.createElement('option');
      none.value = '_none_';
      none.textContent = 'Uncategorized';
      sel.appendChild(none);
    }
    if (current) sel.value = current;
  } catch (e) {
    console.warn('Category load error:', e);
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────

if (batchId) {
  // Check if batch is done first, otherwise poll
  fetch(`/api/batches/${batchId}`)
    .then(r => r.ok ? r.json() : null)
    .then(batch => {
      if (!batch) {
        // Batch not in memory (server restart) — just load triage data
        loadTriage();
        return;
      }
      updateBatchProgress(batch);
      if (batch.status === 'complete' || batch.status === 'failed') {
        _batchDone = true;
        hideBatchProgress();
        loadTriage();
      } else {
        loadTriage();
        _pollTimer = setInterval(pollBatch, POLL_INTERVAL);
      }
    })
    .catch(() => loadTriage());
} else {
  // Global mode — load all archived videos
  loadTriage();
}

loadCategories();

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
        ${data.has_audio ? `<audio id="modal-audio-player" controls src="/api/archive/${data.id}/audio" style="width:100%;margin-bottom:12px;"></audio>` : ''}
        <div class="transcript-body" id="transcript-body"></div>
      </div>
    </div>
  `;

  document.body.appendChild(backdrop);

  const segments = data.segments || [];
  const fullText = data.full_text || '';
  const audioEl = document.getElementById('modal-audio-player');

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
            window.open(data.youtube_url + '&t=' + t, '_blank', 'noopener');
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
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function fmtDuration(secs) {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}
