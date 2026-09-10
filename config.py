# Path to the folder containing IC?????.DBF files from 燿聖.
IC_DATA_PATH: str = "mock/Data/IC"

# Path to PATDB.DBF (patient master — name, national ID, allergy WARN field).
PATDB_PATH: str = "mock/Data/S/PATDB.DBF"

# Path to QLOOK1.DBF (live waiting-room queue written by the HIS).
QUEUE_PATH: str = "mock/Data/S/QLOOK1.DBF"

# Folder containing bioc.dbf / BIO2C.DBF / CBCC.DBF / PAT_HIST.DBF (血液檢驗).
# Override in config_local.py on each clinic PC with the correct local path.
ZZ_DIR: str = ""

# Folder containing IC?????.DBF used by lab_results.py for patient-code lookup.
# Normally the same folder as IC_DATA_PATH — override in config_local.py.
IC_DIR_LAB: str = ""

# UV_APP.DBF — defined for completeness; not currently used by any code path.
UV_APP_PATH: str = ""

# VFP6_P.DBF — patient attribute store; TYPE='P1' rows hold the 手機 (mobile number).
# CODE field is the 1-based sequential record number in PATDB.
# Override in config_local.py: VFP6P_PATH = r"E:\S\VFP6_P.DBF"
VFP6P_PATH: str = ""

# Set to True to use hardcoded Python mock data instead of DBF files.
USE_MOCK_DATA: bool = False

# Days after last visit before a 代謝症候群 patient is considered overdue.
METABOLIC_FOLLOWUP_DAYS: int = 70

# Alleypin page URL where the patient search table lives (set the real value
# in config_local.py — this placeholder will fail loudly if used by mistake).
ALLEYPIN_URL: str = "https://REPLACE-ME-IN-config_local.py"

# Skip re-sending the same LINE template within this many days of its last
# send, to avoid nagging a patient with an identical reminder too soon.
RECENT_SEND_THRESHOLD_DAYS: int = 7

# config.local.py overrides the above — create it on the clinic PC with the real path.
# It is gitignored and never committed.
try:
    from config_local import *  # noqa: F401, F403
except ImportError:
    pass
