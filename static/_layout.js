/* Shared layout: sidebar, topbar, nurse selector, utilities.
   Every page includes this file and calls Layout.init(config). */
(function () {
  'use strict';

  // Apply saved theme immediately — before any rendering — to prevent flash
  var _theme = localStorage.getItem('theme') || '';
  if (_theme) document.documentElement.setAttribute('data-theme', _theme);

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
  };

  // ── Nav structure ────────────────────────────────────
  var MAIN_NAV = [
    { id: 'dashboard', label: '今日總覽',  href: '/new',             badge: false },
    { id: 'chronic',   label: '慢簽追蹤',  href: '/new/chronic',     badge: true  },
    { id: 'mspt',      label: '代謝症候群', href: '/new/mspt',        badge: true  },
    { id: 'hepatitis', label: 'B/C型肝炎', href: '/new/hepatitis',   badge: true  },
    { id: 'ckd',       label: '慢性腎臟病', href: '/new/ckd',         badge: true  },
    { id: 'lab',       label: '檢驗追蹤',  href: '/new/lab',         badge: true  },
  ];
  var OTHER_NAV = [
    { id: 'directory', label: '聯絡資訊',  href: '/new/directory',   badge: false },
    { id: 'schedule',  label: '排班表',    href: '/new/schedule',    badge: false },
  ];

  // ── Private state ────────────────────────────────────
  var _activePage   = 'dashboard';
  var _onRefresh    = null;
  var _nurse        = localStorage.getItem('nurse') || '';
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

  function apiFetch(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    });
  }

  // Generic mutating API call (POST / DELETE / PUT)
  function apiAction(method, url, body) {
    return fetch(url, {
      method: method,
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body:    body ? JSON.stringify(body) : undefined,
    }).then(function (r) {
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

    apiFetch('/api/nurses').then(function (nurses) {
      var optsEl = document.getElementById('nurse-opts');
      if (!optsEl) return;

      function renderOpts() {
        optsEl.innerHTML = nurses.map(function (n) {
          var sel = n === _nurse;
          return '<button class="nurse-opt' + (sel ? ' sel' : '') + '" data-nurse="' + escHtml(n) + '" type="button">' +
            '<div class="nurse-opt-av">' + escHtml(n.slice(-1)) + '</div>' +
            '<span class="nurse-opt-name">' + escHtml(n) + '</span>' +
            CHECK_SVG +
          '</button>';
        }).join('');
        optsEl.querySelectorAll('.nurse-opt').forEach(function (el) {
          el.addEventListener('click', function () {
            _nurse = el.dataset.nurse;
            localStorage.setItem('nurse', _nurse);
            _updateAvatar(_nurse);
            _updateNurseLbl(_nurse);
            _renderNurseShift();
            renderOpts();
            closeDd();
          });
        });
      }

      renderOpts();

      var clearBtn = document.getElementById('nurse-clear');
      if (clearBtn) {
        clearBtn.addEventListener('click', function () {
          _nurse = '';
          localStorage.removeItem('nurse');
          _updateAvatar('');
          _updateNurseLbl('');
          _renderNurseShift();
          renderOpts();
          closeDd();
        });
      }
    }).catch(function () {});
  }

  // ── Sidebar ──────────────────────────────────────────
  function _navItem(item) {
    var badge = item.badge
      ? '<span class="nb zero" id="badge-' + item.id + '">…</span>'
      : '';
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
        '<a href="/new/schedule" class="pb">查看完整班表</a>' +
      '</div>';
  }

  // ── Topbar ───────────────────────────────────────────
  function _renderTopbar() {
    var el = document.getElementById('topbar');
    if (!el) return;
    el.className = 'tb';
    el.innerHTML =
      '<div class="srch">' + ICONS.search + '<input class="srch-input" type="text" placeholder="搜尋病患姓名或病歷號…" autocomplete="off"></div>' +
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
    }
    if (!report) return;
    set('chronic',   (report.chronic_prescriptions || []).length);
    set('mspt',      (report.mspt_followups || []).length + (report.mspt_inactive || []).length);
    set('hepatitis', (report.hep_followups  || []).length);
    set('ckd',       (report.ckd_followups  || []).length + (report.ckd_inactive   || []).length);
    set('lab', bloodCount != null ? bloodCount : 0);
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
    var label = (category === '代謝症候群' && msptStage) ? category + ' ' + msptStage : category;
    return '<span class="cat-chip ' + (CAT_CLS[category] || 'cat-c') + '">' + escHtml(label) + '</span>';
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
    var dob = (e.patient && e.patient.birth_date) ? String(e.patient.birth_date).slice(0, 10) : '';
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
    if (dob)     infoParts.push('<span class="pr-copy" data-copy="' + escHtml(dob) + '">' + escHtml(dob) + '</span>');
    return '<tr class="pr" data-chart="' + escHtml(e.patient.chart_number) + '">' +
      '<td class="pr-num"><span class="pr-copy" data-copy="' + escHtml(e.patient.chart_number) + '" title="點擊複製病歷號">' + escHtml(e.patient.chart_number) + '</span></td>' +
      '<td class="pr-pt"><div class="pr-name"><span class="pr-copy" data-copy="' + escHtml(e.patient.name) + '" title="點擊複製姓名">' + escHtml(e.patient.name) + '</span></div>' +
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
    var cols = ['病歷號','病患','類別','逾期','到期日','上次回診','備註'];
    var extra = extraHeaders || [];
    cols = cols.concat(extra);
    cols.push('');
    var extraCols = extra.map(function () { return '<col style="width:100px">'; }).join('');
    var colgroup = '<colgroup>' +
      '<col style="width:115px">' +   // 病歷號
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
      return '<div style="margin-bottom:6px">' +
        '<div style="font-size:10px;opacity:.6;margin-bottom:2px">' + (_SLOT_LABEL[s.slot] || s.slot) + '</div>' +
        '<div style="font-size:13.5px;font-weight:700">' + s.start_time + ' – ' + s.end_time + '</div>' +
      '</div>';
    }).join('');
  }

  function loadShiftSidebar() {
    fetch('/api/schedule?week_start=' + getMondayStr())
      .then(function (r) { return r.ok ? r.json() : { published: false, shifts: [] }; })
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

  // ── Public init ──────────────────────────────────────
  function init(config) {
    _activePage = config.activePage || 'dashboard';
    _onRefresh  = config.onRefresh  || null;
    _renderSidebar();
    _renderTopbar();
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
      var cp = ev.target.closest('[data-copy]');
      if (cp && !ev.target.closest('[data-action]')) _handleCopy(cp.dataset.copy);
    });
  }

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
    escHtml:           escHtml,
    localDateStr:      localDateStr,
    getMondayStr:      getMondayStr,
    addDays:           addDays,
    apiFetch:          apiFetch,
    apiAction:         apiAction,
    ICONS:             ICONS,
  };
})();
