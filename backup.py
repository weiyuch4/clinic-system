import shutil
from datetime import date
from pathlib import Path

DB_PATH    = Path("contacts.db")
BACKUP_DIR = Path("backups")
KEEP_DAYS  = 30


def run() -> None:
    """Copy contacts.db to backups/contacts_YYYY-MM-DD.db (once per day).
    Deletes backups older than KEEP_DAYS to avoid unbounded growth."""
    if not DB_PATH.exists():
        return
    BACKUP_DIR.mkdir(exist_ok=True)
    dst = BACKUP_DIR / f"contacts_{date.today().isoformat()}.db"
    if not dst.exists():
        shutil.copy2(DB_PATH, dst)
    # Keep only the most recent KEEP_DAYS backups
    all_backups = sorted(BACKUP_DIR.glob("contacts_*.db"))
    for old in all_backups[:-KEEP_DAYS]:
        old.unlink(missing_ok=True)
