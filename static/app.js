'use strict';

const POLL_INTERVAL = 2000;
const SS_KEY = 'ytqueue_active_batch';

// ── Batch submission ──────────────────────────────────────────────────────────

const form = document.getElementById('batch-form');
if (form) {
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const rawUrls = document.getElementById('urls').value.trim();
    const criteria = document.getElementById('criteria').value.trim();

    if (!rawUrls) return;

    const urls = rawUrls.split(/[\n,]+/).map(u => u.trim()).filter(Boolean);
    const btn = document.getElementById('submit-btn');
    btn.disabled = true;
    btn.textContent = 'Submitting…';

    try {
      const resp = await fetch('/api/batches', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ urls, filter_criteria: criteria }),
      });
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Submission failed');
      }
      const data = await resp.json();
      sessionStorage.setItem(SS_KEY, JSON.stringify({ batch_id: data.batch_id, criteria }));
      showProgress(data.batch_id);
      startPolling(data.batch_id);
    } catch (err) {
      alert('Error: ' + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Start batch';
    }
  });
}

// ── Progress display ──────────────────────────────────────────────────────────

let _pollTimer = null;

function showProgress(batchId) {
  document.getElementById('progress-section').classList.remove('hidden');
  document.getElementById('batch-form').parentElement.classList.add('has-progress');
}

function startPolling(batchId) {
  if (_pollTimer) clearInterval(_pollTimer);
  _pollTimer = setInterval(() => pollBatch(batchId), POLL_INTERVAL);
  pollBatch(batchId);
}

async function pollBatch(batchId) {
  try {
    const resp = await fetch(`/api/batches/${batchId}`);
    if (!resp.ok) return;
    const batch = await resp.json();
    renderBatch(batch);

    if (batch.status === 'complete' || batch.status === 'failed') {
      clearInterval(_pollTimer);
      _pollTimer = null;
      sessionStorage.removeItem(SS_KEY);
      showTriageLink(batchId, batch.status);
    }
  } catch (e) {
    console.warn('Poll error:', e);
  }
}

function renderBatch(batch) {
  const summary = document.getElementById('batch-summary');
  const pct = batch.total > 0 ? Math.round((batch.completed + batch.failed) / batch.total * 100) : 0;
  summary.innerHTML = `
    <div class="progress-bar-wrap">
      <div class="progress-bar" style="width:${pct}%"></div>
    </div>
    <p class="batch-stats">
      ${batch.completed} completed · ${batch.failed} failed · ${batch.in_progress} in progress · ${batch.total} total
      ${batch.filter_criteria ? `<span class="criteria-tag">criteria: ${esc(batch.filter_criteria)}</span>` : ''}
    </p>
  `;

  const list = document.getElementById('job-list');
  list.innerHTML = batch.jobs.map(job => `
    <div class="job-row job-${job.status}">
      <div class="job-info">
        <span class="job-status-badge">${job.status}</span>
        <span class="job-title">${esc(job.title || job.video_id)}</span>
        ${job.duration ? `<span class="job-duration">${fmtDuration(job.duration)}</span>` : ''}
        ${job.status === 'failed' ? `<button class="retry-btn" data-job-id="${esc(job.id)}">↺ Retry</button>` : ''}
      </div>
      <div class="job-progress-bar-wrap">
        <div class="job-progress-bar" style="width:${Math.round(job.progress * 100)}%"></div>
      </div>
      ${job.error ? `<div class="job-error">${esc(job.error)}</div>` : ''}
    </div>
  `).join('');

  list.querySelectorAll('.retry-btn').forEach(btn => {
    btn.addEventListener('click', () => retryJob(btn.dataset.jobId));
  });
}

function showTriageLink(batchId, status) {
  const wrap = document.getElementById('triage-link-wrap');
  const link = document.getElementById('triage-link');
  if (status === 'complete' || status === 'failed') {
    link.href = `/triage.html?batch=${batchId}`;
    wrap.classList.remove('hidden');
  }
}

