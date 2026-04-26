'use strict';

const POLL_MS = 1500;
const params  = new URLSearchParams(location.search);

let _batchId   = params.get('batch') || null;
let _pollTimer = null;
let _batch     = null;

// ── Render ─────────────────────────────────────────────────────────────────────

function render(batch) {
  _batch = batch;
  const page = document.getElementById('progress-page');

  const done    = batch.completed + batch.failed;
  const pct     = batch.total > 0 ? Math.round(done / batch.total * 100) : 0;
  const barClass = batch.status === 'complete' ? 'complete' : batch.status === 'failed' ? 'failed' : '';

  // Categorise jobs
  const active  = batch.jobs.filter(j => !['completed','failed','queued','cancelled'].includes(j.status));
  const queued  = batch.jobs.filter(j => j.status === 'queued');
  const done_jobs = batch.jobs.filter(j => j.status === 'completed');
  const failed_jobs = batch.jobs.filter(j => j.status === 'failed');
  const cancelled_jobs = batch.jobs.filter(j => j.status === 'cancelled');

  const isFinished = batch.status === 'complete' || batch.status === 'failed';

  // ── ETA ──────────────────────────────────────────────────────────────────────
  let etaStr = '';
  if (!isFinished && batch.completed > 0 && batch.total > batch.completed) {
    // Rough estimate: seconds per video × remaining
    const remaining = batch.total - done;
    etaStr = `~${remaining} left`;
  }

  // ── Build HTML ────────────────────────────────────────────────────────────────
  let html = '';

  // Completion banner
  if (isFinished) {
    html += `
      <div class="complete-banner">
        <div>
          <h3>${batch.status === 'complete' ? '✓ Batch complete' : '⚠ Batch finished with errors'}</h3>
          <p>${batch.completed} video${batch.completed !== 1 ? 's' : ''} transcribed
          ${batch.failed > 0 ? ` · ${batch.failed} failed` : ''}
          ${batch.skipped > 0 ? ` · ${batch.skipped} skipped (already archived)` : ''}</p>
        </div>
        <a class="btn-primary" href="/triage.html?batch=${esc(batch.batch_id)}">View results →</a>
      </div>`;
  }

  // Hero card
  html += `
    <div class="hero-card">
      <div class="hero-header">
        <div>
          <div class="hero-title">
            <span class="spinner" id="hero-spinner" style="${isFinished ? 'display:none' : ''}"></span>
            Batch <code style="font-size:.9em">${esc(batch.batch_id)}</code>
          </div>
          ${batch.filter_criteria ? `<div class="hero-subtitle">Criteria: ${esc(batch.filter_criteria)}</div>` : ''}
        </div>
        <div class="hero-actions">
          <span class="status-pill ${batch.status}">${batch.status}</span>
          ${!isFinished ? `<a class="btn-primary" href="/triage.html?batch=${esc(batch.batch_id)}" style="font-size:.82rem;padding:6px 14px">View so far →</a>` : ''}
        </div>
      </div>

      <div class="hero-bar-wrap">
        <div class="hero-bar ${barClass}" style="width:${pct}%"></div>
      </div>

      <div class="hero-stats">
        <div class="stat">
          <span class="stat-val">${pct}%</span>
          <span>overall${etaStr ? ' · ' + etaStr : ''}</span>
        </div>
        <div class="stat">
          <span class="stat-val ok">${batch.completed}</span>
          <span>completed</span>
        </div>
        <div class="stat">
          <span class="stat-val">${batch.in_progress}</span>
          <span>in progress</span>
        </div>
        <div class="stat">
          <span class="stat-val dim">${queued.length}</span>
          <span>queued</span>
        </div>
        ${batch.failed > 0 ? `<div class="stat"><span class="stat-val bad">${batch.failed}</span><span>failed</span></div>` : ''}
        ${batch.skipped > 0 ? `<div class="stat"><span class="stat-val dim">${batch.skipped}</span><span>skipped</span></div>` : ''}
        <div class="stat">
          <span class="stat-val">${batch.total}</span>
          <span>total</span>
        </div>
      </div>
    </div>`;

  // Active jobs
  if (active.length > 0) {
    html += `
      <div>
        <div class="section-header">
          <span class="section-title">In progress (${active.length})</span>
        </div>
        <div class="job-rows">
          ${active.map(j => jobRow(j, 'is-active')).join('')}
        </div>
      </div>`;
  }

  // Queue
  if (queued.length > 0) {
    html += `
      <div class="queue-card">
        <div class="section-header">
          <span class="section-title">Up next (${queued.length})</span>
        </div>
        <div class="queue-list">
          ${queued.slice(0, 10).map((j, i) => `
            <div class="queue-item">
              <span class="queue-pos">#${i + 1}</span>
              <span class="queue-id">${esc(j.video_id)}</span>
            </div>`).join('')}
          ${queued.length > 10 ? `<div class="queue-item" style="color:var(--text-muted);font-size:.8rem">+ ${queued.length - 10} more</div>` : ''}
        </div>
      </div>`;
  }

  // Completed jobs (collapsed once there are many)
  if (done_jobs.length > 0) {
    html += `
      <details ${done_jobs.length < 5 ? 'open' : ''}>
        <summary class="section-title" style="cursor:pointer;user-select:none;list-style:none;margin-bottom:10px">
          ▸ Completed (${done_jobs.length})
        </summary>
        <div class="job-rows">
          ${done_jobs.map(j => jobRow(j, 'is-done')).join('')}
        </div>
      </details>`;
  }

  // Failed jobs
  if (failed_jobs.length > 0) {
    html += `
      <div>
        <div class="section-header">
          <span class="section-title" style="color:var(--danger)">Failed (${failed_jobs.length})</span>
        </div>
        <div class="job-rows">
          ${failed_jobs.map(j => jobRow(j, 'is-failed')).join('')}
        </div>
      </div>`;
  }

  // Cancelled jobs
  if (cancelled_jobs.length > 0) {
    html += `
      <details>
        <summary class="section-title" style="cursor:pointer;user-select:none;list-style:none;margin-bottom:10px">
          ▸ Cancelled (${cancelled_jobs.length})
        </summary>
        <div class="job-rows">
          ${cancelled_jobs.map(j => jobRow(j, 'is-cancelled')).join('')}
        </div>
      </details>`;
  }

  page.innerHTML = html;

  // Wire up retry and cancel buttons
  page.querySelectorAll('.retry-btn').forEach(btn => {
    btn.addEventListener('click', () => retryJob(btn.dataset.jobId));
  });
  page.querySelectorAll('.cancel-btn').forEach(btn => {
    btn.addEventListener('click', () => cancelJob(btn.dataset.jobId));
  });
}

