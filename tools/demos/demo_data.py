"""One fake clinic for every nurse demo. LOCAL throwaway database only.

Names are common, ID numbers are made up. seed() wipes clinic 1's follow-up, contact and
inventory tables first, so never point DEMO_DB at anything but a throwaway Postgres.
"""
import os
from datetime import date, datetime, timedelta

import psycopg2

DB = os.environ["DEMO_DB"]
assert "127.0.0.1" in DB or "localhost" in DB, "refusing: demos only seed a local throwaway database"

NURSE = "小美"

# name, id, birth, days until due (negative = overdue), type, diagnosis
PRESCRIPTIONS = [
    ("陳美玲", "F220000001", "1958-03-14", -6, "AE連續", "高血壓"),
    ("林志明", "A120000002", "1951-11-02", -12, "AE連續", "第二型糖尿病"),
    ("黃淑惠", "B220000003", "1963-07-21", -3, "AE連續", "高血脂症"),
    ("張建國", "C120000004", "1949-01-30", -1, "一般", "胃食道逆流"),
    ("李秀英", "D220000005", "1955-09-09", 0, "AE連續", "高血壓"),
    ("王俊傑", "E120000006", "1970-04-17", 1, "AE連續", "痛風"),
    ("吳麗華", "H220000007", "1960-12-05", 2, "一般", "骨質疏鬆"),
    ("劉文雄", "K120000008", "1947-06-28", 3, "AE連續", "第二型糖尿病"),
]

# category, disease, mspt stage, [(name, id, birth year, days overdue)]
FOLLOWUPS = [
    ("代謝症候群", "代謝症候群", "追1", [
        ("蔡宗翰", "L120000011", 1966, 9), ("許雅婷", "M220000012", 1972, 4),
        ("鄭家豪", "N120000013", 1969, 1), ("謝佩君", "P220000014", 1975, -3),
        ("洪志偉", "Q120000015", 1962, -6)]),
    ("B肝", "B型肝炎", None, [
        ("郭淑芬", "R220000016", 1964, 18), ("曾國華", "S120000017", 1959, 2),
        ("邱美惠", "T220000018", 1971, -2)]),
    ("慢性腎臟病", "慢性腎臟病", None, [
        ("廖文彬", "U120000019", 1950, 33), ("賴素珍", "V220000020", 1953, 5),
        ("周明德", "W120000021", 1948, -4)]),
]

# name, unit, location, pack size, pack unit, safety stock, [two months ago, last month]
ITEMS = [
    ("優碘棉棒", "包", "治療室", 1, "", 4, [9, 7]),
    ("透氣膠帶", "卷", "治療室", 12, "盒", 6, [14, 10]),
    ("3cc 空針", "支", "治療室", 100, "盒", 80, [260, 190]),
    ("手套 M", "盒", "治療室", 10, "箱", 5, [12, 8]),
    ("酒精棉片", "盒", "治療室", 1, "", 3, [6, 5]),
    ("血糖試紙", "盒", "藥櫃", 1, "", 3, [7, 5]),
    ("採血管 紫頭", "支", "藥櫃", 100, "盒", 50, [180, 120]),
    ("壓脈帶", "條", "藥櫃", 1, "", 2, [4, 4]),
    ("影印紙 A4", "包", "庫房", 5, "箱", 5, [15, 11]),
    ("擦手紙", "包", "庫房", 20, "箱", 10, [36, 24]),
]


def seed():
    conn = psycopg2.connect(DB)
    conn.autocommit = True
    cur = conn.cursor()
    today = date.today()
    now = datetime.now()

    for t in ("contact_prefs", "contact_prefs_log", "contacts", "on_hold", "synced_prescriptions",
              "blood_recall_patients", "synced_candidates", "inventory_ledger", "inventory_orders",
              "inventory_count_lines", "inventory_counts", "inventory_items"):
        cur.execute(f"DELETE FROM {t} WHERE clinic_id = 1")

    cur.execute("INSERT INTO nurses (name, sort_order, clinic_id) VALUES (%s, 0, 1) ON CONFLICT (name) DO NOTHING",
                (NURSE,))

    for name, nid, birth, due_in, htype, icd in PRESCRIPTIONS:
        due = today + timedelta(days=due_in)
        cur.execute(
            "INSERT INTO synced_prescriptions (clinic_id, nat_id, name, birth_date, visit_date, h_type, ps, due_date, icd_name) "
            "VALUES (1, %s, %s, %s, %s, %s, 28, %s, %s)",
            (nid, name, birth, (due - timedelta(days=28)).isoformat(), htype, due.isoformat(), icd))

    for cat, disease, stage, people in FOLLOWUPS:
        for i, (name, nid, year, overdue) in enumerate(people):
            cur.execute(
                "INSERT INTO synced_candidates (clinic_id, chart_number, category, name, birth_date, disease_name, "
                "due_date, days_overdue, mspt_stage, contact_reason, last_visit_date, phone, mobile, synced_at) "
                "VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, '', %s, '02-2345-6789', %s, %s)",
                (nid, cat, name, date(year, 1 + i * 2, 10 + i), disease, today - timedelta(days=overdue), overdue,
                 stage, today - timedelta(days=90 + overdue), f"0912-000-0{i:02d}", now))

    # Two finished monthly counts, so 點貨 has 上月 numbers and a usage estimate
    months = []
    for back in (2, 1):
        y, m = today.year, today.month - back
        while m < 1:
            y, m = y - 1, m + 12
        months.append((f"{y}-{m:02d}", f"{y}-{m:02d}-28"))
    count_ids = []
    for month, day in months:
        cur.execute("INSERT INTO inventory_counts (clinic_id, month, started_at, started_by, completed_at, completed_by) "
                    "VALUES (1, %s, %s, %s, %s, %s) RETURNING id", (month, day + "T09:00", NURSE, day + "T10:00", NURSE))
        count_ids.append(cur.fetchone()[0])
    for i, (name, unit, loc, pack, pack_unit, safety, history) in enumerate(ITEMS):
        cur.execute("INSERT INTO inventory_items (clinic_id, name, unit, location, sort_order, pack_size, pack_unit, "
                    "min_stock, created_at) VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (name, unit, loc, i, pack, pack_unit, safety, months[0][1] + "T08:00"))
        item_id = cur.fetchone()[0]
        for cid, qty, (_, day) in zip(count_ids, history, months):
            cur.execute("INSERT INTO inventory_count_lines (count_id, item_id, clinic_id, qty, counted_by, counted_at) "
                        "VALUES (%s, %s, 1, %s, %s, %s)", (cid, item_id, qty, NURSE, day + "T09:30"))
    conn.close()


if __name__ == "__main__":
    seed()
    print("seeded")