// ── Crash recovery ────────────────────────────────────────────────────────────

const saved = sessionStorage.getItem(SS_KEY);
if (saved) {
  try {
    const { batch_id } = JSON.parse(saved);
    showProgress(batch_id);
    startPolling(batch_id);
  } catch (e) {
    sessionStorage.removeItem(SS_KEY);
  }
}

// ── Retry ─────────────────────────────────────────────────────────────────────

async function retryJob(jobId) {
  try {
    const resp = await fetch(`/api/jobs/${jobId}/retry`, { method: 'POST' });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || 'Retry failed');
    }
  } catch (e) {
    alert('Retry error: ' + e.message);
  }
}

// ── History ───────────────────────────────────────────────────────────────────

let _batches = [];

async function loadHistory() {
  try {
    const resp = await fetch('/api/batches?limit=10');
    if (!resp.ok) return;
    _batches = await resp.json();
    renderHistory();
  } catch (e) {
    console.warn('History load error:', e);
  }
}

function renderHistory() {
  const list = document.getElementById('history-list');
  const hideEmpty = document.getElementById('hide-empty-batches').checked;
  const batches = hideEmpty ? _batches.filter(b => b.count > 0) : _batches;

  if (!batches || batches.length === 0) {
    list.innerHTML = '<p class="empty">No batches yet.</p>';
    return;
  }
  list.innerHTML = batches.map(b => `
    <div class="history-batch">
      <div class="history-batch-header">
        <a href="/triage.html?batch=${esc(b.id)}" class="batch-id">${esc(b.id)}</a>
        <span class="history-count">${b.count} video${b.count !== 1 ? 's' : ''}</span>
      </div>
      <ul class="history-items">
        ${b.sample_titles.map(t => `<li>${esc(t)}</li>`).join('')}
        ${b.count > b.sample_titles.length ? `<li class="more">+${b.count - b.sample_titles.length} more</li>` : ''}
      </ul>
    </div>
  `).join('');
}

document.getElementById('hide-empty-batches').addEventListener('change', renderHistory);

loadHistory();
loadBookmarklet();

const BM_VERSION_KEY = 'ytqueue_bm_version';

async function loadBookmarklet() {
  try {
    const [prod, test, verResp] = await Promise.all([
      fetch('/bookmarklet.js'),
      fetch('/bookmarklet-test.js'),
      fetch('/api/bookmarklet-version'),
    ]);

    let currentVersion = null;
    if (verResp.ok) {
      const vd = await verResp.json();
      currentVersion = vd.version;
    }

    if (prod.ok) {
      const code = await prod.text();
      document.getElementById('bookmarklet-link').href = 'javascript:' + code;

      // Detect version embedded in the served code
      const vm = code.match(/var VERSION\s*=\s*'([^']+)'/);
      const servedVersion = vm ? vm[1] : null;

      const savedVersion = localStorage.getItem(BM_VERSION_KEY);
      const staleNotice  = document.getElementById('bookmarklet-stale-notice');

      if (staleNotice && servedVersion && savedVersion && savedVersion !== servedVersion) {
        staleNotice.style.display = 'block';
      }
    }
    if (test.ok) {
      document.getElementById('bookmarklet-test-link').href = 'javascript:' + await test.text();
    }
  } catch (e) {
    console.warn('Bookmarklet load error:', e);
  }
}

// Called by the drag-end handler on the bookmarklet link
function onBookmarkletDragged() {
  try {
    const code = document.getElementById('bookmarklet-link').href.replace('javascript:', '');
    const vm   = code.match(/var VERSION\s*=\s*'([^']+)'/);
    if (vm) localStorage.setItem(BM_VERSION_KEY, vm[1]);
    const n = document.getElementById('bookmarklet-stale-notice');
    if (n) n.style.display = 'none';
  } catch (e) {}
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function esc(str) {
  return String(str)
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
