"""Shared helpers for recording short feature demos against a LOCAL server with fake patients.

Records with Playwright (no real cursor in headless video, so a drawn cursor, click ring and
caption bar are injected), then trims the login part and converts to MP4 with ffmpeg.
Never point this at production: demos must only ever show fake data.
"""
import os
import subprocess
import tempfile
import time

import requests
from playwright.sync_api import sync_playwright

BASE = os.environ.get("DEMO_URL", "http://127.0.0.1:8765")
assert "127.0.0.1" in BASE or "localhost" in BASE, "demos are recorded on a local server only"
W, H = 1366, 768

_OVERLAY = r"""
(() => {
  const css = `
    #demo-cursor{position:fixed;left:-100px;top:-100px;z-index:2147483647;width:26px;height:26px;pointer-events:none;
      background:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M4 2l15 11-6.5 1.2L16 21l-3 1.4-3.4-6.7L4 20z' fill='%23111' stroke='%23fff' stroke-width='1.6' stroke-linejoin='round'/%3E%3C/svg%3E") no-repeat;}
    #demo-ring{position:fixed;z-index:2147483646;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;
      border:3px solid rgba(37,99,235,.85);pointer-events:none;opacity:0}
    #demo-ring.go{animation:demoRing .55s ease-out}
    @keyframes demoRing{0%{opacity:1;transform:scale(.35)}100%{opacity:0;transform:scale(1.35)}}
    #demo-cap{position:fixed;left:50%;bottom:30px;transform:translateX(-50%);z-index:2147483647;pointer-events:none;
      background:rgba(17,24,39,.9);color:#fff;font:600 23px/1.45 "Microsoft JhengHei","PingFang TC",sans-serif;
      padding:13px 28px;border-radius:14px;max-width:84%;text-align:center;box-shadow:0 8px 30px rgba(0,0,0,.25)}
    #demo-cap:empty{display:none}
    #demo-cap.top{top:64px;bottom:auto}
    #demo-cap small{display:block;font-size:15px;font-weight:500;opacity:.75;margin-top:2px}
    #demo-spot{position:fixed;z-index:2147483645;pointer-events:none;border:3px solid #f59e0b;border-radius:12px;
      box-shadow:0 0 0 9999px rgba(0,0,0,.18);display:none}`;
  function mount() {
    if (document.getElementById('demo-cap')) return;
    const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
    ['demo-spot', 'demo-ring', 'demo-cursor', 'demo-cap'].forEach(id => {
      const d = document.createElement('div'); d.id = id; document.body.appendChild(d);
    });
    try {
      document.getElementById('demo-cap').innerHTML = sessionStorage.getItem('demo_cap') || '';
      const p = JSON.parse(sessionStorage.getItem('demo_pos') || 'null');
      if (p) { const c = document.getElementById('demo-cursor'); c.style.left = p[0] + 'px'; c.style.top = p[1] + 'px'; }
    } catch (e) {}
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount); else mount();
  document.addEventListener('mousemove', e => {
    const c = document.getElementById('demo-cursor'); if (!c) return;
    c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px';
    try { sessionStorage.setItem('demo_pos', JSON.stringify([e.clientX, e.clientY])); } catch (x) {}
  }, true);
  document.addEventListener('mousedown', e => {
    const r = document.getElementById('demo-ring'); if (!r) return;
    r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
    r.classList.remove('go'); void r.offsetWidth; r.classList.add('go');
  }, true);
  window.__demoCap = (html, top) => {
    const c = document.getElementById('demo-cap'); if (c) { c.innerHTML = html; c.classList.toggle('top', !!top); }
    try { sessionStorage.setItem('demo_cap', html); } catch (x) {}
  };
  window.__demoSpot = r => {
    const s = document.getElementById('demo-spot'); if (!s) return;
    if (!r) { s.style.display = 'none'; return; }
    Object.assign(s.style, { display: 'block', left: (r.x - 6) + 'px', top: (r.y - 6) + 'px', width: (r.width + 12) + 'px', height: (r.height + 12) + 'px' });
  };
  // Demos never show the update notice
  const g = Storage.prototype.getItem;
  Storage.prototype.getItem = function (k) { return String(k).indexOf('clinic_cl_') === 0 ? '999' : g.call(this, k); };
})();
"""


_PHONE_CSS = r"""
document.addEventListener('DOMContentLoaded', () => {
  const st = document.createElement('style');
  st.textContent = `#demo-cursor{display:none}
    #demo-cap{font-size:16px;padding:10px 14px;bottom:96px;left:14px;right:14px;transform:none;max-width:none;border-radius:12px}
    #demo-cap small{font-size:12.5px}`;
  document.head.appendChild(st);
});
"""


def ffmpeg_exe() -> str:
    import imageio_ffmpeg  # installed outside the project venv; see README note in the demo scripts
    return imageio_ffmpeg.get_ffmpeg_exe()


