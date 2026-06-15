#!/usr/bin/env python3
"""
Z drive explorer — IC01 vs 普通慢性病 differentiation
Run on PC1: python explore_z.py
Output: explore_z_report.txt  (same folder as this script)
Hard timeout: 28 minutes.
"""
import os, struct, time, traceback
from collections import Counter, defaultdict

# ── Config ────────────────────────────────────────────────────────────────────
Z_ROOT       = r"Z:\\"
REPORT_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "explore_z_report.txt")
TIMEOUT_SEC  = 28 * 60
MAX_SAMPLE_RECORDS = 500   # per IC file for distribution analysis

# Fields we want value distributions for (from IC main files)
IC_CODE_FIELDS = ['H_TYPE', 'M26', 'M33', 'M34', 'M22', 'M23', 'LONG',
                  'PTYPE', 'VTYPE', 'TYPE', 'ITYPE', 'CASETYPE', 'RXTYPE']

# Fields we want from P files
P_CODE_FIELDS  = ['LONG', 'PS', 'DRUG_NO', 'CODE_F', 'PTYPE', 'TYPE', 'RXTYPE']

# ── State ─────────────────────────────────────────────────────────────────────
_start = time.time()
_lines = []

def elapsed():   return time.time() - _start
def timed_out(): return elapsed() > TIMEOUT_SEC
def fmt_t():     return f"[{elapsed():5.1f}s]"

def pr(s=""):
    _lines.append(str(s))
    print(str(s), flush=True)

def save():
    try:
        with open(REPORT_PATH, 'w', encoding='utf-8') as f:
            f.write('\n'.join(_lines))
        print(f"\n>>> 報告已儲存：{REPORT_PATH}", flush=True)
    except Exception as e:
        print(f"!!! 無法儲存報告：{e}", flush=True)

# ── DBF parser ────────────────────────────────────────────────────────────────

def dbf_header(path):
    """Returns (fields, num_records, header_size, record_size).
    fields = list of {'n': name, 't': type, 'l': length}"""
    with open(path, 'rb') as f:
        h = f.read(32)
        if len(h) < 32:
            raise ValueError("file too short")
        num_records = struct.unpack_from('<I', h, 4)[0]
        header_size = struct.unpack_from('<H', h, 8)[0]
        record_size = struct.unpack_from('<H', h, 10)[0]
        fields = []
        while True:
            fd = f.read(32)
            if not fd or len(fd) < 32 or fd[0] in (0x0D, 0x1A):
                break
            name = fd[:11].split(b'\x00')[0]
            try:   name = name.decode('ascii', errors='replace').strip()
            except: name = '?'
            ftype = chr(fd[11]) if 32 <= fd[11] < 128 else '?'
            flen  = fd[16]
            fields.append({'n': name, 't': ftype, 'l': flen})
    return fields, num_records, header_size, record_size


def read_records(path, max_rec=MAX_SAMPLE_RECORDS, keep_fields=None):
    """Read up to max_rec non-deleted records. keep_fields: set of names (None = all)."""
    fields, num_records, header_size, record_size = dbf_header(path)
    records = []
    with open(path, 'rb') as f:
        f.seek(header_size)
        for _ in range(num_records):
            if len(records) >= max_rec or timed_out():
                break
            row = f.read(record_size)
            if not row or len(row) < record_size:
                break
            if row[0] == 0x2A:  # deleted
                continue
            rec = {}
            offset = 1
            for fd in fields:
                raw = row[offset: offset + fd['l']]
                if keep_fields is None or fd['n'] in keep_fields:
                    try:    val = raw.decode('big5', errors='replace').strip()
                    except: val = raw.decode('latin-1', errors='replace').strip()
                    rec[fd['n']] = val
                offset += fd['l']
            records.append(rec)
    return fields, records, num_records

# ── Helpers ───────────────────────────────────────────────────────────────────

def field_dist(records, fname, top=20):
    c = Counter(r.get(fname, '') for r in records)
    return c.most_common(top)

def short_fields(fields):
    """Field names with length ≤ 4 — likely code/flag fields."""
    return [f['n'] for f in fields if f['l'] <= 4]

