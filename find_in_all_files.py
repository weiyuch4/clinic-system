import sys
import os
import time

sys.stdout.reconfigure(encoding="utf-8")

if len(sys.argv) < 3:
    print("Usage: python find_in_all_files.py <SEARCH_DIR> <SEARCH_TERM>")
    print("  Searches every file in SEARCH_DIR (recursively) for SEARCH_TERM")
    print("  by scanning raw bytes — works on DBF, XML, text, any format.")
    sys.exit(1)

search_dir = sys.argv[1]
term_str   = sys.argv[2]
term_bytes = term_str.encode("ascii")
SKIP_SIZE  = 2_000_000_000  # skip files over 2GB (likely full-drive backups)
CHUNK      = 65536

print(f"Searching {search_dir!r} for {term_str!r} in every file...")
print(f"(Skipping files over 2 GB)\n")

found = 0
scanned = 0
errors = 0
start = time.time()

SKIP_DIRS = {"$recycle.bin", "system volume information"}

for root, dirs, files in os.walk(search_dir, topdown=True):
    dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS]

    for fname in files:
        fpath = os.path.join(root, fname)
        scanned += 1

        # Progress every 500 files
        if scanned % 500 == 0:
            elapsed = time.time() - start
            print(f"  [{scanned} files, {elapsed:.0f}s]  currently in: {root!r}", flush=True)

        try:
            size = os.path.getsize(fpath)
            if size > SKIP_SIZE:
                print(f"  SKIPPED (too large): {fpath!r}  ({size/1e9:.1f} GB)")
                continue

            leftover = b""
            match = False
            with open(fpath, "rb") as f:
                while True:
                    chunk = f.read(CHUNK)
                    if not chunk:
                        break
                    data = leftover + chunk
                    if term_bytes in data:
                        match = True
                        break
                    leftover = data[-len(term_bytes) + 1:]

            if match:
                found += 1
                ext = os.path.splitext(fname)[1].upper()
                print(f"\n  >>> FOUND in {fpath!r}  ({size:,} bytes, {ext})\n")

        except PermissionError:
            errors += 1
        except Exception as e:
            errors += 1
            if errors <= 10:
                print(f"  Error: {fpath!r} — {e}")

elapsed = time.time() - start
print(f"\nFinished. Scanned {scanned} files in {elapsed:.1f}s.")
print(f"Matches: {found}   Errors/skipped: {errors}")
