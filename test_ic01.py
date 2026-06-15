#!/usr/bin/env python3
"""Quick test: does database.py detect B221745017's IC01?
Run: python test_ic01.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date
from database import _query_chronic_prescriptions

TARGETS = ['B221745017', 'A121443480']
as_of = date.today()

print(f"Running _query_chronic_prescriptions as of {as_of}...")
results = _query_chronic_prescriptions(as_of)
print(f"Total results: {len(results)}\n")

for tid in TARGETS:
    found = [e for e in results if e.patient.chart_number == tid]
    if found:
        for e in found:
            print(f"✓ DETECTED {tid}: {e.patient.name}  stage={e.chronic_stage}"
                  f"  due={e.due_date}  overdue={e.days_overdue}d  disease={e.disease_name}")
    else:
        print(f"✗ NOT DETECTED: {tid}")
