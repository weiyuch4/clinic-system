#!/usr/bin/env python3
"""
Targeted IC01 signal finder — second pass.
Run on PC1: python explore_z2.py
Output: explore_z2_report.txt  (same folder)
Timeout: 25 minutes.

Strategy:
  A. Read IC H files — may contain M33/M26 or NHI claim codes
  B. Cross-reference: find 01西醫 records for patients known to be
     IC01 (because they have AE連續 the following month). Then compare
     every field against 01西醫 records for patients who NEVER have
     AE連續 — the difference is the real IC01 signal.
  C. Show BACK field breakdown for AE連續 vs 01西醫
"""
import os, struct, time, traceback
from collections import Counter, defaultdict

Z_ROOT      = r"Z:\\"
IC_DIR      = os.path.join(Z_ROOT, "3")
REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "explore_z2_report.txt")
TIMEOUT_SEC = 25 * 60
_start      = time.time()
_lines      = []

def elapsed():   return time.time() - _start
def timed_out(): return elapsed() > TIMEOUT_SEC
def ft():        return f"[{elapsed():5.1f}s]"

def pr(s=""):
    _lines.append(str(s))
    print(str(s), flush=True)

def save():
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write('\n'.join(_lines))
    print(f"\n>>> 報告已儲存：{REPORT_PATH}", flush=True)

# ── DBF parser ────────────────────────────────────────────────────────────────

def dbf_schema(path):
    with open(path, 'rb') as f:
        h = f.read(32)
        if len(h) < 32: raise ValueError("too short")
        num_rec  = struct.unpack_from('<I', h, 4)[0]
        hdr_size = struct.unpack_from('<H', h, 8)[0]
        rec_size = struct.unpack_from('<H', h, 10)[0]
        fields = []
        while True:
            fd = f.read(32)
            if not fd or len(fd) < 32 or fd[0] in (0x0D, 0x1A): break
            name = fd[:11].split(b'\x00')[0]
            try:   name = name.decode('ascii', errors='replace').strip()
            except: name = '?'
            ftype = chr(fd[11]) if 32 <= fd[11] < 128 else '?'
            flen  = fd[16]
            fields.append({'n': name, 't': ftype, 'l': flen})
    return fields, num_rec, hdr_size, rec_size


def read_records(path, max_rec=1000, keep=None):
    fields, num_rec, hdr_size, rec_size = dbf_schema(path)
    records = []
    with open(path, 'rb') as f:
        f.seek(hdr_size)
        for _ in range(num_rec):
            if len(records) >= max_rec or timed_out(): break
            row = f.read(rec_size)
            if not row or len(row) < rec_size: break
            if row[0] == 0x2A: continue
            rec = {}; offset = 1
            for fd in fields:
                raw = row[offset: offset + fd['l']]
                if keep is None or fd['n'] in keep:
                    try:    val = raw.decode('big5', errors='replace').strip()
                    except: val = raw.decode('latin-1', errors='replace').strip()
                    rec[fd['n']] = val
                offset += fd['l']
            records.append(rec)
    return fields, records, num_rec


def dist(records, fname, top=15):
    c = Counter(r.get(fname, '') for r in records)
    return c.most_common(top)


# ── Gather IC file paths ──────────────────────────────────────────────────────

def ic_files_of_type(suffix=''):
    """
    suffix=''  → main files IC?????.DBF
    suffix='H' → H files  IC?????H.DBF
    suffix='P' → P files  IC?????P.DBF
    suffix='X' → X files  IC?????X.DBF
    """
    result = []
    try:
        for fn in sorted(os.listdir(IC_DIR)):
            upper = fn.upper()
            if not upper.startswith('IC'): continue
            if not upper.endswith('.DBF'): continue
            stem = fn[2:-4].upper()            # e.g. '11001', '11001H', '11001P'
            expected_stem = 5 * '?' + suffix.upper()
            if suffix == '':
                if len(stem) == 5 and stem.isdigit():
                    result.append(os.path.join(IC_DIR, fn))
            else:
                if len(stem) == 5 + len(suffix) and stem[:5].isdigit() and stem[5:] == suffix.upper():
                    result.append(os.path.join(IC_DIR, fn))
    except Exception as e:
        pr(f"  listdir error: {e}")
    return sorted(result)


# ── Section A: IC H file structure ───────────────────────────────────────────

