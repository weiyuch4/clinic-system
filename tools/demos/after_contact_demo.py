"""Nurse demo: 聯絡完病患後，按哪個按鈕 (今日總覽 → 處方追蹤: 已聯繫 / 未加LINE / 暫緩 / 撤銷).

LOCAL server + throwaway database only — it wipes and re-seeds the fake clinic first:
    DEMO_DB=postgresql://postgres:@127.0.0.1:<port>/postgres DEMO_PASS=... \
    PYTHONPATH=<folder with imageio_ffmpeg> python tools/demos/after_contact_demo.py static/demos/after-contact.mp4
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import demo_data  # noqa: E402
from demo_kit import Demo  # noqa: E402

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "after-contact.mp4")


def row(nat, action):
    return f'#list-pending tr[data-nat="{nat}"] [data-action="{action}"]'


def record():
    with Demo(OUT, "clinic", os.environ["DEMO_PASS"], nurse=demo_data.NURSE) as d:
        d.goto("/dashboard")
        d.page.wait_for_function("!/…/.test(document.querySelector('a.urg-item[href=\"/prescription\"]').innerText)")
        d.start()
        d.cap("每天從「今日總覽」開始", sub="右邊「今日待處理」：每份名單還有幾位要聯絡", hold=600)
        d.spot("a.urg-item[href='/prescription']")
        d.wait(2400)
        d.spot(None)
        d.click("a.urg-item[href='/prescription']")
        d.page.wait_for_function("document.getElementById('cnt-pending').textContent !== '…'")
        d.wait(900)

        d.cap("① 傳了 LINE 或聯絡到病患 → 按「已聯繫」")
        d.move(row("A120000002", "contact"))
        d.poster()
        d.wait(900)
        d.click(row("A120000002", "contact"))
        d.wait(900)
        d.spot('.filter-tab[data-tab="contacted"]')
        d.cap("他移到「已聯繫」分頁，待聯絡少了一位", hold=2400)
        d.spot(None)

        d.cap("② 病患還沒加診所 LINE → 按「未加LINE」", sub="先移到「未加LINE」分頁，請病患加好友後再聯絡")
        d.wait(1400)
        d.click(row("F220000001", "no-line"))
        d.wait(1100)
        d.spot('.filter-tab[data-tab="noline"]')
        d.wait(1600)
        d.spot(None)

        d.cap("③ 暫時不用聯絡（出國、住院）→ 按「暫緩」，寫下原因")
        d.wait(1200)
        d.click(row("B220000003", "hold"))
        d.page.wait_for_selector("#modal-hold.open")
        d.type("#modal-hold-note", "出國，12 月回來再聯絡", delay=110)
        d.wait(500)
        d.click("#btn-hold-confirm")
        d.wait(1000)
        d.spot('.filter-tab[data-tab="hold"]')
        d.cap("暫緩的病患在「暫緩中」，隨時可以按「解除暫緩」", hold=2400)
        d.spot(None)

        d.cap("按錯了？到「已聯繫」分頁按「撤銷」")
        d.click('.filter-tab[data-tab="contacted"]')
        d.wait(700)
        d.spot('#list-contacted tr')
        d.move('#list-contacted [data-action="undo-contact"]')
        d.wait(1400)
        d.spot(None)
        d.click('#list-contacted [data-action="undo-contact"]')
        d.wait(1000)
        d.click('.filter-tab[data-tab="pending"]')
        d.wait(500)
        d.spot('#list-pending tr[data-nat="A120000002"]')
        d.cap("病患回到待聯絡，紀錄也一起刪掉", hold=2800)
        d.spot(None)


if __name__ == "__main__":
    demo_data.seed()
    record()
    print("saved", OUT)
