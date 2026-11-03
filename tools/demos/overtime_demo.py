"""Nurse demo (phone): 記加班 — date, start and end time, note, 新增; edit or delete; monthly total.

LOCAL server + throwaway database only — it wipes and re-seeds the fake clinic first:
    DEMO_DB=postgresql://postgres:@127.0.0.1:<port>/postgres DEMO_PASS=... \
    PYTHONPATH=<folder with imageio_ffmpeg> python tools/demos/overtime_demo.py static/demos/overtime.mp4
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import demo_data  # noqa: E402
from demo_kit import Demo  # noqa: E402

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "overtime.mp4")


def record():
    with Demo(OUT, "clinic", os.environ["DEMO_PASS"], nurse=demo_data.NURSE, phone=True) as d:
        d.goto("/nurse-ot")
        d.page.wait_for_selector("#log-table", state="attached")
        d.wait(600)
        d.start()
        d.cap("加班後記一筆：下方選「加班」", hold=1800)

        d.cap("① 選日期")
        d.click("#dp-trigger")
        d.page.wait_for_selector("#dp-drop .cal-day")
        d.wait(500)
        d.click("#dp-drop .cal-today")
        d.wait(700)

        d.cap("② 開始、結束時間：先點小時，再點分鐘")
        d.click("#tp-end-trigger")
        d.page.wait_for_selector("#tp-end-hcol .time-opt")
        d.wait(500)
        d.click("#tp-end-hcol .time-opt >> nth=20", pause=250)
        d.wait(500)
        d.click("#tp-end-mcol .time-opt >> nth=6", pause=250)
        d.wait(700)

        d.cap("③ 寫一下做了什麼（選填），按「新增」")
        d.type("#add-note", "月底點貨", delay=150)
        d.page.keyboard.press("Escape")
        d.wait(400)
        d.click("#add-btn")
        d.page.wait_for_function("document.querySelectorAll('#log-body tr').length >= 2")
        d.wait(900)
        d.poster()

        d.spot(".ot-summary")
        d.cap("上方自動算好本月總加班時間和筆數", hold=2400)
        d.spot(None)

        d.cap("記錯了：按 ✎ 修改，按 × 刪除")
        d.move("#log-body tr >> nth=0 >> .ot-edit")
        d.wait(900)
        d.spot("#log-body tr >> nth=0")
        d.wait(2000)
        d.spot(None)
        d.cap("加班紀錄會留在系統裡，月底不用再另外抄", hold=2600)


if __name__ == "__main__":
    demo_data.seed()
    record()
    print("saved", OUT)
