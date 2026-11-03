"""Nurse demo (phone): 把筆記本上的舊紀錄打進帳冊 (品項 → item → 帳冊紀錄, Enter walks the fields).

LOCAL server + throwaway database only — it wipes and re-seeds the fake clinic first:
    DEMO_DB=postgresql://postgres:@127.0.0.1:<port>/postgres DEMO_PASS=... \
    PYTHONPATH=<folder with imageio_ffmpeg> python tools/demos/stock_book_demo.py static/demos/stock-book.mp4
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import demo_data  # noqa: E402
from demo_kit import Demo  # noqa: E402

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "stock-book.mp4")

# One page of the paper book: date, 摘要, 收入, 發出, 結存, estimate?
LINES = [
    ("8/1", "存貨", "", "", "12", False),
    ("8/20", "入 2 盒", "24", "", "", False),
    ("9/30", "點貨", "", "", "20", True),
]


def record():
    with Demo(OUT, "clinic", os.environ["DEMO_PASS"], nurse=demo_data.NURSE, phone=True) as d:
        d.goto("/inventory")
        d.page.wait_for_selector('[data-act="start"]')
        d.start()
        d.cap("把筆記本上的舊紀錄補進來：先到「品項」", hold=1200)
        d.click('.inv-tabs [data-tab="items"]')
        d.page.wait_for_selector(".irow")
        d.wait(900)
        d.cap("點要補登的品項")
        d.click('.irow:has-text("透氣膠帶")')
        d.page.wait_for_selector("#m-item.open")
        d.wait(900)
        d.cap("按「帳冊紀錄」", top=True)
        d.click("#mi-book")
        d.page.wait_for_selector("#m-ledger.open")
        d.wait(1000)

        d.cap("照筆記本一行一行輸入", sub="日期寫 8/1 或 115/8/1 都可以；按 Enter 跳下一格", top=True)
        d.wait(800)
        for i, (day, note, got, used, left, approx) in enumerate(LINES):
            d.click("#ml-date", pause=200)
            d.page.keyboard.type(day, delay=150)
            if i == 0:
                d.wait(400)
                d.spot("#ml-hint")
                d.wait(1600)
                d.spot(None)
            for sel, val in (("#ml-note", note), ("#ml-in", got), ("#ml-out", used)):
                d.page.keyboard.press("Enter")
                d.wait(180)
                if val:
                    d.page.keyboard.type(val, delay=120)
            if approx:
                d.cap("數量是估的 → 按「≒」")
                d.click("#ml-approx")
                d.wait(900)
                d.click("#ml-bal", pause=200)
            else:
                d.page.keyboard.press("Enter")
                d.wait(180)
            if left:
                d.page.keyboard.type(left, delay=120)
            if i == 0:
                d.cap("在「結存」按 Enter 就存好這一行，可以接著打下一行")
                d.wait(900)
            d.page.keyboard.press("Enter")
            d.wait(1100)
            if i == 0:
                d.poster()

        d.cap("補登的紀錄會算進每月用量，建議訂購量更準")
        d.spot("#ml-table")
        d.wait(3200)
        d.spot(None)


if __name__ == "__main__":
    demo_data.seed()
    record()
    print("saved", OUT)
