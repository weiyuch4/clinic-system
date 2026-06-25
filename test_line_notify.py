#!/usr/bin/env python3
"""
Safe single-patient test for the Alleypin LINE-notification automation.
Defaults to dry-run — stops right before actually clicking the template,
so you can verify search, row-matching by national ID, and template-
finding all work without sending anything real.

The automation browser stays running between calls (instead of closing
after each one) so you only ever have to log into Alleypin once — the
first time it's launched. Re-running this script reuses that same
already-logged-in browser. Use --stop to close it (e.g. to force a
fresh login, or to clear a stuck state).

Run on PC1:
  python test_line_notify.py B123124596 1980/05/20 王順鴻 "立即B型肝炎追蹤"
  python test_line_notify.py B123124596 1980/05/20 王順鴻 "立即B型肝炎追蹤" --live
  python test_line_notify.py --stop

DOB must be in ROC format (e.g. 115/01/15), matching what the search box expects.
"""
import argparse
import asyncio

from line_notify import run_batch, stop_browser


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("chart_number", nargs="?", help="National ID, e.g. B123124596")
    parser.add_argument("dob_roc", nargs="?", help="ROC format DOB, e.g. 115/01/15")
    parser.add_argument("name", nargs="?", help="Patient name, for the safety cross-check")
    parser.add_argument("template", nargs="?", help="Exact preset-text label, e.g. 立即B型肝炎追蹤")
    parser.add_argument("--live", action="store_true", help="Actually click-send (default is dry-run)")
    parser.add_argument("--stop", action="store_true", help="Close the long-running automation browser and exit")
    args = parser.parse_args()

    if args.stop:
        stopped = asyncio.run(stop_browser())
        print("Browser closed." if stopped else "No automation browser was running.")
        return

    if not all([args.chart_number, args.dob_roc, args.name, args.template]):
        parser.error("chart_number, dob_roc, name, and template are required unless using --stop")

    targets = [{
        'chart_number': args.chart_number,
        'dob_roc': args.dob_roc,
        'name': args.name,
        'template': args.template,
    }]

    mode = "LIVE — this WILL send a real message" if args.live else "DRY-RUN — nothing will actually be sent"
    print(f"Mode: {mode}")
    print("If the browser isn't already running, a window will open — log into Alleypin")
    print("manually if prompted (only needed the first time). Watch each step.\n")

    results = asyncio.run(run_batch(targets, dry_run=not args.live))

    print("\n" + "=" * 60)
    print("RESULT")
    print("=" * 60)
    for r in results:
        print(f"  {r['status'].upper():18s} {r['chart_number']} {r.get('name', '')}: {r['detail']}")


if __name__ == "__main__":
    main()