class Demo:
    """with Demo('out.mp4', user, password, nurse) as d: d.goto('/chronic'); d.cap('...'); d.click(sel)"""

    def __init__(self, out_mp4: str, user: str, password: str, nurse: str = "", phone: bool = False):
        self.out = out_mp4
        self.phone = phone
        # Phone demos record a 390×844 screen, then ffmpeg doubles it so players don't blur it further;
        # taps show a ring, no cursor. (Playwright's recorder pads rather than scales a larger frame size.)
        self.w, self.h = (390, 844) if phone else (W, H)
        self.tok = requests.post(f"{BASE}/auth/login", json={"username": user, "password": password}).json()["access_token"]
        self.nurse = nurse
        self.x, self.y = self.w * 0.6, self.h * 0.5

    def __enter__(self):
        self._pw = sync_playwright().start()
        self._br = self._pw.chromium.launch(channel="msedge", headless=True)
        self._dir = tempfile.mkdtemp(prefix="demo_raw_")  # raw webm stays out of static/
        self.ctx = self._br.new_context(viewport={"width": self.w, "height": self.h},
                                        is_mobile=self.phone, has_touch=self.phone, record_video_dir=self._dir,
                                        record_video_size={"width": self.w, "height": self.h},
                                        color_scheme="light")
        self.ctx.add_init_script(_OVERLAY)
        if self.phone:
            self.ctx.add_init_script(_PHONE_CSS)
        self.page = self.ctx.new_page()
        self._t_open = time.monotonic()
        self.page.goto(f"{BASE}/login")
        self.page.evaluate(f"localStorage.setItem('clinic_token','{self.tok}');"
                           f"localStorage.setItem('nurse','{self.nurse}');sessionStorage.clear()")
        self._t_start = None
        self._t_poster = None
        return self

    def start(self):
        """Call once the first real screen is showing; everything before is cut."""
        self.page.wait_for_timeout(400)
        self._t_start = time.monotonic()

    def poster(self):
        """Mark this moment as the thumbnail shown on the 教學影片 page (saved next to the MP4 as .jpg)."""
        self._t_poster = time.monotonic()

    def goto(self, path: str):
        self.page.goto(BASE + path)
        self.page.wait_for_load_state("networkidle")

    def wait(self, ms: int):
        self.page.wait_for_timeout(ms)

    def cap(self, text: str, sub: str = "", hold: int = 0, top: bool | None = None):
        """Caption bar. top=True moves it up (e.g. over a phone bottom sheet); it stays there until top=False."""
        if top is not None:
            self.cap_top = top
        html = text + (f"<small>{sub}</small>" if sub else "")
        self.page.evaluate("([h, t]) => window.__demoCap && window.__demoCap(h, t)", [html, getattr(self, "cap_top", False)])
        if hold:
            self.wait(hold)

    def spot(self, selector: str | None):
        if selector is None:
            self.page.evaluate("window.__demoSpot && window.__demoSpot(null)")
            return
        box = self.page.locator(selector).first.bounding_box()
        self.page.evaluate("r => window.__demoSpot && window.__demoSpot(r)", box)

    def move(self, selector: str, steps: int = 28):
        loc = self.page.locator(selector).first
        loc.wait_for(state="visible")
        b = loc.bounding_box()
        # Bring it to the middle when near an edge: on phones the bottom nav covers the last ~80px
        if b["y"] < self.h * 0.15 or b["y"] + b["height"] > self.h * 0.8:
            loc.evaluate("e => e.scrollIntoView({block: 'center', behavior: 'smooth'})")
            self.wait(550)
            b = loc.bounding_box()
        tx, ty = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
        self.page.mouse.move(tx, ty, steps=steps)
        self.x, self.y = tx, ty

    def click(self, selector: str, pause: int = 350):
        self.move(selector)
        self.wait(pause)
        self.page.mouse.down()
        self.page.mouse.up()

    def type(self, selector: str, text: str, delay: int = 140):
        self.click(selector)
        self.page.keyboard.type(text, delay=delay)

    def __exit__(self, *exc):
        video = self.page.video
        self.ctx.close()
        raw = video.path()
        self._br.close()
        self._pw.stop()
        if exc[0]:
            return False
        skip = max(0.0, (self._t_start or self._t_open) - self._t_open)
        subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-ss", f"{skip:.2f}", "-i", raw,
                        *(["-vf", "scale=iw*2:ih*2:flags=lanczos"] if self.phone else []),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "slow",
                        "-movflags", "+faststart", "-an", self.out], check=True)
        os.remove(raw)
        os.rmdir(self._dir)
        at = (self._t_poster - (self._t_start or self._t_open)) if self._t_poster else 3.0
        subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-ss", f"{max(0.0, at):.2f}", "-i", self.out,
                        "-frames:v", "1", "-vf", "scale=-2:640" if self.phone else "scale=640:-2", "-q:v", "4",
                        os.path.splitext(self.out)[0] + ".jpg"], check=True)
        return False
