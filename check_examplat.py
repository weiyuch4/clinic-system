import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"C:\clinic-system")

import lab_results as lr
from collections import Counter

path = r"E:\Z\EXAMPLAT.DBF"
rows = lr._cached_rows(path)

dates = sorted(set(r.get("M_DATE", "").strip() for r in rows if r.get("M_DATE", "").strip()))

print(f"Total records : {len(rows)}")
print(f"Unique dates  : {len(dates)}")

if dates:
    print(f"Earliest      : {dates[0]}  -> {lr._decode_date(dates[0])}")
    print(f"Latest        : {dates[-1]}  -> {lr._decode_date(dates[-1])}")
    print()
    print("Records per month:")
    months = Counter(d[:5] for d in dates)
    for m in sorted(months):
        print(f"  {lr._decode_date(m + '01')[:7]}   {months[m]} test days")
else:
    print("No dates found.")
