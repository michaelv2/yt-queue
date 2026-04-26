(function () {
  'use strict';

  var SERVER    = '__SERVER__';
  var API_TOKEN = '__API_TOKEN__';

  if (!location.hostname.includes('youtube.com') && !location.hostname.includes('vimeo.com')) {
    alert('yt-queue (preview): Must be on a YouTube or Vimeo page.');
    return;
  }

  var ids = [], seen = {};
  function addId(id) {
    if (id && id.length === 11 && !seen[id]) { seen[id] = true; ids.push(id); }
  }

  try {
    var raw = JSON.stringify(window.ytInitialData);
    var re = /"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"/g, m;
    while ((m = re.exec(raw)) !== null) addId(m[1]);
  } catch (e) {}

  try {
    document.querySelectorAll('a[href*="watch?v="]').forEach(function (a) {
      var dm = a.href.match(/[?&]v=([A-Za-z0-9_-]{11})/);
      if (dm) addId(dm[1]);
    });
  } catch (e) {}

  try {
    var sv = location.search.match(/[?&]v=([A-Za-z0-9_-]{11})/);
    if (sv) addId(sv[1]);
  } catch (e) {}

  if (ids.length === 0) {
    alert('yt-queue (preview): No videos found. Try scrolling down to load more, then run again.');
    return;
  }

  location.href = SERVER + '/preview.html?ids=' + ids.join(',');
})();