function jobRow(job, cls) {
  const pct = Math.round(job.progress * 100);
  const ytUrl = `https://www.youtube.com/watch?v=${esc(job.video_id)}`;
  const title = job.title || job.video_id;

  return `
    <div class="job-item ${cls}">
      <div class="job-status-col">
        <span class="job-badge ${job.status}">${job.status}</span>
        <div class="job-mini-bar-wrap">
          <div class="job-mini-bar" style="width:${pct}%"></div>
        </div>
      </div>
      <div class="job-info-col">
        <div class="job-name">
          <a href="${ytUrl}" target="_blank" rel="noopener">${esc(title)}</a>
        </div>
        <div class="job-meta">
          ${job.duration ? fmtDuration(job.duration) + ' · ' : ''}${pct}%
        </div>
        ${job.error ? `<div class="job-error-text">${esc(job.error)}</div>` : ''}
      </div>
      <div class="job-action-col">
        ${cls === 'is-active' ? `<button class="cancel-btn" data-job-id="${esc(job.id)}" style="font-size:.75rem;border:1px solid var(--border);background:none;color:var(--text-muted);border-radius:3px;padding:3px 8px;cursor:pointer" title="Cancel">✕</button>` : ''}
        ${job.status === 'failed' ? `<button class="retry-btn" data-job-id="${esc(job.id)}" style="font-size:.75rem;border:1px solid var(--danger);background:none;color:var(--danger);border-radius:3px;padding:3px 8px;cursor:pointer">↺ Retry</button>` : ''}
      </div>
    </div>`;
}

// ── Poll ───────────────────────────────────────────────────────────────────────

async function poll() {
  if (!_batchId) return;
  try {
    const resp = await fetch(`/api/batches/${_batchId}`);
    if (!resp.ok) {
      showError(`Server returned ${resp.status}`);
      stopPolling();
      return;
    }
    const batch = await resp.json();
    render(batch);

    if (batch.status === 'complete' || batch.status === 'failed') {
      stopPolling();
      document.title = `✓ Done — ${batch.completed} videos — yt-queue`;
    }
  } catch (e) {
    showError('Could not reach server: ' + e.message);
    stopPolling();
  }
}

function startPolling() {
  stopPolling();
  poll();
  _pollTimer = setInterval(poll, POLL_MS);
}

function stopPolling() {
  if (_pollTimer) clearInterval(_pollTimer);
  _pollTimer = null;
}

// ── Retry / Cancel ────────────────────────────────────────────────────────────

async function retryJob(jobId) {
  try {
    const resp = await fetch(`/api/jobs/${jobId}/retry`, { method: 'POST' });
    if (!resp.ok) {
      const e = await resp.json();
      throw new Error(e.detail || 'Retry failed');
    }
    startPolling();
  } catch (e) {
    alert('Retry error: ' + e.message);
  }
}

async function cancelJob(jobId) {
  try {
    const resp = await fetch(`/api/jobs/${jobId}/cancel`, { method: 'POST' });
    if (!resp.ok) {
      const e = await resp.json();
      throw new Error(e.detail || 'Cancel failed');
    }
  } catch (e) {
    alert('Cancel error: ' + e.message);
  }
}

// ── Init ───────────────────────────────────────────────────────────────────────

function showError(msg) {
  document.getElementById('progress-page').innerHTML =
    `<div class="error-state">⚠ ${esc(msg)}</div>`;
}

if (!_batchId) {
  showIdle();
} else {
  startPolling();
}

function showIdle() {
  document.getElementById('progress-page').innerHTML = `
    <div class="hero-card" style="padding:48px 28px;text-align:center">
      <div style="font-size:1rem;font-weight:600;margin-bottom:10px">No active batch</div>
      <p style="color:var(--text-muted);font-size:0.88rem">
        Use the bookmarklet on any YouTube page to start processing videos,
        or <a href="/">submit URLs directly</a>.
      </p>
    </div>`;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function fmtDuration(secs) {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = Math.floor(secs % 60);
  return h > 0
    ? `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`
    : `${m}:${String(s).padStart(2,'0')}`;
}
