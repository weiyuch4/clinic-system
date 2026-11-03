"""Nurse demo (phone): 訂購與到貨 — suggestions after the count, adjust, mark ordered, copy the list, receive.

LOCAL server + throwaway database only — it wipes and re-seeds the fake clinic first:
    DEMO_DB=postgresql://postgres:@127.0.0.1:<port>/postgres DEMO_PASS=... \
    PYTHONPATH=<folder with imageio_ffmpeg> python tools/demos/order_arrival_demo.py static/demos/order-arrival.mp4
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import demo_data  # noqa: E402
from demo_kit import Demo  # noqa: E402

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "order-arrival.mp4")


def record():
    with Demo(OUT, "clinic", os.environ["DEMO_PASS"], nurse=demo_data.NURSE, phone=True) as d:
        d.goto("/inventory")
        d.page.wait_for_selector('.inv-tabs [data-tab="order"]')
        d.click('.inv-tabs [data-tab="order"]', pause=0)
        d.page.wait_for_selector(".orow")
        d.wait(300)
        d.start()
        d.cap("點完貨後到「訂購」", sub="系統依每月用量和安全量，算好建議訂購的數量", hold=2600)

        d.spot(".orow .reason")
        d.cap("每一項都寫了為什麼要訂、建議訂多少", hold=2400)
        d.spot(None)

        d.cap("數量可以用 − ／ ＋ 調整")
        d.click(".orow >> nth=0 >> .stp-b[data-d='1']")
        d.wait(900)
        d.poster()
        d.cap("這次不訂 → 取消勾選")
        d.click(".orow >> nth=1 >> .ochk")
        d.wait(1200)

        d.cap("確定後按下方「標記為已訂購」", top=True)
        d.click("#btn-place")
        d.page.wait_for_selector("[data-recv]")
        d.wait(1200)

        d.cap("訂購清單可以複製，貼到 LINE 傳給廠商")
        d.click('[data-act="copy"]')
        d.wait(2200)

        d.cap("貨到了 → 在「等待到貨」按「到貨」")
        d.click('.row:has-text("優碘棉棒") [data-recv]')
        d.page.wait_for_selector("#m-recv.open")
        d.wait(900)
        d.cap("訂 2 包只到 1 包 → 改成實際收到的數量", sub="用量和建議訂購量才會算得準")
        d.click("#mr-stp .stp-b[data-d='-1']")
        d.wait(1200)
        d.click("#mr-save")
        d.wait(1300)
        d.cap("到貨會自動記進這個品項的帳冊", top=False, hold=3000)


if __name__ == "__main__":
    demo_data.seed(this_month_counted=True)
    record()
    print("saved", OUT)
