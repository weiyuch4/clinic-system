/* Admin portal auth — sessionStorage only, zero persistent traces.
   Replaces auth-client.js on admin pages. The token lives only in
   sessionStorage: tab/window close clears it automatically. */
(function () {
  'use strict';

  var KEY = 'clinic_admin_token';
  var _orig = window.fetch.bind(window);
  var _authed = false;

  function getToken()    { return sessionStorage.getItem(KEY); }
  function setToken(t)   { sessionStorage.setItem(KEY, t); }
  function clearToken()  { sessionStorage.removeItem(KEY); }

  function decoded(t) {
    try {
      var b64 = t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      while (b64.length % 4) b64 += '=';
      return JSON.parse(atob(b64));
    } catch (e) { return null; }
  }

  // Validate existing token before doing anything
  var existing = getToken();
  if (existing) {
    var p = decoded(existing);
    if (p && p.exp * 1000 > Date.now()) {
      _authed = true;
    } else {
      clearToken();
    }
  }

  // Patch window.fetch: inject admin token on all /api/* calls
  window.fetch = function (url, opts) {
    opts = opts || {};
    var t = getToken();
    if (t && typeof url === 'string' && url.indexOf('/api/') === 0) {
      var h = Object.assign({}, opts.headers || {});
      h['Authorization'] = 'Bearer ' + t;
      opts = Object.assign({}, opts, { headers: h });
    }
    return _orig(url, opts).then(function (r) {
      if (r.status === 401 && typeof url === 'string' && url.indexOf('/api/') === 0) {
        clearToken();
        _showOverlay('登入已過期，請重新登入');
      }
      return r;
    });
  };

  // Exit: wipe session and close the window (no trace left on clinic PC)
  window.exitAdminMode = function () {
    clearToken();
    var closed = false;
    try { window.close(); closed = window.closed; } catch (e) {}
    if (!closed) location.replace('/');
  };

  function _showOverlay(msg) {
    var o = document.getElementById('adm-overlay');
    if (o) o.style.display = 'flex';
    if (msg) {
      var e = document.getElementById('adm-err');
      if (e) { e.textContent = msg; e.style.display = 'block'; }
    }
  }

  function _hideOverlay() {
    var o = document.getElementById('adm-overlay');
    if (o) o.style.display = 'none';
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (!_authed) _showOverlay();

    var form = document.getElementById('adm-login-form');
    if (!form) return;

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var u   = document.getElementById('adm-u').value.trim();
      var pw  = document.getElementById('adm-p').value;
      var err = document.getElementById('adm-err');
      var btn = form.querySelector('button[type=submit]');
      if (err) err.style.display = 'none';
      if (btn) btn.disabled = true;

      _orig('/api/admin/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: u, password: pw }),
      }).then(function (r) {
        return r.json().then(function (d) { return { ok: r.ok, data: d }; });
      }).then(function (res) {
        if (!res.ok) {
          if (err) { err.textContent = res.data.detail || '登入失敗'; err.style.display = 'block'; }
          if (btn) btn.disabled = false;
          return;
        }
        setToken(res.data.access_token);
        // Reload so the page initialises cleanly with auth in place
        location.reload();
      }).catch(function () {
        if (err) { err.textContent = '網路錯誤，請稍後再試'; err.style.display = 'block'; }
        if (btn) btn.disabled = false;
      });
    });
  });

})();
