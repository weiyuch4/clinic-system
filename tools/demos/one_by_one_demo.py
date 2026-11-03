"""Nurse demo: 逐一追蹤 — work a long list one patient at a time in the small window.

The real button opens a separate browser window, which a page recording can't show next to the
list. So the demo replaces window.open with a window-styled frame on the same page that loads the
real /workflow-popup (same page, same buttons, same API calls).

LOCAL server + throwaway database only — it wipes and re-seeds the fake clinic first:
    DEMO_DB=postgresql://postgres:@127.0.0.1:<port>/postgres DEMO_PASS=... \
    PYTHONPATH=<folder with imageio_ffmpeg> python tools/demos/one_by_one_demo.py static/demos/one-by-one.mp4
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import demo_data  # noqa: E402
from demo_kit import Demo  # noqa: E402

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "one-by-one.mp4")
W = "#demo-win iframe >> internal:control=enter-frame >> "  # inside the small window

# Wrapped in a function: page.evaluate() calls whatever function the expression returns
_FAKE_WINDOW = r"""() => {
window.open = function (url, name, features) {
  var old = document.getElementById('demo-win'); if (old) old.remove();
  var w = document.createElement('div');
  w.id = 'demo-win';
  w.style.cssText = 'position:fixed;right:28px;top:72px;width:420px;z-index:900;border-radius:10px;overflow:hidden;' +
    'box-shadow:0 18px 50px rgba(0,0,0,.28),0 0 0 1px rgba(0,0,0,.12);background:#fff';
  w.innerHTML = '<div style="height:30px;display:flex;align-items:center;gap:8px;padding:0 12px;background:#e9ebee;' +
    'font:600 12px system-ui,\'Microsoft JhengHei\',sans-serif;color:#374151">逐一追蹤</div>' +
    '<iframe src="' + url + '" style="display:block;width:420px;height:520px;border:0"></iframe>';
  document.body.appendChild(w);
  var f = w.querySelector('iframe');
  f.addEventListener('load', function () { try { f.contentWindow.opener = window; } catch (e) {} });
  return f.contentWindow;
};
}
"""


def record():
    with Demo(OUT, "clinic", os.environ["DEMO_PASS"], nurse=demo_data.NURSE) as d:
        d.goto("/prescription")
        d.page.wait_for_function("document.getElementById('cnt-pending').textContent !== '…'")
        d.page.evaluate(_FAKE_WINDOW)
        d.start()
        d.cap("名單很長時，用「逐一追蹤」一位一位處理", hold=1200)
        d.click("#btn-workflow")
        d.page.wait_for_selector(W + ".pat-name")
        d.wait(900)
        d.spot("#demo-win")
        d.cap("小視窗一次只顯示一位病患，可以放在螢幕旁邊", hold=2600)
        d.spot(None)
        d.poster()

        d.cap("姓名、身份證、生日都有「複製」，可以直接貼上")
        d.click(W + ".field >> nth=1 >> .cp")
        d.wait(1800)

        d.cap("聯絡好了 → 「已聯繫」，自動跳到下一位")
        d.click(W + "#actions .btn-pri")
        d.wait(1600)

        d.cap("還沒加診所 LINE → 「未加LINE」")
        d.click(W + "#actions button:has-text('未加LINE')")
        d.wait(1600)

        d.cap("現在不方便 → 「跳過」，之後再回來")
        d.click(W + "#actions button:has-text('跳過')")
        d.wait(1500)

        d.cap("暫時不用聯絡 → 「暫緩」，寫下原因")
        d.click(W + "#actions .btn-warn")
        d.type(W + "#hold-note", "住院中，出院後再聯絡", delay=110)
        d.wait(400)
        d.click(W + "#confirm-btn")
        d.wait(1400)

        d.spot("#filter-bar")
        d.cap("後面的名單會跟著更新：待聯絡變少，已聯繫、暫緩中多了", hold=3200)
        d.spot(None)


if __name__ == "__main__":
    demo_data.seed()
    record()
    print("saved", OUT)
