(function () {
  'use strict';

  var SERVER = '__SERVER__';

  // Must be on a YouTube playlist page
  if (
    !location.hostname.includes('youtube.com') ||
    !location.search.includes('list=')
  ) {
    alert('yt-queue: Navigate to a YouTube playlist page first (e.g. Watch Later, a channel playlist, or any ?list= URL).');
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

  // Method 1: ytInitialData — covers all videos loaded into the page
  try {
    var raw = JSON.stringify(window.ytInitialData);
    var re = /"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"/g;
    var m;
    while ((m = re.exec(raw)) !== null) addId(m[1]);
  } catch (e) {}

  // Method 2: DOM links — fallback / supplement
  try {
    var links = document.querySelectorAll('a[href*="watch?v="]');
    for (var i = 0; i < links.length; i++) {
      var dm = links[i].href.match(/[?&]v=([A-Za-z0-9_-]{11})/);
      if (dm) addId(dm[1]);
    }
  } catch (e) {}

  if (ids.length === 0) {
    alert('yt-queue: No videos found on this page.\n\nTry scrolling down to load more videos, then run again.');
    return;
  }

  // ── Prompt for criteria ─────────────────────────────────────────────────────

  var criteria = prompt(
    'yt-queue: Found ' + ids.length + ' video' + (ids.length !== 1 ? 's' : '') + '.\n\n' +
    'Filter criteria (optional — leave blank to skip relevance scoring):',
    ''
  );
  if (criteria === null) return; // user cancelled

  // ── Submit ──────────────────────────────────────────────────────────────────

  var urls = ids.map(function (id) {
    return 'https://www.youtube.com/watch?v=' + id;
  });

  fetch(SERVER + '/api/batches', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ urls: urls, filter_criteria: criteria }),
  })
    .then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || r.status); });
      return r.json();
    })
    .then(function (data) {
      window.open(SERVER + '/triage.html?batch=' + data.batch_id, 'ytqueue');
    })
    .catch(function (e) {
      alert('yt-queue: Submission failed — ' + e.message + '\n\nIs the server running at ' + SERVER + '?');
    });
})();
