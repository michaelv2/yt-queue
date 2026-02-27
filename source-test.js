(function () {
  'use strict';
  var SERVER = '__SERVER__';
  if (!location.hostname.includes('youtube.com') || !location.search.includes('list=')) {
    alert('yt-queue (dry run): Navigate to a YouTube playlist page first (URL must contain list=).');
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
    var links = document.querySelectorAll('a[href*="watch?v="]');
    for (var i = 0; i < links.length; i++) {
      var dm = links[i].href.match(/[?&]v=([A-Za-z0-9_-]{11})/);
      if (dm) addId(dm[1]);
    }
  } catch (e) {}
  if (ids.length === 0) {
    alert('yt-queue (dry run): No videos found. Try scrolling down to load more, then run again.');
    return;
  }
  location.href = SERVER + '/preview.html?ids=' + ids.join(',');
})();
