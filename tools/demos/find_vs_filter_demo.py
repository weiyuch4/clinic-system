"""Nurse demo: 「找病患」和「篩選名單」差在哪 (top-bar search vs the list filter).

LOCAL server + throwaway database only — it wipes and re-seeds the fake clinic first:
    DEMO_DB=postgresql://postgres:@127.0.0.1:<port>/postgres DEMO_PASS=... \
    PYTHONPATH=<folder with imageio_ffmpeg> python tools/demos/find_vs_filter_demo.py static/demos/find-vs-filter.mp4
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import demo_data  # noqa: E402
from demo_kit import Demo  # noqa: E402

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "find-vs-filter.mp4")


def record():
    with Demo(OUT, "clinic", os.environ["DEMO_PASS"], nurse=demo_data.NURSE) as d:
        d.goto("/prescription")
        d.page.wait_for_function("document.getElementById('cnt-pending').textContent !== '…'")
        d.start()
        d.cap("畫面上有兩個搜尋框，用途不一樣", hold=2000)

        d.spot("#search-input")
        d.cap("「篩選名單」：只在這份名單裡找", sub="名單很長時，用來快速找到某一列")
        d.wait(1800)
        d.spot(None)
        d.type("#search-input", "黃", delay=200)
        d.wait(700)
        d.spot("#list-pending")
        d.wait(2000)
        d.spot(None)
        d.page.fill("#search-input", "")
        d.page.dispatch_event("#search-input", "input")
        d.wait(600)

        d.spot(".srch-input")
        d.poster()
        d.cap("「找病患」：所有病患都找得到", sub="不在這份名單上的病患也可以，例如 B 肝的郭淑芬")
        d.wait(2000)
        d.spot(None)
        d.type(".srch-input", "郭淑芬", delay=220)
        d.page.wait_for_selector(".srch-dd-item")
        d.wait(1200)
        d.click(".srch-dd-item")
        d.page.wait_for_selector(".pt-section")
        d.wait(800)
        d.cap("直接打開病患資料：追蹤項目、聯絡偏好、聯絡紀錄都在這裡", hold=3400)


if __name__ == "__main__":
    demo_data.seed()
    record()
    print("saved", OUT)
