"""Nurse demo: 病患要求不聯絡 (about 39 seconds, captions in Chinese).

LOCAL server + throwaway database only — it wipes and re-seeds fake patients first:
    DEMO_DB=postgresql://postgres:@127.0.0.1:<port>/postgres DEMO_PASS=... \
    PYTHONPATH=<folder with imageio_ffmpeg> python tools/demos/dnc_demo.py static/demos/do-not-contact.mp4
Writes the MP4 and its .jpg thumbnail. After re-recording, bump this video's `v` in DEMOS (static/_layout.js).
"""
import os
import sys
from datetime import date, timedelta

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from demo_kit import Demo  # noqa: E402

DB = os.environ["DEMO_DB"]
assert "127.0.0.1" in DB or "localhost" in DB, "refusing: demos only seed a local throwaway database"
OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "dnc_demo.mp4")

# Fake patients: names are common, ID numbers are made up and don't pass the checksum
PATIENTS = [  # name, id, birth, days until due (negative = overdue), type, diagnosis
    ("陳美玲", "F220000001", "1958-03-14", -6, "AE連續", "高血壓"),
    ("林志明", "A120000002", "1951-11-02", -12, "AE連續", "第二型糖尿病"),
    ("黃淑惠", "B220000003", "1963-07-21", -3, "AE連續", "高血脂症"),
    ("張建國", "C120000004", "1949-01-30", -1, "一般", "胃食道逆流"),
    ("李秀英", "D220000005", "1955-09-09", 0, "AE連續", "高血壓"),
    ("王俊傑", "E120000006", "1970-04-17", 1, "AE連續", "痛風"),
    ("吳麗華", "H220000007", "1960-12-05", 2, "一般", "骨質疏鬆"),
    ("劉文雄", "K120000008", "1947-06-28", 3, "AE連續", "第二型糖尿病"),
]
DEMO_ID, DEMO_NAME = PATIENTS[0][1], PATIENTS[0][0]


def seed():
    conn = psycopg2.connect(DB)
    conn.autocommit = True
    cur = conn.cursor()
    today = date.today()
    for t in ("contact_prefs", "contact_prefs_log", "contacts", "on_hold", "synced_prescriptions", "blood_recall_patients"):
        cur.execute(f"DELETE FROM {t} WHERE clinic_id = 1")
    for name, nid, birth, due_in, htype, icd in PATIENTS:
        due = today + timedelta(days=due_in)
        cur.execute(
            "INSERT INTO synced_prescriptions (clinic_id, nat_id, name, birth_date, visit_date, h_type, ps, due_date, icd_name) "
            "VALUES (1, %s, %s, %s, %s, %s, 28, %s, %s)",
            (nid, name, birth, (due - timedelta(days=28)).isoformat(), htype, due.isoformat(), icd))
    conn.close()


def record():
    with Demo(OUT, "clinic", os.environ["DEMO_PASS"], nurse="小美") as d:
        d.goto("/prescription")
        d.page.wait_for_function("document.getElementById('cnt-pending').textContent !== '…'")
        d.start()
        d.cap("病患說「不要再傳通知給我」時", sub="設定「不聯絡」，四個步驟", hold=3200)

        d.cap("① 在上方「找病患」輸入姓名或身份證")
        d.wait(900)
        d.type(".srch-input", DEMO_NAME, delay=260)
        d.page.wait_for_selector(".srch-dd-item")
        d.wait(1100)
        d.click(".srch-dd-item")
        d.page.wait_for_selector("#cp-card")
        d.wait(900)

        d.cap("② 在「聯絡偏好」點選病患不要的通知", sub="全部都不要 → 點「全部訊息」　只有部分 → 點那幾項")
        d.spot("#cp-card")
        d.poster()
        d.wait(2200)
        d.spot(None)
        d.move("[data-all]")
        d.wait(1300)
        d.click('[data-scope="處方"]')
        d.wait(1100)

        d.cap("③ 寫下病患怎麼說的，按「儲存」")
        d.wait(600)
        d.type("#cp-note", "病患來電表示已在外院拿藥，不需要提醒", delay=90)
        d.wait(500)
        d.click("#cp-save")
        d.page.wait_for_function("document.querySelector('.cp-now').innerText.includes('不聯絡')")
        d.wait(400)
        d.spot(".cp-now")
        d.cap("已儲存　誰在什麼時候設定的都會留下紀錄", hold=2600)
        d.spot(None)

        d.cap("④ 她不會再出現在「待聯絡」，也不會收到 LINE")
        d.click('.sidebar a[href="/prescription"], a[href="/prescription"]')
        d.page.wait_for_function("document.getElementById('cnt-dnc').textContent !== '…'")
        d.wait(700)
        d.spot("#list-pending")
        d.wait(2400)
        d.spot(None)

        d.cap("已到期的會放在「不聯絡」分頁，淡色顯示")
        d.click('.filter-tab[data-tab="dnc"]')
        d.wait(800)
        d.spot("#list-dnc tr.pr-dnc")
        d.wait(2400)
        d.spot(None)

        d.cap("病患改變主意？按「修改」，取消勾選後儲存即可")
        d.move("#list-dnc a.act-btn")
        d.wait(2800)

        d.cap("左側「病患資料」可以看到所有要求不聯絡的病患")
        d.click('a[href="/patient"]')
        d.page.wait_for_selector(".dnc-tbl")
        d.wait(3400)


if __name__ == "__main__":
    seed()
    record()
    print("saved", OUT)
