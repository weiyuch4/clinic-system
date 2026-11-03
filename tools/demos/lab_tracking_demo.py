"""Nurse demo: 檢驗追蹤 — sent-out blood draws: report back → notify, overdue, paper reports from other labs.

LOCAL server + throwaway database only — it wipes and re-seeds the fake clinic first, then sends the
fake blood draws through the local sync endpoint (DEMO_SYNC_TOKEN, default local-sync-test):
    DEMO_DB=postgresql://postgres:@127.0.0.1:<port>/postgres DEMO_PASS=... \
    PYTHONPATH=<folder with imageio_ffmpeg> python tools/demos/lab_tracking_demo.py static/demos/lab-tracking.mp4
"""
import os
import sys
from datetime import date, timedelta

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import demo_data  # noqa: E402
from demo_kit import BASE, Demo  # noqa: E402

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "lab-tracking.mp4")
CODES = {"血糖": "09005C", "總膽固醇": "09001C", "三酸甘油酯": "09004C", "肌酸酐": "09015C", "醣化血紅素": "09006C"}


def patient(name, nid, birth, tests, back):
    return {"name": name, "nat_id": nid, "birth_date": birth, "phone": "02-2345-6789", "mobile": "",
            "draw_codes": [CODES[t] for t in tests], "draw_code_names": tests, "is_allergy": False,
            "results_back": back, "results_date": date.today().isoformat() if back else None}


def seed_draws():
    today = date.today()
    days = [
        {"date": (today - timedelta(days=2)).isoformat(), "patients": [
            patient("林志明", "A120000002", "1951-11-02", ["血糖", "醣化血紅素"], True),
            patient("蔡宗翰", "L120000011", "1966-01-10", ["血糖", "總膽固醇", "三酸甘油酯"], True),
            patient("陳美玲", "F220000001", "1958-03-14", ["肌酸酐"], False),
        ]},
        {"date": (today - timedelta(days=7)).isoformat(), "patients": [
            patient("郭淑芬", "R220000016", "1964-01-10", ["總膽固醇", "三酸甘油酯"], False),
        ]},
    ]
    r = requests.post(f"{BASE}/api/sync/push-blood-pending", json={"days": days},
                      headers={"X-Sync-Token": os.environ.get("DEMO_SYNC_TOKEN", "local-sync-test")}, timeout=30)
    r.raise_for_status()


def row(name, action):
    return f'.lab-row:has-text("{name}") [data-action="{action}"]'


def record():
    with Demo(OUT, "clinic", os.environ["DEMO_PASS"], nurse=demo_data.NURSE) as d:
        d.goto("/dashboard")
        d.page.wait_for_function("!/…/.test(document.querySelector('a.urg-item[href=\"/lab\"]').innerText)")
        d.start()
        d.cap("外送抽血的報告回來了，「今日總覽」會提醒", hold=600)
        d.spot("a.urg-item[href='/lab']")
        d.wait(2200)
        d.spot(None)
        d.click("a.urg-item[href='/lab']")
        d.page.wait_for_selector(".lab-row")
        d.wait(800)

        d.spot(".lab-group >> nth=0")
        d.cap("「檢驗追蹤」依抽血日分組，標出待通知幾位", hold=2600)
        d.spot(None)

        d.spot('.lab-row:has-text("林志明")')
        d.poster()
        d.cap("「已出報告」：通知病患後，按「已通知病患」", hold=1600)
        d.spot(None)
        d.click(row("林志明", "notify"))
        d.wait(1300)

        d.spot('.lab-row:has-text("郭淑芬")')
        d.cap("「待出報告」還在等；抽血超過 5 天沒出，會標「超時待出」", sub="可以打電話問檢驗所", hold=3000)
        d.spot(None)

        d.cap("送到別的檢驗所、會拿到紙本報告 → 按「其他檢驗所」")
        d.wait(600)
        d.click(row("陳美玲", "to-physical"))
        d.wait(1300)
        d.click("#tab-physical")
        d.wait(900)
        d.cap("移到「實體報告」，紙本回來通知病患後再按「已通知病患」", hold=3400)


if __name__ == "__main__":
    demo_data.seed()
    seed_draws()
    record()
    print("saved", OUT)
