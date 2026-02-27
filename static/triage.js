'use strict';

const POLL_INTERVAL = 2500;

const params = new URLSearchParams(location.search);
const batchId = params.get('batch');

if (!batchId) {
  document.getElementById('card-grid').innerHTML =
    '<p class="empty">No batch ID provided. <a href="/">Submit a batch</a>.</p>';
}

let _entries = [];
let _pollTimer = null;
let _batchDone = false;

// ── Data loading ──────────────────────────────────────────────────────────────

async function loadTriage() {
  if (!batchId) return;
  try {
    const resp = await fetch(`/api/triage/${batchId}`);
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
  label.textContent = `${batch.completed} / ${batch.total} complete · ${batch.failed} failed · ${batch.in_progress} in progress`;
}

function hideBatchProgress() {
  document.getElementById('batch-progress').classList.add('hidden');
}

// ── Rendering ─────────────────────────────────────────────────────────────────

function getFilteredSorted() {
  const filterVal = document.getElementById('filter-select').value;
  const sortVal = document.getElementById('sort-select').value;

  let items = [..._entries];

  if (filterVal === 'flagged') {
    items = items.filter(e => e.is_flagged);
  } else if (filterVal === 'high') {
    items = items.filter(e => e.relevance_score !== null && e.relevance_score >= 0.7);
  } else if (filterVal === 'medium') {
    items = items.filter(e => e.relevance_score !== null && e.relevance_score >= 0.4);
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

// ── Summarize ─────────────────────────────────────────────────────────────────

let _summarizeTimer = null;

document.getElementById('summarize-btn').addEventListener('click', async () => {
  if (!batchId) return;
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
}

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