def walk_dbf(root):
    """Yield absolute paths of all .DBF files under root."""
    for dirpath, dirs, files in os.walk(root):
        if timed_out():
            break
        dirs.sort()
        for fn in sorted(files):
            if fn.upper().endswith('.DBF'):
                yield os.path.join(dirpath, fn)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    pr("=" * 72)
    pr("IC01 vs 普通慢性病 探索報告")
    pr(f"執行時間: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    pr(f"掃描根目錄: {Z_ROOT}")
    pr("=" * 72)

    # ── 1. Directory inventory ─────────────────────────────────────────────────
    pr()
    pr(f"{fmt_t()} [1/5] 掃描 Z:\\ 目錄結構...")

    by_dir = defaultdict(list)
    total_dbf = 0
    try:
        for path in walk_dbf(Z_ROOT):
            total_dbf += 1
            try:   sz = os.path.getsize(path)
            except: sz = 0
            rel = path[len(Z_ROOT):]
            by_dir[os.path.dirname(path)].append((os.path.basename(path), sz))
    except Exception as e:
        pr(f"  掃描錯誤: {e}")

    pr(f"  找到 {total_dbf} 個 DBF 檔案\n")
    pr("【Z 槽目錄結構】")
    for d in sorted(by_dir.keys()):
        pr(f"  {d}\\")
        for fn, sz in sorted(by_dir[d]):
            pr(f"    {fn:30s}  {sz:>10,} bytes")

    # ── 2. Structure of every DBF file ────────────────────────────────────────
    pr()
    pr(f"{fmt_t()} [2/5] 讀取所有 DBF 欄位結構...")
    pr()

    all_paths = []
    for d in sorted(by_dir.keys()):
        for fn, _ in sorted(by_dir[d]):
            all_paths.append(os.path.join(d, fn))

    for path in all_paths:
        if timed_out():
            pr("  !! 時間到，停止結構掃描"); break
        rel = path[len(Z_ROOT):]
        try:
            fields, num_rec, _, _ = dbf_header(path)
            flist = '  '.join(f"{f['n']}({f['t']}{f['l']})" for f in fields)
            pr(f"  {rel}  [{num_rec:,} 筆]")
            pr(f"    {flist}")
        except Exception as e:
            pr(f"  {rel}: 無法讀取 ({e})")

    # ── 3. IC main file analysis ───────────────────────────────────────────────
    pr()
    pr(f"{fmt_t()} [3/5] IC 主檔詳細分析...")
    pr("    目標：H_TYPE / M26 / M33 / 其他短碼欄位的值分佈")
    pr()

    ic_paths = [p for p in all_paths if os.path.basename(p).upper().startswith('IC')
                and not os.path.basename(p).upper().startswith('ICP')
                and not os.path.basename(p)[2:-4].upper().endswith(('P','H','X'))]
    # Sort so newest file (largest ROC month number) is last
    ic_paths.sort()

    if not ic_paths:
        pr("  !! 找不到 IC?????.DBF 檔案（確認 Z:\\ 已掛載）")

    for path in ic_paths:
        if timed_out():
            pr("  !! 時間到，停止 IC 分析"); break
        rel = path[len(Z_ROOT):]
        pr(f"  {'─'*60}")
        pr(f"  {rel}")
        try:
            fields, records, total = read_records(path, max_rec=MAX_SAMPLE_RECORDS)
            fnames = {f['n'] for f in fields}
            pr(f"  總記錄: {total:,}  已讀: {len(records)}")
            pr(f"  全部欄位: {', '.join(f['n'] for f in fields)}")
            pr()

            if not records:
                pr("  (無資料)"); continue

            # Distribution of every short/code field that exists
            present_code = [fn for fn in IC_CODE_FIELDS if fn in fnames]
            # Also any other short fields not in our list
            other_short = [f['n'] for f in fields if f['l'] <= 3 and f['n'] not in IC_CODE_FIELDS]
            for fn in present_code + other_short:
                dist = field_dist(records, fn)
                # Skip if only empty / single value
                non_empty = [(v, c) for v, c in dist if v]
                if not non_empty:
                    continue
                pr(f"    {fn:12s}: {dict(dist)}")

            # Sample records where M33='1' and M26='3'  (=suspected IC01)
            pr()
            ic01_samples = [r for r in records
                            if r.get('M33','').strip() == '1' and r.get('M26','').strip() == '3']
            pr(f"  IC01 樣本 (M33=1 且 M26=3): {len(ic01_samples)} 筆 (含在已讀的 {len(records)} 筆中)")
            for r in ic01_samples[:5]:
                pr(f"    {r}")

            # Sample 01西醫 records that are NOT M33=1/M26=3  (= regular chronic?)
            regular = [r for r in records
                       if r.get('H_TYPE','').strip() == '01西醫'
                       and not (r.get('M33','').strip() == '1' and r.get('M26','').strip() == '3')]
            pr(f"  01西醫 非IC01 樣本: {len(regular)} 筆")
            for r in regular[:5]:
                pr(f"    {r}")

        except Exception as e:
            pr(f"  錯誤: {e}")
            traceback.print_exc()
        pr()

    # ── 4. P file analysis ────────────────────────────────────────────────────
    pr()
    pr(f"{fmt_t()} [4/5] P 檔詳細分析 (LONG / PS / DRUG_NO 分佈)...")
    pr()

    p_paths = []
    for path in all_paths:
        bn = os.path.basename(path).upper()
        # IC?????P.DBF convention
        if bn.startswith('IC') and bn.endswith('P.DBF') and len(bn) == 12:
            p_paths.append(path)
    p_paths.sort()

    if not p_paths:
        # Try files ending in P.DBF more loosely
        p_paths = [p for p in all_paths if os.path.basename(p).upper().endswith('P.DBF')]
        p_paths.sort()

    pr(f"  找到 P 檔: {len(p_paths)} 個")

    for path in p_paths:
        if timed_out():
            pr("  !! 時間到，停止 P 檔分析"); break
        rel = path[len(Z_ROOT):]
        pr(f"  {'─'*60}")
        pr(f"  {rel}")
        try:
            fields, records, total = read_records(path, max_rec=MAX_SAMPLE_RECORDS)
            fnames = {f['n'] for f in fields}
            pr(f"  總記錄: {total:,}  已讀: {len(records)}")
            pr(f"  全部欄位: {', '.join(f['n'] for f in fields)}")
            pr()

            if not records:
                pr("  (無資料)"); continue

            present = [fn for fn in P_CODE_FIELDS if fn in fnames]
            for fn in present:
                dist = field_dist(records, fn)
                non_empty = [(v, c) for v, c in dist if v]
                if not non_empty:
                    continue
                pr(f"    {fn:12s}: {dict(dist)}")

            # Sample LONG=1 records
            long1 = [r for r in records if r.get('LONG','').strip() == '1']
            pr(f"\n  LONG=1 樣本: {len(long1)} 筆")
            for r in long1[:5]:
                pr(f"    {r}")

            # Sample LONG != '1'
            not_long1 = [r for r in records if r.get('LONG','').strip() != '1']
            pr(f"\n  LONG≠1 樣本: {len(not_long1)} 筆")
            for r in not_long1[:3]:
                pr(f"    {r}")

        except Exception as e:
            pr(f"  錯誤: {e}")
        pr()

    # ── 5. Other potentially relevant files ───────────────────────────────────
    if not timed_out():
        pr()
        pr(f"{fmt_t()} [5/5] 其他可能相關的 DBF 檔案...")
        pr()

        already = set(ic_paths) | set(p_paths)
        keywords = ['PRESC', 'ORDER', 'DRUG', 'MED', 'CHRON', 'VISIT',
                    'CASE', 'NHI', 'CLAIM', 'REG', 'PAT', 'CUST',
                    'LONG', 'RX', 'APPT', 'DIAG']
        maybe_rx = [p for p in all_paths
                    if p not in already
                    and any(kw in os.path.basename(p).upper() for kw in keywords)]

        if maybe_rx:
            for path in maybe_rx:
                if timed_out(): break
                rel = path[len(Z_ROOT):]
                try:
                    fields, num_rec, _, _ = dbf_header(path)
                    fnames_str = ', '.join(f['n'] for f in fields)
                    pr(f"  {rel}  [{num_rec:,} 筆]  欄位: {fnames_str}")

                    # If it has any of the known code fields, read and show dists
                    fnames = {f['n'] for f in fields}
                    interesting = fnames & set(IC_CODE_FIELDS + P_CODE_FIELDS)
                    if interesting:
                        _, records, _ = read_records(path, max_rec=200, keep_fields=interesting)
                        for fn in interesting:
                            dist = field_dist(records, fn)
                            non_empty = [(v, c) for v, c in dist if v]
                            if non_empty:
                                pr(f"    {fn}: {dict(dist)}")
                except Exception as e:
                    pr(f"  {rel}: {e}")
                pr()
        else:
            pr("  (未找到其他關鍵字相符的檔案)")

    # ── Done ──────────────────────────────────────────────────────────────────
    pr()
    pr("=" * 72)
    pr(f"完成。總執行時間: {elapsed():.1f} 秒")
    pr("=" * 72)
    save()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pr("\n(使用者中斷)")
        save()
    except Exception as e:
        pr(f"\n!!! 未預期錯誤: {e}")
        traceback.print_exc()
        save()
