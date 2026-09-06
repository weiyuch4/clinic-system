/* Shared layout: sidebar, topbar, nurse selector, utilities.
   Every page includes this file and calls Layout.init(config). */
(function () {
  'use strict';

  // Apply saved theme immediately — before any rendering — to prevent flash
  var _theme = localStorage.getItem('theme') || '';
  if (_theme) document.documentElement.setAttribute('data-theme', _theme);

  // Auth guard — redirect to login if no token
  var _token = localStorage.getItem('clinic_token');
  if (!_token && location.pathname !== '/login') {
    location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
  }

  // ── SVG icon library ────────────────────────────────
  var ICONS = {
    home:      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>',
    dashboard: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/></svg>',
    chronic:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/></svg>',
    mspt:      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>',
    hepatitis: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
    ckd:       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
    lab:       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v11m0 0a3 3 0 1 0 6 0m-6 0h6m-6 0H3m12 0h6"/></svg>',
    directory: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    schedule:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>',
    chevron:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>',
    phone:     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 3.07 9.81a19.79 19.79 0 0 1-3.07-8.68A2 2 0 0 1 2 .99h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L6.09 8.91a16 16 0 0 0 6 6"/></svg>',
    refresh:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-3.96"/></svg>',
    search:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>',
    sun:       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><line x1="12" y1="2" x2="12" y2="4"/><line x1="12" y1="20" x2="12" y2="22"/><line x1="4.93" y1="4.93" x2="6.34" y2="6.34"/><line x1="17.66" y1="17.66" x2="19.07" y2="19.07"/><line x1="2" y1="12" x2="4" y2="12"/><line x1="20" y1="12" x2="22" y2="12"/><line x1="6.34" y1="17.66" x2="4.93" y2="19.07"/><line x1="19.07" y1="4.93" x2="17.66" y2="6.34"/></svg>',
    moon:      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>',
    history:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
  };

  // ── Nav structure ────────────────────────────────────
  var MAIN_NAV = [
    { id: 'dashboard', label: '今日總覽',  href: '/dashboard',       badge: false },
    { id: 'chronic',   label: '慢簽追蹤',  href: '/chronic',     badge: true  },
    { id: 'mspt',      label: '代謝症候群', href: '/mspt',        badge: true  },
    { id: 'hepatitis', label: 'B/C型肝炎', href: '/hepatitis',   badge: true  },
    { id: 'ckd',       label: '慢性腎臟病', href: '/ckd',         badge: true  },
    { id: 'lab',       label: '檢驗追蹤',  href: '/lab',         badge: true  },
  ];
  var OTHER_NAV = [
    { id: 'directory', label: '聯絡資訊',  href: '/directory',   badge: false },
    { id: 'schedule',  label: '排班表',    href: '/schedule',    badge: false },
    { id: 'history',   label: '聯絡記錄',  href: '/history',     badge: false },
  ];

  // ── Private state ────────────────────────────────────
  var _activePage   = 'dashboard';
  var _onRefresh    = null;
  var _nurse        = localStorage.getItem('nurse') || '';
  var _pinTarget    = '';   // nurse name waiting for PIN entry
  var _scheduleData = null;
  // _theme declared at top of IIFE for early application

  // ── Utilities (also exposed publicly) ────────────────
  function escHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function localDateStr(d) {
    var D = d || new Date();
    return D.getFullYear() + '-' +
      String(D.getMonth() + 1).padStart(2, '0') + '-' +
      String(D.getDate()).padStart(2, '0');
  }

  function getMondayStr() {
    var d = new Date(), dow = d.getDay();
    var mon = new Date(d);
    mon.setDate(d.getDate() - (dow === 0 ? 6 : dow - 1));
    return localDateStr(mon);
  }

  function addDays(dateStr, n) {
    var d = new Date(dateStr + 'T00:00:00');
    d.setDate(d.getDate() + n);
    return localDateStr(d);
  }

  var _DOW_ZH = ['日','一','二','三','四','五','六'];
  function fmtChineseDate(d) {
    var D = d || new Date();
    return D.getFullYear()+'年'+(D.getMonth()+1)+'月'+D.getDate()+'日（週'+_DOW_ZH[D.getDay()]+'）';
  }

  function _authHeaders(extra) {
    var t = localStorage.getItem('clinic_token');
    var h = Object.assign({}, extra || {});
    if (t) h['Authorization'] = 'Bearer ' + t;
    return h;
  }

  function _handle401(r, url) {
    if (r.status === 401) {
      localStorage.removeItem('clinic_token');
      location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
    }
    return r;
  }

  function apiFetch(url) {
    return fetch(url, { headers: _authHeaders() }).then(function (r) {
      _handle401(r, url);
      if (!r.ok) throw new Error(r.status);
      return r.json();
    });
  }

  // Stale-while-revalidate cache for /api/report.
  // If cached data exists: return it instantly, then fetch fresh in background and call onUpdate(freshData).
  // If cache is very fresh (< 15 s): skip background fetch entirely.
  // If no cache: block until fetch completes (first load of the day).
  var _RPT_MIN_AGE = 15000; // skip background fetch if cache is this fresh
  function getReport(dateStr, onUpdate) {
    var key = 'clinic_rpt_' + (dateStr || localDateStr());
    var cached = null, cacheAge = Infinity;
    try {
      var raw = sessionStorage.getItem(key);
      if (raw) {
        var hit = JSON.parse(raw);
        cached = hit.data;
        cacheAge = Date.now() - hit.ts;
      }
    } catch(e) {}

    function _fetchFresh() {
      return apiFetch('/api/report?report_date=' + (dateStr || localDateStr()))
        .then(function(data) {
          try { sessionStorage.setItem(key, JSON.stringify({ data: data, ts: Date.now() })); } catch(e) {}
          return data;
        });
    }

    if (cached) {
      if (cacheAge >= _RPT_MIN_AGE && onUpdate) {
        // Stale-while-revalidate: serve cache now, refresh silently
        _fetchFresh().then(onUpdate).catch(function() {});
      }
      return Promise.resolve(cached);
    }
    // No cache — must wait for fresh data
    return _fetchFresh();
  }

  // Generic mutating API call (POST / DELETE / PUT)
  function apiAction(method, url, body) {
    return fetch(url, {
      method: method,
      headers: _authHeaders(body ? { 'Content-Type': 'application/json' } : {}),
      body:    body ? JSON.stringify(body) : undefined,
    }).then(function (r) {
      _handle401(r, url);
      if (!r.ok) return r.json().then(function (e) {
        throw new Error(e.detail || ('HTTP ' + r.status));
      });
      return r.status === 204 ? null : r.json().catch(function () { return null; });
    });
  }

  // ── Nurse selector ───────────────────────────────────
  function getNurse() { return _nurse; }

  function _updateAvatar(name) {
    var el = document.getElementById('nurse-av');
    if (el) el.textContent = name ? name.slice(-1) : '?';
  }

  function _updateNurseLbl(name) {
    var el = document.getElementById('nurse-lbl');
    if (el) el.textContent = name || '選擇護理師';
  }

  // ── Theme toggle ─────────────────────────────────────
  function _isDark() {
    return _theme === 'dark' ||
      (!_theme && window.matchMedia && window.matchMedia('(prefers-color-scheme:dark)').matches);
  }

  function _applyTheme(t) {
    _theme = t;
    var root = document.documentElement;
    if (t) { root.setAttribute('data-theme', t); localStorage.setItem('theme', t); }
    else   { root.removeAttribute('data-theme');  localStorage.removeItem('theme'); }
    _updateThemeBtn();
  }

  function _updateThemeBtn() {
    var btn = document.getElementById('btn-theme');
    if (!btn) return;
    var dark = _isDark();
    btn.innerHTML = dark ? ICONS.sun : ICONS.moon;
    btn.title = dark ? '切換淺色模式' : '切換深色模式';
  }

  var CHECK_SVG = '<svg class="nurse-chk" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg>';

  function _initNurseSelector() {
    _updateAvatar(_nurse);
    _updateNurseLbl(_nurse);

    var btn  = document.getElementById('nurse-btn');
    var dd   = document.getElementById('nurse-dd');
    var wrap = document.getElementById('nurse-wrap');
    if (!btn || !dd) return;

    function closeDd() { dd.classList.remove('open'); btn.classList.remove('open'); }
    function openDd()  { dd.classList.add('open');    btn.classList.add('open');    }

    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      dd.classList.contains('open') ? closeDd() : openDd();
    });
    document.addEventListener('click', function (e) {
      if (wrap && !wrap.contains(e.target)) closeDd();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeDd();
    });

    apiFetch('/api/nurses/with-pin-status').then(function (nurses) {
      var optsEl = document.getElementById('nurse-opts');
      if (!optsEl) return;

      function renderOpts() {
        var LOCK = '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>';
        optsEl.innerHTML = nurses.map(function (n) {
          var sel = n.name === _nurse;
          return '<button class="nurse-opt' + (sel ? ' sel' : '') + '" data-nurse="' + escHtml(n.name) + '" data-has-pin="' + (n.has_pin ? '1' : '0') + '" type="button">' +
            '<div class="nurse-opt-av">' + escHtml(n.name.slice(-1)) + '</div>' +
            '<span class="nurse-opt-name">' + escHtml(n.name) + '</span>' +
            (n.has_pin ? '<span class="nurse-pin-icon">' + LOCK + '</span>' : '') +
            CHECK_SVG +
          '</button>';
        }).join('');
        optsEl.querySelectorAll('.nurse-opt').forEach(function (el) {
          el.addEventListener('click', function () {
            var name   = el.dataset.nurse;
            var hasPin = el.dataset.hasPin === '1';
            closeDd();
            if (name === _nurse) return;  // already this nurse, no action needed
            if (!hasPin) {
              // No PIN set — allow free selection with a one-time notice
              _setNurse(name);
              showToast('提示：' + name + ' 尚未設定 PIN，請管理員前往護理師管理設定');
              return;
            }
            _openPinModal(name, renderOpts);
          });
        });
      }

      renderOpts();

      var clearBtn = document.getElementById('nurse-clear');
      if (clearBtn) {
        clearBtn.addEventListener('click', function () {
          _setNurse('');
          renderOpts();
          _updateChangePinBtn();
          closeDd();
        });
      }

      var changePinBtn = document.getElementById('nurse-change-pin');
      if (changePinBtn) {
        changePinBtn.addEventListener('click', function () {
          closeDd();
          _openChangePinModal(_nurse);
        });
      }
    }).catch(function (e) {
      console.error('Failed to load nurse list:', e);
    });
  }

  // ── Nurse identity helpers ───────────────────────────
  function _updateChangePinBtn() {
    var btn = document.getElementById('nurse-change-pin');
    if (btn) btn.style.display = _nurse ? '' : 'none';
  }

  function _setNurse(name) {
    _nurse = name;
    if (name) { localStorage.setItem('nurse', name); }
    else       { localStorage.removeItem('nurse'); }
    _updateAvatar(name);
    _updateNurseLbl(name);
    _renderNurseShift();
    _updateChangePinBtn();
  }

  function _openChangePinModal(name) {
    var lbl  = document.getElementById('change-pin-name');
    var inp1 = document.getElementById('change-pin-old');
    var inp2 = document.getElementById('change-pin-new');
    var err  = document.getElementById('change-pin-err');
    if (lbl)  lbl.textContent = name + '：更改 PIN';
    if (inp1) inp1.value = '';
    if (inp2) inp2.value = '';
    if (err)  { err.textContent = ''; err.style.display = 'none'; }
    showModal('change-pin-modal');
    setTimeout(function () { if (inp1) inp1.focus(); }, 120);
  }

  function _closeChangePinModal() {
    hideModal('change-pin-modal');
  }

  function _submitChangePinModal() {
    var inp1 = document.getElementById('change-pin-old');
    var inp2 = document.getElementById('change-pin-new');
    var err  = document.getElementById('change-pin-err');
    var btn  = document.getElementById('change-pin-submit');
    var oldPin = inp1 ? inp1.value.trim() : '';
    var newPin = inp2 ? inp2.value.trim() : '';
    if (!oldPin || !newPin) return;
    if (!/^\d{4}$/.test(newPin)) {
      if (err) { err.textContent = '新 PIN 必須是 4 位數字'; err.style.display = ''; }
      return;
    }
    if (btn) btn.disabled = true;
    apiAction('POST', '/api/auth/nurse-pin/change', { name: _nurse, old_pin: oldPin, new_pin: newPin })
      .then(function () {
        _closeChangePinModal();
        showToast('PIN 已更新');
      })
      .catch(function (e) {
        if (err) { err.textContent = e.message || '更改失敗'; err.style.display = ''; }
      })
      .finally(function () { if (btn) btn.disabled = false; });
  }

  var _pinOnSuccess = null;

  function _openPinModal(name, onSuccess) {
    _pinTarget    = name;
    _pinOnSuccess = onSuccess || null;
    var lbl = document.getElementById('pin-modal-name');
    var inp = document.getElementById('pin-modal-input');
    var err = document.getElementById('pin-modal-err');
    if (lbl) lbl.textContent = name + ' 的 PIN';
    if (inp) inp.value = '';
    if (err) { err.textContent = ''; err.style.display = 'none'; }
    showModal('pin-modal');
    setTimeout(function () { if (inp) inp.focus(); }, 120);
  }

  function _closePinModal() {
    hideModal('pin-modal');
    _pinTarget    = '';
    _pinOnSuccess = null;
  }

  function _submitPin() {
    var name = _pinTarget;
    var inp  = document.getElementById('pin-modal-input');
    var err  = document.getElementById('pin-modal-err');
    var btn  = document.getElementById('pin-modal-submit');
    var pin  = inp ? inp.value.trim() : '';
    if (!pin || !name) return;
    if (btn) btn.disabled = true;
    apiAction('POST', '/api/auth/nurse-pin', { name: name, pin: pin })
      .then(function () {
        _closePinModal();
        _setNurse(name);
        showToast(name + ' 已登入');
        if (_pinOnSuccess) { _pinOnSuccess(); _pinOnSuccess = null; }
      })
      .catch(function (e) {
        if (err) { err.textContent = e.message || 'PIN 不正確'; err.style.display = ''; }
        if (inp) { inp.value = ''; inp.focus(); }
      })
      .finally(function () { if (btn) btn.disabled = false; });
  }

  // ── Sidebar ──────────────────────────────────────────
  function _navItem(item) {
    var badge = '';
    if (item.badge) {
      var cached = null;
      try { cached = localStorage.getItem('badge_' + item.id); } catch(e) {}
      var n = cached !== null ? parseInt(cached, 10) : NaN;
      var txt = isNaN(n) ? '…' : n;
      var cls = (isNaN(n) || n === 0) ? 'nb zero' : 'nb';
      badge = '<span class="' + cls + '" id="badge-' + item.id + '">' + txt + '</span>';
    }
    return '<a href="' + item.href + '" class="ni' + (item.id === _activePage ? ' on' : '') + '">' +
      (ICONS[item.id] || '') + escHtml(item.label) + badge + '</a>';
  }

  function _renderSidebar() {
    var el = document.getElementById('sidebar');
    if (!el) return;
    el.className = 'sb';
    el.innerHTML =
      '<div class="logo">' +
        '<div class="lm">' + ICONS.home + '</div>' +
        '<span class="ln">診所追蹤</span>' +
      '</div>' +
      '<div class="nl">主選單</div>' +
      MAIN_NAV.map(_navItem).join('') +
      '<div class="nl">其他</div>' +
      OTHER_NAV.map(_navItem).join('') +
      '<div class="sf"></div>' +
      '<div class="promo">' +
        '<div class="ps">我的今日班表</div>' +
        '<div class="pt" id="sb-shift-info">載入中…</div>' +
        '<a href="/schedule" class="pb">查看完整班表</a>' +
      '</div>' +
      '<button class="adm-entry" type="button" onclick="window.open(\'/admin\',\'adm\',\'width=1280,height=840,noopener\')">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>' +
        '管理員後台</button>';
  }

  // ── Topbar ───────────────────────────────────────────
  function _renderTopbar() {
    var el = document.getElementById('topbar');
    if (!el) return;
    el.className = 'tb';
    el.innerHTML =
      '<div class="srch">' + ICONS.search + '<input class="srch-input" type="text" placeholder="搜尋病患姓名或身份證…" autocomplete="off"></div>' +
      '<div class="tbr">' +
        '<span class="lu" id="last-updated"></span>' +
        '<button class="ib" id="btn-theme" title="切換深色模式">' + ICONS.moon + '</button>' +
        '<button class="ib" id="btn-refresh" title="重新整理">' + ICONS.refresh + '</button>' +
        '<div class="nurse-wrap" id="nurse-wrap">' +
          '<button class="nurse-btn" id="nurse-btn" type="button">' +
            '<div class="av" id="nurse-av">?</div>' +
            '<span class="nurse-lbl" id="nurse-lbl">選擇護理師</span>' +
            '<svg class="nurse-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>' +
          '</button>' +
          '<div class="nurse-dd" id="nurse-dd">' +
            '<div class="nurse-dd-hd">值班護理師</div>' +
            '<div class="nurse-opts" id="nurse-opts"></div>' +
            '<div class="nurse-dd-sep"></div>' +
            '<button class="nurse-change-pin" id="nurse-change-pin" type="button" style="display:none">更改我的 PIN</button>' +
            '<button class="nurse-clear" id="nurse-clear" type="button">清除選擇</button>' +
          '</div>' +
        '</div>' +
      '</div>';

    var btn = document.getElementById('btn-refresh');
    if (btn && _onRefresh) btn.addEventListener('click', _onRefresh);
    var themeBtn = document.getElementById('btn-theme');
    if (themeBtn) themeBtn.addEventListener('click', function () { _applyTheme(_isDark() ? 'light' : 'dark'); });
    _updateThemeBtn();
    var srchInput = el.querySelector('.srch-input');
    if (srchInput) {
      srchInput.addEventListener('input', function () {
        var target = document.getElementById('search-input') || document.getElementById('dir-search');
        if (!target) return;
        target.value = srchInput.value;
        target.dispatchEvent(new Event('input', { bubbles: true }));
      });
    }
  }

  // ── Badge / shift updates ────────────────────────────
  function updateBadges(report, bloodCount) {
    function set(id, n) {
      var el = document.getElementById('badge-' + id);
      if (!el) return;
      el.textContent = n;
      el.classList.toggle('zero', n === 0);
      try { localStorage.setItem('badge_' + id, n); } catch(e) {}
    }
    if (!report) return;
    set('chronic',   (report.chronic_prescriptions || []).length);
    set('mspt',      (report.mspt_followups || []).length + (report.mspt_inactive || []).length);
    set('hepatitis', (report.hep_followups  || []).length);
    set('ckd',       (report.ckd_followups  || []).length + (report.ckd_inactive   || []).length);
    if (bloodCount != null) set('lab', bloodCount);
  }

  function updateShiftInfo(text) {
    var el = document.getElementById('sb-shift-info');
    if (el) el.textContent = text || '班表尚未發布';
  }

  function updateLastUpdated() {
    var now = new Date(), el = document.getElementById('last-updated');
    if (el) el.textContent = '更新於 ' +
      String(now.getHours()).padStart(2, '0') + ':' +
      String(now.getMinutes()).padStart(2, '0');
  }

  // ── Error bar ────────────────────────────────────────
  function showError(msg) {
    var el = document.getElementById('error-bar');
    var msgEl = document.getElementById('error-msg');
    if (msgEl) msgEl.textContent = msg || '資料載入失敗';
    if (el) el.style.display = 'flex';
  }
  function hideError() {
    var el = document.getElementById('error-bar');
    if (el) el.style.display = 'none';
  }

  // ── Toast ────────────────────────────────────────────
  function showToast(msg, type) {
    var t = document.createElement('div');
    t.className = 'toast toast-' + (type || 'success');
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(function () { t.classList.add('show'); }, 10);
    setTimeout(function () {
      t.classList.remove('show');
      setTimeout(function () { t.remove(); }, 300);
    }, 3000);
  }

  // ── Modal ────────────────────────────────────────────
  function showModal(id) {
    var el = document.getElementById(id);
    if (!el) return;
    el.style.display = 'flex';
    setTimeout(function () { el.classList.add('open'); }, 10);
  }
  function hideModal(id) {
    var el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('open');
    setTimeout(function () { el.style.display = 'none'; }, 200);
  }

  // ── Collapsible sections ─────────────────────────────
  function initSection(headId, bodyId) {
    var head = document.getElementById(headId);
    var body = document.getElementById(bodyId);
    if (!head || !body) return;
    var chev = head.querySelector('.sec-chevron');
    head.addEventListener('click', function () {
      var collapsed = body.classList.toggle('hidden');
      if (chev) chev.classList.toggle('collapsed', collapsed);
    });
  }

  // ── Patient rendering helpers ─────────────────────────
  var CAT_CLS = { '慢簽':'cat-c','代謝症候群':'cat-m','B肝':'cat-h','C肝':'cat-h','慢性腎臟病':'cat-k' };

  function catChip(category, msptStage) {
    var label = (category === '代謝症候群' && msptStage) ? msptStage : category;
    return '<span class="cat-chip ' + (CAT_CLS[category] || 'cat-c') + '">' + escHtml(label) + '</span>';
  }

  function toRoc(isoDate) {
    var p = String(isoDate || '').split('-');
    if (p.length !== 3) return isoDate || '';
    return (parseInt(p[0]) - 1911) + '/' + p[1] + '/' + p[2];
  }

  function dayBadge(days) {
    var cls = days >= 30 ? 'days-hi' : days >= 15 ? 'days-md' : 'days-lo';
    return '<span class="days ' + cls + '">' + days + '天</span>';
  }

  // Build a standard patient card HTML string.
  // opts: { entry, actions: [{label, cls, key}], tags: [html strings] }
  function patientCard(opts) {
    var e = opts.entry;
    var phone = e.phone || '';
    var mobile = e.mobile || '';
    var contact = [phone, mobile].filter(Boolean).join(' / ');
    var daysN = e.days_overdue || 0;
    var daysCls = daysN >= 30 ? 'days-hi' : daysN >= 15 ? 'days-md' : 'days-lo';

    var tags = (opts.tags || []).join('');
    var actions = (opts.actions || []).map(function (a) {
      return '<button class="act-btn ' + (a.cls || '') + '" data-action="' + escHtml(a.key) + '">' +
        escHtml(a.label) + '</button>';
    }).join('');

    function sd(d) { var s = String(d || ''); return s.length >= 10 ? s.slice(5, 10) : s; }

    var PHONE_SVG = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 3.07 9.81a19.79 19.79 0 0 1-3.07-8.68A2 2 0 0 1 2 .99h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L6.09 8.91a16 16 0 0 0 6 6"/></svg>';

    var metaParts = [];
    if (contact) {
      metaParts.push('<span class="pm-phone">' + PHONE_SVG + escHtml(contact) + '</span>');
    } else {
      metaParts.push('<span class="pm-nophone">' + PHONE_SVG + '無電話</span>');
    }
    if (e.due_date)       metaParts.push('<span>到期&nbsp;' + escHtml(sd(e.due_date)) + '</span>');
    if (e.last_visit_date) metaParts.push('<span>上次&nbsp;' + escHtml(sd(e.last_visit_date)) + '</span>');

    return '<div class="p-card" data-chart="' + escHtml(e.patient.chart_number) + '">' +
      '<div class="p-row1">' +
        '<span class="p-name">' + escHtml(e.patient.name) + '</span>' +
        '<span class="p-chart">#' + escHtml(e.patient.chart_number) + '</span>' +
        '<div class="p-chips">' + catChip(e.category, e.mspt_stage) + (tags ? ' ' + tags : '') + '</div>' +
        '<div class="p-days ' + daysCls + '">' + daysN + '<span class="p-days-u">天</span></div>' +
      '</div>' +
      '<div class="p-row2">' +
        '<div class="pm">' + metaParts.join('<span class="pm-dot">·</span>') + '</div>' +
        '<div class="p-actions">' + actions + '</div>' +
      '</div>' +
    '</div>';
  }

  // Table-row version — returns a <tr> string.
  // opts: { entry, actions:[{label,cls,key}], tags:[html] }
  function patientRow(opts) {
    var e = opts.entry;
    var phone  = e.phone  || (e.patient && e.patient.phone)  || '';
    var mobile = e.mobile || (e.patient && e.patient.mobile) || '';
    var contact = [phone, mobile].filter(Boolean).join(' / ');
    var dobIso = (e.patient && e.patient.birth_date) ? String(e.patient.birth_date).slice(0, 10) : '';
    var dobRoc = dobIso ? toRoc(dobIso) : '';
    var daysN = e.days_overdue || 0;
    var daysCls = daysN >= 30 ? 'days-hi' : daysN >= 15 ? 'days-md' : 'days-lo';
    function sd(d) { var s = String(d || ''); return s.length >= 10 ? s.slice(5) : s; }
    var tags = (opts.tags || []).join('');
    var actions = (opts.actions || []).map(function (a) {
      return '<button class="act-btn ' + (a.cls || '') + '" data-action="' +
        escHtml(a.key) + '">' + escHtml(a.label) + '</button>';
    }).join('');
    var infoParts = [];
    if (contact) infoParts.push('<span class="pr-copy" data-copy="' + escHtml(contact) + '">' + escHtml(contact) + '</span>');
    else         infoParts.push('<span class="pr-noph">無電話</span>');
    if (dobRoc)  infoParts.push('<span class="pr-copy" data-copy="' + escHtml(dobRoc) + '">' + escHtml(dobRoc) + '</span>');
    return '<tr class="pr" data-chart="' + escHtml(e.patient.chart_number) + '">' +
      '<td class="pr-num"><span class="pr-copy" data-copy="' + escHtml(e.patient.chart_number) + '" title="點擊複製身份證">' + escHtml(e.patient.chart_number) + '</span></td>' +
      '<td class="pr-pt"><div class="pr-name"><span class="pr-lab" data-chart="' + escHtml(e.patient.chart_number) + '" data-name="' + escHtml(e.patient.name) + '" title="點擊查看檢驗結果">' + escHtml(e.patient.name) + '</span></div>' +
        '<div class="pr-info">' + infoParts.join(' · ') + '</div>' +
      '</td>' +
      '<td class="pr-cat">' + catChip(e.category, e.mspt_stage) + '</td>' +
      '<td class="pr-days ' + daysCls + '">' + daysN + '天</td>' +
      '<td class="pr-date">' + (e.due_date        ? escHtml(sd(e.due_date))        : '—') + '</td>' +
      '<td class="pr-date">' + (e.last_visit_date ? escHtml(sd(e.last_visit_date)) : '—') + '</td>' +
      '<td class="pr-note">' + (tags ? '<div class="pr-tags">' + tags + '</div>' : '') + '</td>' +
      '<td class="pr-act"><div class="pr-btns">' + actions + '</div></td>' +
    '</tr>';
  }

  // Wrap row-html strings in a full table with standard headers.
  // extraHeaders: optional extra <th> text to insert before the actions column.
  function patientTable(rowsHtml, extraHeaders) {
    var cols = ['身份證','病患','類別','逾期','到期日','上次回診','備註'];
    var extra = extraHeaders || [];
    cols = cols.concat(extra);
    cols.push('');
    var extraCols = extra.map(function () { return '<col style="width:100px">'; }).join('');
    var colgroup = '<colgroup>' +
      '<col style="width:115px">' +   // 身份證
      '<col>' +                        // 病患 — fills remaining space
      '<col style="width:150px">' +   // 類別
      '<col style="width:72px">' +    // 逾期
      '<col style="width:70px">' +    // 到期日
      '<col style="width:70px">' +    // 上次回診
      '<col style="width:100px">' +   // 備註
      extraCols +
      '<col style="width:170px">' +   // 操作
      '</colgroup>';
    return '<div class="ptbl-wrap"><table class="p-table">' + colgroup + '<thead><tr>' +
      cols.map(function (c) {
        if (!c) return '<th></th>';
        var st = c === '逾期' ? 'num' : 'text';
        return '<th class="th-sort" data-sort="' + st + '">' + c + ' <span class="sort-icon">⇅</span></th>';
      }).join('') +
      '</tr></thead><tbody>' + rowsHtml + '</tbody></table></div>';
  }

  // ── Section helpers ──────────────────────────────────
  // Render a collapsible section with a header and list of patient cards.
  // opts: { id, title, entries, renderCard, emptyText }
  function renderSection(opts) {
    var entries = opts.entries || [];
    var countHtml = '<span class="sec-count">' + entries.length + '</span>';
    var chevronHtml = '<span class="sec-chevron">' + ICONS.chevron + '</span>';
    var cards = entries.length
      ? entries.map(opts.renderCard).join('')
      : '<div class="sec-empty">' + (opts.emptyText || '目前沒有記錄') + '</div>';

    return '<div class="sec-head" id="head-' + opts.id + '">' +
        escHtml(opts.title) + countHtml + chevronHtml +
      '</div>' +
      '<div class="sec-body" id="body-' + opts.id + '">' + cards + '</div>';
  }

  // ── Nurse shift sidebar ───────────────────────────────
  var _SLOT_LABEL = { morning: '早診', afternoon: '下午診', evening: '晚診' };

  function _renderNurseShift() {
    var el = document.getElementById('sb-shift-info');
    if (!el) return;
    if (!_nurse) {
      el.innerHTML = '<span style="font-size:12px;opacity:.5">請先選擇護理師</span>';
      return;
    }
    if (!_scheduleData || !_scheduleData.published) {
      el.innerHTML = '<span style="font-size:12px;opacity:.5">班表尚未發布</span>';
      return;
    }
    var today = localDateStr();
    var mine = (_scheduleData.shifts || []).filter(function (s) {
      return s.shift_date === today && s.nurse === _nurse;
    });
    if (!mine.length) {
      el.innerHTML = '<span style="font-size:12px;opacity:.5">今日無排班</span>';
      return;
    }
    el.innerHTML = mine.map(function (s) {
      return '<div class="promo-slot">' +
        '<div class="promo-slot-label">' + (_SLOT_LABEL[s.slot] || s.slot) + '</div>' +
        '<div class="promo-slot-time">' + s.start_time + ' – ' + s.end_time + '</div>' +
      '</div>';
    }).join('');
  }

  function loadShiftSidebar() {
    apiFetch('/api/schedule?week_start=' + getMondayStr())
      .then(function (data) { _scheduleData = data; _renderNurseShift(); })
      .catch(function () { _scheduleData = null; _renderNurseShift(); });
  }

  // ── Copy to clipboard ────────────────────────────────
  function _handleCopy(text) {
    if (!text) return;
    var done = function () { showToast('已複製：' + text); };
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(done).catch(function () {
        _fallbackCopy(text); done();
      });
    } else {
      _fallbackCopy(text); done();
    }
  }

  function _fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;opacity:0;top:0;left:0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch (e) {}
    ta.remove();
  }

  // ── Table sort ───────────────────────────────────────
  function _handleSort(th) {
    var table = th.closest('table');
    var tbody = table && table.querySelector('tbody');
    if (!tbody) return;
    var colIdx = Array.from(th.parentElement.children).indexOf(th);
    var isNum = th.getAttribute('data-sort') === 'num';
    var dir = th.getAttribute('data-dir') === 'asc' ? 'desc' : 'asc';
    var rows = Array.from(tbody.querySelectorAll('tr'));
    rows.sort(function (a, b) {
      var at = a.cells[colIdx] ? a.cells[colIdx].textContent.trim() : '';
      var bt = b.cells[colIdx] ? b.cells[colIdx].textContent.trim() : '';
      var cmp = isNum ? (parseFloat(at) || 0) - (parseFloat(bt) || 0)
                      : at.localeCompare(bt, 'zh-TW');
      return dir === 'asc' ? cmp : -cmp;
    });
    rows.forEach(function (r) { tbody.appendChild(r); });
    table.querySelectorAll('th[data-sort]').forEach(function (h) {
      h.removeAttribute('data-dir');
      var ic = h.querySelector('.sort-icon'); if (ic) ic.textContent = '⇅';
    });
    th.setAttribute('data-dir', dir);
    var ic = th.querySelector('.sort-icon'); if (ic) ic.textContent = dir === 'asc' ? '↑' : '↓';
  }

  var _PIN_INPUT_STYLE = 'border:1.5px solid var(--border);border-radius:var(--r);padding:9px 12px;font-size:22px;letter-spacing:8px;text-align:center;width:100%;background:var(--bg);color:var(--text);box-sizing:border-box;outline:none';
  var _PIN_LBL_STYLE  = 'font-size:12px;font-weight:600;color:var(--sub);margin-bottom:3px';

  // ── PIN modal (injected into body) ───────────────────
  function _injectPinModal() {
    if (document.getElementById('pin-modal')) return;

    // Verify-PIN modal
    var d1 = document.createElement('div');
    d1.innerHTML =
      '<div class="modal-overlay" id="pin-modal">' +
        '<div class="modal-box" style="max-width:320px">' +
          '<div class="modal-title" id="pin-modal-name">PIN 驗證</div>' +
          '<div style="display:flex;flex-direction:column;gap:4px;margin-top:4px">' +
            '<input id="pin-modal-input" type="password" inputmode="numeric" maxlength="4" placeholder="••••" autocomplete="new-password" style="' + _PIN_INPUT_STYLE + '">' +
          '</div>' +
          '<div id="pin-modal-err" style="display:none;color:#B91C1C;font-size:12px;text-align:center;margin-top:4px"></div>' +
          '<div class="modal-footer">' +
            '<button class="act-btn" onclick="Layout._closePinModal()">取消</button>' +
            '<button id="pin-modal-submit" class="act-btn act-primary" onclick="Layout._submitPin()">確認</button>' +
          '</div>' +
        '</div>' +
      '</div>';
    document.body.appendChild(d1.firstChild);
    (function () {
      var inp = document.getElementById('pin-modal-input');
      inp.addEventListener('keydown', function (e) { if (e.key === 'Escape') _closePinModal(); });
      inp.addEventListener('input', function () {
        inp.value = inp.value.replace(/\D/g, '');
        if (inp.value.length === 4) _submitPin();
      });
    })();

    // Change-PIN modal (self-service)
    if (!document.getElementById('change-pin-modal')) {
      var d2 = document.createElement('div');
      d2.innerHTML =
        '<div class="modal-overlay" id="change-pin-modal">' +
          '<div class="modal-box" style="max-width:320px">' +
            '<div class="modal-title" id="change-pin-name">更改 PIN</div>' +
            '<div style="display:flex;flex-direction:column;gap:12px;margin-top:4px">' +
              '<div><div style="' + _PIN_LBL_STYLE + '">目前 PIN</div>' +
                '<input id="change-pin-old" type="password" inputmode="numeric" maxlength="4" placeholder="••••" autocomplete="new-password" style="' + _PIN_INPUT_STYLE + '"></div>' +
              '<div><div style="' + _PIN_LBL_STYLE + '">新 PIN（4 位數字）</div>' +
                '<input id="change-pin-new" type="password" inputmode="numeric" maxlength="4" placeholder="••••" autocomplete="new-password" style="' + _PIN_INPUT_STYLE + '"></div>' +
            '</div>' +
            '<div id="change-pin-err" style="display:none;color:#B91C1C;font-size:12px;text-align:center;margin-top:4px"></div>' +
            '<div class="modal-footer">' +
              '<button class="act-btn" onclick="Layout._closeChangePinModal()">取消</button>' +
              '<button id="change-pin-submit" class="act-btn act-primary" onclick="Layout._submitChangePinModal()">更改 PIN</button>' +
            '</div>' +
          '</div>' +
        '</div>';
      document.body.appendChild(d2.firstChild);
      (function () {
        var old = document.getElementById('change-pin-old');
        var nw  = document.getElementById('change-pin-new');
        old.addEventListener('keydown', function (e) { if (e.key === 'Escape') _closeChangePinModal(); });
        old.addEventListener('input', function () {
          old.value = old.value.replace(/\D/g, '');
          if (old.value.length === 4) nw.focus();
        });
        nw.addEventListener('keydown', function (e) { if (e.key === 'Escape') _closeChangePinModal(); });
        nw.addEventListener('input', function () {
          nw.value = nw.value.replace(/\D/g, '');
          if (nw.value.length === 4) _submitChangePinModal();
        });
      })();
    }
    _updateChangePinBtn();
  }

  // ── Public init ──────────────────────────────────────
  function init(config) {
    _activePage = config.activePage || 'dashboard';
    _onRefresh  = config.onRefresh  || null;
    _renderSidebar();
    _renderTopbar();
    _injectPinModal();
    _initNurseSelector();
    loadShiftSidebar();
    if (_onRefresh) {
      document.addEventListener('visibilitychange', function () {
        if (!document.hidden) _onRefresh();
      });
    }
    document.addEventListener('click', function (ev) {
      var th = ev.target.closest('th[data-sort]');
      if (th) { _handleSort(th); return; }
      var lab = ev.target.closest('.pr-lab');
      if (lab) { _openLabModal(lab.dataset.chart, lab.dataset.name); return; }
      var cp = ev.target.closest('[data-copy]');
      if (cp && !ev.target.closest('[data-action]')) _handleCopy(cp.dataset.copy);
    });
  }

  // ── Lab results modal ────────────────────────────────
  var _labActiveTab = 'bio';

  function _injectLabModal() {
    if (document.getElementById('lab-modal')) return;
    var d = document.createElement('div');
    d.innerHTML =
      '<div class="modal-overlay" id="lab-modal">' +
        '<div class="modal-box" style="max-width:560px;max-height:80vh;display:flex;flex-direction:column">' +
          '<div style="display:flex;align-items:flex-start;gap:10px;margin-bottom:4px">' +
            '<div style="flex:1">' +
              '<div class="modal-title" id="lab-modal-title">檢驗結果</div>' +
              '<div style="font-size:12px;color:var(--muted);margin-top:2px" id="lab-modal-sub"></div>' +
            '</div>' +
            '<button onclick="Layout.closeLabModal()" style="background:none;border:none;cursor:pointer;color:var(--muted);font-size:18px;line-height:1;padding:2px 4px">✕</button>' +
          '</div>' +
          '<div style="display:flex;gap:0;border-bottom:1.5px solid var(--border);margin-bottom:12px;flex-shrink:0">' +
            '<button class="lab-tab on" id="lab-tab-bio" onclick="Layout._labTab(\'bio\')">各項檢驗 BIO</button>' +
            '<button class="lab-tab" id="lab-tab-cbc" onclick="Layout._labTab(\'cbc\')">CBC 血球計數</button>' +
          '</div>' +
          '<div id="lab-panel-bio" style="overflow-y:auto;flex:1"></div>' +
          '<div id="lab-panel-cbc" style="overflow-y:auto;flex:1;display:none"></div>' +
        '</div>' +
      '</div>';
    document.body.appendChild(d.firstChild);
  }

  function _labTab(tab) {
    _labActiveTab = tab;
    var bio = document.getElementById('lab-panel-bio');
    var cbc = document.getElementById('lab-panel-cbc');
    var tbio = document.getElementById('lab-tab-bio');
    var tcbc = document.getElementById('lab-tab-cbc');
    if (!bio) return;
    bio.style.display = tab === 'bio' ? '' : 'none';
    cbc.style.display = tab === 'cbc' ? '' : 'none';
    tbio.className = 'lab-tab' + (tab === 'bio' ? ' on' : '');
    tcbc.className = 'lab-tab' + (tab === 'cbc' ? ' on' : '');
  }

  function _renderLabResults(data) {
    function daysAgo(rocDate) {
      if (!rocDate) return '';
      var p = String(rocDate).split('/');
      if (p.length < 3) return rocDate;
      var ad = new Date((parseInt(p[0]) + 1911) + '-' + p[1] + '-' + p[2]);
      var diff = Math.round((Date.now() - ad.getTime()) / 86400000);
      return diff === 0 ? '今日' : diff === 1 ? '昨日' : diff + ' 天前';
    }
    function visitCard(visit) {
      var items = (visit.items || []).map(function (it) {
        var flag = it.flag === '+' ? ' <span style="color:#dc2626;font-weight:700">↑</span>'
                 : it.flag === '-' ? ' <span style="color:#2563eb;font-weight:700">↓</span>' : '';
        return '<div style="display:flex;justify-content:space-between;padding:3px 0;font-size:12.5px;border-bottom:1px solid var(--border)">' +
          '<span style="color:var(--sub)">' + escHtml(it.label || '') + '</span>' +
          '<span style="font-variant-numeric:tabular-nums">' + escHtml(String(it.value || '—')) + flag + '</span>' +
        '</div>';
      }).join('');
      return '<div style="margin-bottom:14px">' +
        '<div style="font-size:12px;font-weight:700;color:var(--sub);margin-bottom:6px">' +
          escHtml(String(visit.date || '')) + ' <span style="font-weight:400;margin-left:4px;opacity:.6">' + daysAgo(visit.date) + '</span>' +
        '</div>' +
        (items || '<div style="font-size:12px;color:var(--muted)">無記錄</div>') +
      '</div>';
    }
    var bio = document.getElementById('lab-panel-bio');
    var cbc = document.getElementById('lab-panel-cbc');
    var bioVisits = data.bio || [];
    var cbcVisits = data.cbc || [];
    bio.innerHTML = bioVisits.length ? bioVisits.map(visitCard).join('') :
      '<div style="text-align:center;padding:30px;color:var(--muted);font-size:13px">無 BIO 檢驗記錄</div>';
    cbc.innerHTML = cbcVisits.length ? cbcVisits.map(visitCard).join('') :
      '<div style="text-align:center;padding:30px;color:var(--muted);font-size:13px">無 CBC 檢驗記錄</div>';
  }

  function _openLabModal(chartNumber, name) {
    _injectLabModal();
    document.getElementById('lab-modal-title').textContent = '檢驗結果 — ' + (name || '');
    document.getElementById('lab-modal-sub').textContent = '#' + (chartNumber || '');
    document.getElementById('lab-panel-bio').innerHTML =
      '<div style="text-align:center;padding:30px;color:var(--muted)">載入中…</div>';
    document.getElementById('lab-panel-cbc').innerHTML = '';
    _labTab('bio');
    showModal('lab-modal');
    apiFetch('/api/lab/' + encodeURIComponent(chartNumber || ''))
      .then(function (data) { _renderLabResults(data); })
      .catch(function () {
        document.getElementById('lab-panel-bio').innerHTML =
          '<div style="text-align:center;padding:30px;color:#dc2626;font-size:13px">載入失敗，請確認網路連線</div>';
      });
  }

  function _closeLabModal() { hideModal('lab-modal'); }

  // ── Export ───────────────────────────────────────────
  window.Layout = {
    init:              init,
    updateBadges:      updateBadges,
    updateShiftInfo:   updateShiftInfo,
    updateLastUpdated: updateLastUpdated,
    showError:         showError,
    hideError:         hideError,
    showToast:         showToast,
    showModal:         showModal,
    hideModal:         hideModal,
    initSection:       initSection,
    renderSection:     renderSection,
    patientCard:       patientCard,
    patientRow:        patientRow,
    patientTable:      patientTable,
    catChip:           catChip,
    dayBadge:          dayBadge,
    getNurse:          getNurse,
    openLabModal:      _openLabModal,
    closeLabModal:     _closeLabModal,
    _labTab:           _labTab,
    _closePinModal:        _closePinModal,
    _submitPin:            _submitPin,
    _closeChangePinModal:  _closeChangePinModal,
    _submitChangePinModal: _submitChangePinModal,
    escHtml:           escHtml,
    localDateStr:      localDateStr,
    getMondayStr:      getMondayStr,
    addDays:           addDays,
    fmtChineseDate:    fmtChineseDate,
    apiFetch:          apiFetch,
    apiAction:         apiAction,
    getReport:         getReport,
    ICONS:             ICONS,
  };
})();
