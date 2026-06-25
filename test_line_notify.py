#!/usr/bin/env python3
"""
Safe single-patient test for the Alleypin LINE-notification automation.
Always runs with a VISIBLE browser (slowed down) so you can watch every
step. Defaults to dry-run — stops right before actually clicking the
template, so you can verify search, row-matching by national ID, and
template-finding all work without sending anything real.

First run: a browser window opens to Alleypin. If not already logged in
within this dedicated profile (alleypin_profile/), log in manually once —
the session persists in that folder for future runs (this script and the
real batch-send endpoint share the same profile).

Run on PC1:
  python test_line_notify.py B123124596 1980/05/20 王順鴻 "立即B型肝炎追蹤"
  python test_line_notify.py B123124596 1980/05/20 王順鴻 "立即B型肝炎追蹤" --live

DOB must be in ROC format (e.g. 115/01/15), matching what the search box expects.
"""
import argparse
import asyncio

from line_notify import run_batch


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("chart_number", help="National ID, e.g. B123124596")
    parser.add_argument("dob_roc", help="ROC format DOB, e.g. 115/01/15")
    parser.add_argument("name", help="Patient name, for the safety cross-check")
    parser.add_argument("template", help="Exact preset-text label, e.g. 立即B型肝炎追蹤")
    parser.add_argument("--live", action="store_true", help="Actually click-send (default is dry-run)")
    parser.add_argument("--slow-mo", type=int, default=400, help="Milliseconds delay between actions, for visibility")
    args = parser.parse_args()

    targets = [{
        'chart_number': args.chart_number,
        'dob_roc': args.dob_roc,
        'name': args.name,
        'template': args.template,
    }]

    mode = "LIVE — this WILL send a real message" if args.live else "DRY-RUN — nothing will actually be sent"
    print(f"Mode: {mode}")
    print("Browser will be visible. Watch each step.\n")

    results = asyncio.run(run_batch(targets, dry_run=not args.live, headless=False, slow_mo=args.slow_mo))

    print("\n" + "=" * 60)
    print("RESULT")
    print("=" * 60)
    for r in results:
        print(f"  {r['status'].upper():18s} {r['chart_number']} {r.get('name', '')}: {r['detail']}")


if __name__ == "__main__":
    main()
