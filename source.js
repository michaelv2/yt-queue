(function () {
  'use strict';

  var SERVER    = '__SERVER__';
  var API_TOKEN = '__API_TOKEN__';
  var VERSION   = '__VERSION__';   // injected; used to detect stale bookmarklets

  if (!location.hostname.includes('youtube.com') && !location.hostname.includes('vimeo.com')) {
    alert('yt-queue: Must be on a YouTube or Vimeo page.');
    return;
  }

  // ── Extract video IDs ───────────────────────────────────────────────────────

  var ids = [];
  var seen = {};

  function addId(id) {
    if (id && id.length === 11 && !seen[id]) {
      seen[id] = true;
      ids.push(id);
    }
  }

  // Playlist / ytInitialData — catches all loaded videos
  try {
    var raw = JSON.stringify(window.ytInitialData);
    var re = /"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"/g;
    var m;
    while ((m = re.exec(raw)) !== null) addId(m[1]);
  } catch (e) {}

  // DOM links (fallback / supplement)
  try {
    document.querySelectorAll('a[href*="watch?v="]').forEach(function (a) {
      var dm = a.href.match(/[?&]v=([A-Za-z0-9_-]{11})/);
      if (dm) addId(dm[1]);
    });
  } catch (e) {}

  // Current single video as final fallback
  try {
    var sv = location.search.match(/[?&]v=([A-Za-z0-9_-]{11})/);
    if (sv) addId(sv[1]);
  } catch (e) {}

  if (ids.length === 0) {
    alert('yt-queue: No videos found on this page.\n\nTry scrolling down to load more, then run again.');
    return;
  }

  // ── OPEN WINDOW FIRST — must be synchronous before any dialog ──────────────
  //   Browsers revoke the user-gesture token after the first dialog (prompt/alert),
  //   so window.open() must happen before prompt().

  var win = window.open(SERVER + '/progress.html', 'ytqueue');

  // ── Criteria prompt ─────────────────────────────────────────────────────────

  var criteria = prompt(
    'yt-queue: Found ' + ids.length + ' video' + (ids.length !== 1 ? 's' : '') + '.\n\n' +
    'Filter criteria (optional — leave blank to skip relevance scoring):',
    ''
  );

  if (criteria === null) {
    // User cancelled — close the window we opened
    if (win && !win.closed) win.close();
    return;
  }

  // ── Submit batch ────────────────────────────────────────────────────────────

  var headers = { 'Content-Type': 'application/json' };
  if (API_TOKEN) headers['Authorization'] = 'Bearer ' + API_TOKEN;

  var urls = ids.map(function (id) { return 'https://www.youtube.com/watch?v=' + id; });

  fetch(SERVER + '/api/batches', {
    method: 'POST',
    headers: headers,
    body: JSON.stringify({ urls: urls, filter_criteria: criteria }),
  })
    .then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || r.status); });
      return r.json();
    })
    .then(function (data) {
      if (win && !win.closed) {
        win.location.replace(SERVER + '/progress.html?batch=' + data.batch_id);
      }
    })
    .catch(function (e) {
      if (win && !win.closed) win.close();
      var msg = 'yt-queue: Submission failed\n\n' + e.message;
      if (String(e.message).includes('401')) {
        msg += '\n\nThe server has authentication enabled.\nSet YTQUEUE_API_TOKEN in your .env and re-drag the bookmarklet.';
      } else {
        msg += '\n\nIs the server running at ' + SERVER + '?';
      }
      alert(msg);
    });
})();
