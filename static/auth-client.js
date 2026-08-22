/* Auth client for pages that don't use _layout.js (index.html, doctor.html).
   - Redirects to /login if no valid token
   - Patches window.fetch to attach Authorization header on /api/* calls
   - Auto-refreshes the token 1 hour before it expires */
(function () {
  'use strict';

  var TOKEN_KEY = 'clinic_token';
  var REFRESH_TIMER = null;

  function getToken() { return localStorage.getItem(TOKEN_KEY); }
  function setToken(t) { localStorage.setItem(TOKEN_KEY, t); }
  function clearToken() { localStorage.removeItem(TOKEN_KEY); }

  function decodeExp(token) {
    try { return JSON.parse(atob(token.split('.')[1])).exp || 0; }
    catch (e) { return 0; }
  }

  function goLogin() {
    clearToken();
    var next = encodeURIComponent(location.pathname + location.search);
    location.href = '/login?next=' + next;
  }

  // ── Fetch patch ─────────────────────────────────────────────────────────────
  var _orig = window.fetch.bind(window);
  window._origFetch = _orig;
  window.fetch = function (url, opts) {
    opts = opts || {};
    var token = getToken();
    if (token && typeof url === 'string' && url.indexOf('/api/') === 0) {
      var hdrs = Object.assign({}, opts.headers || {});
      hdrs['Authorization'] = 'Bearer ' + token;
      opts = Object.assign({}, opts, { headers: hdrs });
    }
    return _orig(url, opts).then(function (r) {
      if (r.status === 401 && typeof url === 'string' && url.indexOf('/api/') === 0) {
        goLogin();
      }
      return r;
    });
  };

  // ── Auto-refresh ─────────────────────────────────────────────────────────────
  function scheduleRefresh(token) {
    if (REFRESH_TIMER) clearTimeout(REFRESH_TIMER);
    var exp = decodeExp(token);
    if (!exp) return;
    var msUntilRefresh = exp * 1000 - Date.now() - 60 * 60 * 1000; // 1h before expiry
    if (msUntilRefresh < 5000) msUntilRefresh = 5000;
    REFRESH_TIMER = setTimeout(doRefresh, msUntilRefresh);
  }

  function doRefresh() {
    _orig('/auth/refresh', { method: 'POST', credentials: 'include' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (d && d.access_token) { setToken(d.access_token); scheduleRefresh(d.access_token); }
        else goLogin();
      })
      .catch(function () { /* network hiccup — will retry on next 401 */ });
  }

  // ── Init ─────────────────────────────────────────────────────────────────────
  var token = getToken();
  if (!token) { goLogin(); return; }

  var exp = decodeExp(token);
  if (exp && exp * 1000 < Date.now()) {
    // Token already expired — try refresh before giving up
    doRefresh();
  } else {
    scheduleRefresh(token);
  }

  // Expose for programmatic use (logout button, etc.)
  window.clinicAuth = {
    setToken: function (t) { setToken(t); scheduleRefresh(t); },
    getToken: getToken,
    logout: function () {
      _orig('/auth/logout', { method: 'POST', credentials: 'include' });
      goLogin();
    },
  };
})();