def analyse_h_files():
    pr("=" * 72)
    pr(f"{ft()} [A] IC H 檔案結構分析")
    pr("=" * 72)

    h_paths = ic_files_of_type('H')
    pr(f"  找到 H 檔: {len(h_paths)} 個")
    if not h_paths:
        pr("  !! 找不到 H 檔"); return

    # Show first few H files
    for path in h_paths[-6:]:          # analyse 6 most recent
        if timed_out(): break
        rel = os.path.basename(path)
        pr()
        pr(f"  {rel}")
        try:
            fields, records, total = read_records(path, max_rec=300)
            fnames = {f['n'] for f in fields}
            pr(f"  總記錄: {total:,}  已讀: {len(records)}")
            pr(f"  全部欄位: {', '.join(f['n'] for f in fields)}")
            pr()

            if not records: pr("  (無資料)"); continue

            # Distributions of ALL short/code fields
            for fd in fields:
                if fd['l'] > 8: continue   # skip long text fields
                d = dist(records, fd['n'])
                non_empty = [(v, c) for v, c in d if v]
                if not non_empty: continue
                if len(non_empty) == 1 and non_empty[0][1] == len(records): continue  # all same
                pr(f"    {fd['n']:14s}: {dict(d)}")

            # Sample records
            pr()
            pr(f"  前3筆完整記錄:")
            for r in records[:3]:
                pr(f"    {r}")

        except Exception as e:
            pr(f"  {rel}: 錯誤 {e}")

    pr()


# ── Section B: Cross-reference 01西醫 with following AE連續 ──────────────────

def analyse_crossref():
    pr("=" * 72)
    pr(f"{ft()} [B] 交叉比對：找真正的 IC01 記錄")
    pr("  方法：在月份 N 是 01西醫、月份 N+1/N+2 有 AE連續 → 確認 IC01")
    pr("=" * 72)
    pr()

    main_paths = ic_files_of_type('')
    if not main_paths:
        pr("  !! 找不到主檔"); return

    # Keep only last 24 months to limit time
    main_paths = main_paths[-24:]
    pr(f"  分析最近 {len(main_paths)} 個月份的主檔")
    pr()

    # Pass 1: collect AE連續 patients per month-file
    # key: (nat_id, month_stem) → True
    ae_by_month: dict[str, set[str]] = {}        # month_stem → set of nat_ids
    nishi_by_month: dict[str, list[dict]] = {}   # month_stem → list of 01西醫 records

    for path in main_paths:
        if timed_out(): break
        stem = os.path.basename(path)[2:-4]  # '11401'
        try:
            _, records, _ = read_records(path, max_rec=5000,
                                         keep={'ID','H_TYPE','CODE_F','CARD','BACK1','BACK2',
                                               'BACK3','BACK4','BACK5','BACK6','BACK7','BACK8',
                                               'BACK9','BACK10','BACK11','BACK12','BACK13',
                                               'BACK14','BACK15','NEWB','KIND','TYPE','L_PAY',
                                               'DATE','CARD_NO','A54','SHOSNO'})
            ae_set  = {r['ID'] for r in records if r.get('H_TYPE','') == 'AE連續' and r.get('ID')}
            nishi   = [r for r in records if r.get('H_TYPE','') == '01西醫' and r.get('ID')]
            ae_by_month[stem]    = ae_set
            nishi_by_month[stem] = nishi
            pr(f"  {stem}: 01西醫={len(nishi)}  AE連續={len(ae_set)}")
        except Exception as e:
            pr(f"  {stem}: 錯誤 {e}")

    pr()

    # Pass 2: for each 01西醫 record in month N,
    # check if same patient appears as AE連續 in month N+1 or N+2
    def next_stems(stem):
        """Return stems for the following 1-2 months."""
        year, mon = int(stem[:3]), int(stem[3:])
        nexts = []
        for _ in range(2):
            mon += 1
            if mon > 12: mon = 1; year += 1
            nexts.append(f"{year:03d}{mon:02d}")
        return nexts

    confirmed_ic01: list[dict] = []   # 01西醫 records confirmed as IC01
    confirmed_regular: list[dict] = [] # 01西醫 records with NO AE連續 follow-up

    for stem, nishi_records in nishi_by_month.items():
        if timed_out(): break
        nexts = next_stems(stem)
        ae_next = set()
        for ns in nexts:
            ae_next |= ae_by_month.get(ns, set())

        for r in nishi_records:
            nat_id = r.get('ID','')
            if nat_id in ae_next:
                confirmed_ic01.append(r)
            else:
                confirmed_regular.append(r)

    pr(f"  確認 IC01 記錄 (後續有 AE連續): {len(confirmed_ic01)}")
    pr(f"  確認普通慢性病 記錄 (無 AE連續): {len(confirmed_regular)}")
    pr()

    if not confirmed_ic01:
        pr("  !! 無確認 IC01 記錄，無法比對")
        return

    # Compare field distributions between confirmed IC01 and regular
    all_fields = set()
    for r in confirmed_ic01[:100] + confirmed_regular[:100]:
        all_fields |= r.keys()
    # Skip fields that are always unique (dates, IDs, codes) or long
    skip_fields = {'ID', 'CODE_F', 'DATE', 'CARD_NO', 'DOCTOR', 'SAVE', 'SAVE2',
                   'SAMID', 'BACK3', 'PARENT_B', 'PARENT_N', 'BORN', 'NEWBD',
                   'DATETIME', 'TIME', 'BIRTH', 'NAME', 'FEE', 'SELF', 'NSELF1', 'NSELF2', 'NO',
                   'ICD','ICD1','ICD2','ICD3','ICD4','ICD5','SR','UPDATE','A54','SHOSNO'}

    pr("  【欄位分佈比較：確認 IC01 vs 普通慢性病 01西醫 記錄】")
    pr("  (只顯示兩組有差異的欄位)")
    pr()

    n_ic01    = len(confirmed_ic01)
    n_regular = len(confirmed_regular)
    ic01_sample    = confirmed_ic01[:500]
    regular_sample = confirmed_regular[:500]

    for fname in sorted(all_fields - skip_fields):
        d_ic01 = Counter(r.get(fname,'') for r in ic01_sample)
        d_reg  = Counter(r.get(fname,'') for r in regular_sample)
        # Only show if distributions differ meaningfully
        top_ic01 = d_ic01.most_common(5)
        top_reg  = d_reg.most_common(5)
        if top_ic01 == top_reg: continue
        pr(f"  {fname}:")
        pr(f"    IC01    ({n_ic01:4d}筆): {dict(top_ic01)}")
        pr(f"    普通慢性 ({n_regular:4d}筆): {dict(top_reg)}")
    pr()

    # Show sample IC01 records with all fields
    pr("  【確認 IC01 完整記錄樣本 (前5筆)】")
    for r in confirmed_ic01[:5]:
        pr(f"    {r}")
    pr()
    pr("  【確認普通慢性 完整記錄樣本 (前5筆)】")
    for r in confirmed_regular[:5]:
        pr(f"    {r}")
    pr()


