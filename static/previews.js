'use strict';

let _total = 0;
let _items = [];
let _batchFilter = '';
let _categoryFilter = '';
let _tagFilter = '';
let _sortCol = 'archived_at';

async function loadPreviews() {
  // First fetch to get total count
  const countParams = new URLSearchParams({ limit: 1, offset: 0 });
  if (_batchFilter) countParams.set('batch_id', _batchFilter);
  if (_categoryFilter) countParams.set('category', _categoryFilter);
  if (_tagFilter) countParams.set('tag', _tagFilter);
  const countResp = await fetch(`/api/archive?${countParams}`);
  if (!countResp.ok) return;
  const countData = await countResp.json();
  _total = countData.total;

  // Fetch all items (API max is 200 per request)
  _items = [];
  for (let off = 0; off < _total; off += 200) {
    const params = new URLSearchParams({
      limit: 200,
      offset: off,
      sort_col: _sortCol,
      sort_dir: _sortCol === 'title' ? 'asc' : 'desc',
    });
    if (_batchFilter) params.set('batch_id', _batchFilter);
    if (_categoryFilter) params.set('category', _categoryFilter);
    if (_tagFilter) params.set('tag', _tagFilter);
    const resp = await fetch(`/api/archive?${params}`);
    if (!resp.ok) break;
    const data = await resp.json();
    _items.push(...data.items);
  }

  renderGrid(_items);
  document.getElementById('total-count').textContent =
    `${_total} video${_total !== 1 ? 's' : ''}`;
}

function renderGrid(items) {
  const grid = document.getElementById('thumb-grid');
  if (items.length === 0) {
    grid.innerHTML = '<p class="empty">No videos found.</p>';
    return;
  }
  grid.innerHTML = items.map(item => {
    const vidId = item.video_id;
    const badges = [];
    if (item.is_flagged) badges.push('<span class="thumb-overlay-badge badge-flag" title="Flagged">&#9733;</span>');
    if (item.is_marked_for_deletion) badges.push('<span class="thumb-overlay-badge badge-delete" title="Marked for deletion">&#128465;</span>');
    if (item.is_watched) badges.push('<span class="thumb-overlay-badge badge-watched" title="Watched">&#128065;</span>');
    if (item.was_previously_deleted) badges.push('<span class="thumb-overlay-badge badge-prev-deleted" title="Previously deleted">&#9888;</span>');
    return `
      <div class="thumb-item" title="${esc(item.title)}">
        <div class="thumb-img-wrap">
          <a href="${esc(item.youtube_url)}" target="_blank" rel="noopener">
            <img src="${item.thumbnail_url ? esc(item.thumbnail_url) : `https://img.youtube.com/vi/${esc(vidId)}/mqdefault.jpg`}"
                 alt="${esc(item.title)}" loading="lazy">
          </a>
          ${badges.length ? `<div class="thumb-overlay-badges">${badges.join('')}</div>` : ''}
        </div>
        <div class="thumb-caption">
          ${item.batch_id ? `<a href="/triage.html?batch=${esc(item.batch_id)}" class="thumb-title">${esc(item.title)}</a>` : `<span class="thumb-title">${esc(item.title)}</span>`}
          <span class="thumb-meta">${item.duration ? fmtDuration(item.duration) : ''}</span>
        </div>
      </div>`;
  }).join('');
}


// ── Batch list ────────────────────────────────────────────────────────────────

async function loadBatches() {
  try {
    const resp = await fetch('/api/batches');
    if (!resp.ok) return;
    const batches = await resp.json();
    const sel = document.getElementById('batch-filter');
    batches.filter(b => b.count > 0).forEach(b => {
      const opt = document.createElement('option');
      opt.value = b.id;
      const date = new Date(b.created_at * 1000).toLocaleDateString();
      opt.textContent = `${b.id.slice(0, 8)}… (${date})`;
      sel.appendChild(opt);
    });
  } catch (e) {
    console.warn('Batch load error:', e);
  }
}

async function loadCategories() {
  try {
    const resp = await fetch('/api/categories');
    if (!resp.ok) return;
    const cats = await resp.json();
    const sel = document.getElementById('category-filter');
    cats.forEach(c => {
      const opt = document.createElement('option');
      opt.value = c.name;
      opt.textContent = c.name;
      sel.appendChild(opt);
    });
  } catch (e) {
    console.warn('Category load error:', e);
  }
}

// ── Filter events ─────────────────────────────────────────────────────────────

document.getElementById('batch-filter').addEventListener('change', (e) => {
  _batchFilter = e.target.value;
  loadPreviews();
});

document.getElementById('category-filter').addEventListener('change', (e) => {
  _categoryFilter = e.target.value;
  loadPreviews();
});

document.getElementById('tag-filter').addEventListener('change', (e) => {
  _tagFilter = e.target.value;
  loadPreviews();
});

document.getElementById('sort-select').addEventListener('change', (e) => {
  _sortCol = e.target.value;
  loadPreviews();
});

// ── Helpers ───────────────────────────────────────────────────────────────────

function esc(str) {
  return String(str || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function fmtDuration(secs) {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

// ── Init ──────────────────────────────────────────────────────────────────────

async function fetchScoreCriteria() {
  const indicator = document.getElementById('score-criteria-indicator');
  if (!indicator) return;
  try {
    const resp = await fetch('/api/archive/score/criteria');
    if (!resp.ok) return;
    const data = await resp.json();
    indicator.textContent = data.label ? `Scored against: ${data.label}` : '';
    indicator.hidden = !data.label;
  } catch (e) {
    console.warn('Failed to load score criteria:', e);
  }
}

loadBatches();
loadCategories();
loadPreviews();
fetchScoreCriteria();
