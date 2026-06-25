# Path to the folder containing IC?????.DBF files from 燿聖.
IC_DATA_PATH: str = "mock/Data/IC"

# Path to PATDB.DBF (patient master — name, national ID, allergy WARN field).
PATDB_PATH: str = "mock/Data/S/PATDB.DBF"

# Path to QLOOK1.DBF (live waiting-room queue written by the HIS).
QUEUE_PATH: str = "mock/Data/S/QLOOK1.DBF"

# Set to True to use hardcoded Python mock data instead of DBF files.
USE_MOCK_DATA: bool = False

# Days after last visit before a 代謝症候群 patient is considered overdue.
METABOLIC_FOLLOWUP_DAYS: int = 70

# Alleypin page URL where the patient search table lives (set the real value
# in config_local.py — this placeholder will fail loudly if used by mistake).
ALLEYPIN_URL: str = "https://REPLACE-ME-IN-config_local.py"

# Run the Alleypin automation browser with no visible window. Set to False
# temporarily whenever a fresh Alleypin login is needed — the login form has
# to be visible to type into — then stop the browser (test_line_notify.py
# --stop), log in once with this set to False, and switch it back to True.
ALLEYPIN_HEADLESS: bool = True

# config.local.py overrides the above — create it on the clinic PC with the real path.
# It is gitignored and never committed.
try:
    from config_local import *  # noqa: F401, F403
except ImportError:
    pass
