"""UI height audit: finds controls on the same line (within 24px) whose heights differ by 2px+.
Run against a LOCAL server with test data, never production:
    UI_AUDIT_URL=http://127.0.0.1:8765 UI_AUDIT_USER=clinic UI_AUDIT_PASS=... python tools/ui_height_audit.py [desktop|mobile] [out.json]
Every page, every admin section and every .modal-overlay is checked. Rule: see the UI guide, "Control Height"."""
import json
import os
import sys

import requests
from playwright.sync_api import sync_playwright

B = os.environ.get("UI_AUDIT_URL", "http://127.0.0.1:8765")
MODE = sys.argv[1] if len(sys.argv) > 1 else "desktop"
OUT = sys.argv[2] if len(sys.argv) > 2 else f"ui_height_audit_{MODE}.json"

PAGES_DESKTOP = ["dashboard", "risk", "prescription", "mspt", "hepatitis", "ckd", "lab", "blood-recall",
                 "history", "notes", "directory", "schedule", "nurse-ot", "inventory", "change-password",
                 "nurse-mgmt", "broadcasts", "reviews", "ai-agent", "doctor", "admin"]
PAGES_MOBILE = ["schedule", "nurse-ot", "notes", "inventory", "change-password", "admin"]

# Collect visible controls, then pair up neighbours on the same line
MEASURE = r"""
(scopeSel) => {
  const scope = scopeSel ? document.querySelector(scopeSel) : document;
  if (!scope) return [];
  const isCtl = el => {
    const t = el.tagName;
    if (t === 'SELECT' || t === 'TEXTAREA') return t === 'SELECT';
    if (t === 'INPUT') return !['checkbox','radio','hidden','range','file','color'].includes(el.type);
    if (t === 'BUTTON') return true;
    if (t === 'A' || t === 'LABEL' || t === 'SPAN' || t === 'DIV') {
      const cs = getComputedStyle(el);
      const looksLikeBtn = (cs.cursor === 'pointer') && (parseFloat(cs.borderTopWidth) > 0 ||
        (cs.backgroundColor !== 'rgba(0, 0, 0, 0)' && cs.backgroundColor !== 'transparent'));
      return t === 'A' ? looksLikeBtn : (looksLikeBtn && el.getAttribute('role') === 'button');
    }
    return false;
  };
  const vis = el => {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return false;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) === 0) return false;
    return !!el.offsetParent || cs.position === 'fixed';
  };
  const desc = el => {
    const cls = (el.className && typeof el.className === 'string') ? '.' + el.className.trim().split(/\s+/).join('.') : '';
    const id = el.id ? '#' + el.id : '';
    const txt = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || el.title || '').trim().slice(0, 14).replace(/\s+/g, ' ');
    return el.tagName.toLowerCase() + id + cls + (txt ? ' "' + txt + '"' : '');
  };
  // Grouped controls (segmented toggles, pickers, tab pills) are measured as one unit
  const GROUP = '.seg-toggle,.month-picker,.week-picker,.view-toggle,.inv-tabs,.month-nav';
  const ctls = [...scope.querySelectorAll('button,a,input,select,label,span[role=button],div[role=button]')]
    .filter(isCtl).filter(vis)
    // ignore controls nested inside another control (icon inside button etc.), grouped controls and the phone nav
    .filter(el => !el.parentElement.closest('button,a') && !el.closest(GROUP) && !el.closest('.mob-nav'))
    .concat([...scope.querySelectorAll('.seg-toggle,.month-picker,.week-picker,.view-toggle')].filter(vis));
  const rects = ctls.map(el => ({ el, r: el.getBoundingClientRect() }));
  const out = [];
  for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
    const a = rects[i], b = rects[j];
    const ov = Math.min(a.r.bottom, b.r.bottom) - Math.max(a.r.top, b.r.top);
    if (ov < Math.min(a.r.height, b.r.height) * 0.5) continue;
    const gap = a.r.right <= b.r.left ? b.r.left - a.r.right : b.r.right <= a.r.left ? a.r.left - b.r.right : -1;
    if (gap < 0 || gap > 24) continue;
    const dh = Math.abs(a.r.height - b.r.height);
    if (dh < 2) continue;
    out.push({ a: desc(a.el), ah: Math.round(a.r.height * 10) / 10, b: desc(b.el), bh: Math.round(b.r.height * 10) / 10, dh: Math.round(dh * 10) / 10 });
  }
  return out;
}
"""

tok = requests.post(f"{B}/auth/login", json={"username": os.environ.get("UI_AUDIT_USER", "clinic"), "password": os.environ["UI_AUDIT_PASS"]}).json()["access_token"]
results = {}

with sync_playwright() as p:
    br = p.chromium.launch(channel="msedge", headless=True)
    if MODE == "mobile":
        ctx = br.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, device_scale_factor=2)
    else:
        ctx = br.new_context(viewport={"width": 1366, "height": 900})
    page = ctx.new_page()
    page.goto(f"{B}/login")
    page.evaluate(f"localStorage.setItem('clinic_token','{tok}');localStorage.setItem('clinic_nurse','測試')")

    def settle():
        page.wait_for_timeout(900)
        page.evaluate("document.querySelectorAll('.cl-overlay').forEach(e=>e.remove())")

    def run(key, scope=None):
        try:
            res = page.evaluate(MEASURE, scope)
        except Exception as e:  # noqa: BLE001
            res = [{"error": str(e)[:200]}]
        if res:
            results[key] = res

    def modals(prefix):
        ids = page.evaluate("[...document.querySelectorAll('.modal-overlay[id]')].map(m=>m.id)")
        for mid in ids:
            page.evaluate(f"(()=>{{const m=document.getElementById('{mid}');m.style.display='flex';m.classList.add('open','show');}})()")
            page.wait_for_timeout(250)
            run(f"{prefix} #modal {mid}", f"#{mid}")
            page.evaluate(f"(()=>{{const m=document.getElementById('{mid}');m.style.display='none';m.classList.remove('open','show');}})()")

    for name in (PAGES_MOBILE if MODE == "mobile" else PAGES_DESKTOP):
        page.goto(f"{B}/{name}")
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        settle()
        if name == "admin":
            sections = page.evaluate("[...document.querySelectorAll('[data-section]')].map(b=>b.dataset.section)")
            for sec in dict.fromkeys(sections):
                page.evaluate(f"(()=>{{const b=document.querySelector('[data-section=\"{sec}\"]');b&&b.click();}})()")
                settle()
                run(f"admin/{sec}", f"#{sec}")
                subtabs = page.evaluate(f"[...document.querySelectorAll('#{sec} .ln-tab')].map((b,i)=>i)")
                for i in subtabs[1:]:
                    page.evaluate(f"document.querySelectorAll('#{sec} .ln-tab')[{i}].click()")
                    settle()
                    run(f"admin/{sec}/sub{i}", f"#{sec}")
            run("admin/(chrome)", ".sidebar") if page.query_selector(".sidebar") else None
            modals("admin")
        else:
            run(name)
            modals(name)
    br.close()

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=1)
total = sum(len(v) for v in results.values())
print(f"{MODE}: {total} mismatched pairs on {len(results)} views -> {OUT}")