# ── Section C: AE連續 BACK field breakdown ───────────────────────────────────

def analyse_back_fields():
    pr("=" * 72)
    pr(f"{ft()} [C] AE連續 vs 01西醫 所有 BACK 欄位分佈")
    pr("=" * 72)
    pr()

    main_paths = ic_files_of_type('')
    if not main_paths:
        pr("  !! 找不到主檔"); return

    # Aggregate across last 12 months
    ae_records    = []
    nishi_records = []

    for path in main_paths[-12:]:
        if timed_out(): break
        try:
            _, records, _ = read_records(path, max_rec=2000)
            for r in records:
                h = r.get('H_TYPE','')
                if h == 'AE連續' and len(ae_records) < 3000:
                    ae_records.append(r)
                elif h == '01西醫' and len(nishi_records) < 3000:
                    nishi_records.append(r)
        except Exception as e:
            pr(f"  {os.path.basename(path)}: {e}")

    pr(f"  AE連續 樣本: {len(ae_records)}  01西醫 樣本: {len(nishi_records)}")
    pr()

    back_fields = ['BACK1','BACK2','BACK3','BACK4','BACK5','BACK6',
                   'BACK7','BACK8','BACK9','BACK10','BACK11','BACK12',
                   'BACK13','BACK14','BACK15','CARD','KIND','TYPE','NEWB','L_PAY']

    for fn in back_fields:
        d_ae    = Counter(r.get(fn,'') for r in ae_records)
        d_nishi = Counter(r.get(fn,'') for r in nishi_records)
        if not any(v for v in d_ae) and not any(v for v in d_nishi): continue
        if d_ae == d_nishi: continue   # skip if identical
        pr(f"  {fn}:")
        pr(f"    AE連續  : {dict(d_ae.most_common(8))}")
        pr(f"    01西醫  : {dict(d_nishi.most_common(8))}")
    pr()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    pr("=" * 72)
    pr("IC01 vs 普通慢性病 — 第二次精確探索")
    pr(f"執行時間: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    pr(f"IC 目錄: {IC_DIR}")
    pr("=" * 72)

    analyse_h_files()
    if not timed_out():
        analyse_crossref()
    if not timed_out():
        analyse_back_fields()

    pr("=" * 72)
    pr(f"完成。總執行時間: {elapsed():.1f} 秒")
    pr("=" * 72)
    save()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pr("\n(使用者中斷)"); save()
    except Exception as e:
        pr(f"\n!!! 錯誤: {e}"); traceback.print_exc(); save()
