"""Nurse demo (phone): 每月點貨 — start, type / ＋− / 同上月, jump between locations, finish, see 訂購.

LOCAL server + throwaway database only — it wipes and re-seeds the fake clinic first:
    DEMO_DB=postgresql://postgres:@127.0.0.1:<port>/postgres DEMO_PASS=... \
    PYTHONPATH=<folder with imageio_ffmpeg> python tools/demos/monthly_count_demo.py static/demos/monthly-count.mp4
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import demo_data  # noqa: E402
from demo_kit import Demo  # noqa: E402

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "monthly-count.mp4")


def r(group, i, sel):
    """Control `sel` in the i-th row (from 1) of location group `group`."""
    return f"#grp-{group} .row >> nth={i - 1} >> {sel}"


def record():
    with Demo(OUT, "clinic", os.environ["DEMO_PASS"], nurse=demo_data.NURSE, phone=True) as d:
        d.goto("/inventory")
        d.page.wait_for_selector('[data-act="start"]')
        d.start()
        d.cap("每月點貨：打開「點貨」，按「開始點貨」", hold=1600)
        d.click('[data-act="start"]')
        d.page.wait_for_selector(".row .stp-in")
        d.wait(900)

        d.cap("點到幾個就輸入幾個", sub="數字輸入後自動儲存，不用按儲存")
        d.wait(700)
        d.type(r(0, 1, ".stp-in"), "8", delay=200)
        d.page.keyboard.press("Enter")
        d.wait(900)
        d.poster()

        d.cap("和上個月一樣 → 按「同上月」")
        d.wait(500)
        d.click(r(0, 2, ".same-btn"))
        d.wait(1300)

        d.cap("上方可以看進度，點位置跳到下一區")
        d.page.evaluate("document.querySelector('.ct').scrollTo({top:0,behavior:'smooth'})")
        d.wait(700)
        d.spot(".cbar")
        d.wait(1800)
        d.spot(None)
        d.click('.chip[data-jump="1"]')
        d.wait(900)

        d.cap("差一點點 → 用 − 和 ＋ 調整")
        d.click(r(1, 1, ".same-btn"))
        d.wait(600)
        for _ in range(3):
            d.click(r(1, 1, ".stp-b[data-d='-1']"), pause=250)
            d.wait(250)
        d.wait(900)

        d.cap("一區一區點下去")
        # group sizes come from the page: locations are listed in the order the app sorts them
        sizes = d.page.evaluate("[...document.querySelectorAll('.grp')].map(g => g.querySelectorAll('.row').length)")
        for g, n in enumerate(sizes):
            for i in range(1, n + 1):
                if (g, i) in ((0, 1), (0, 2), (1, 1)):
                    continue
                d.click(r(g, i, ".same-btn"), pause=180)
                d.wait(300)

        d.cap("全部點完 → 按「完成點貨」")
        d.wait(400)
        d.click('[data-act="complete"]')
        d.wait(1500)
        d.cap("完成後到「訂購」，看系統建議要訂多少", sub="依過去幾個月的用量和安全量計算")
        d.click('.inv-tabs [data-tab="order"]')
        d.wait(3600)


if __name__ == "__main__":
    demo_data.seed()
    record()
    print("saved", OUT)
