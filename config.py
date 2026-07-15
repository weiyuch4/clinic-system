# Path to the folder containing IC?????.DBF files from 燿聖.
IC_DATA_PATH: str = "mock/Data/IC"

# Path to PATDB.DBF (patient master — name, national ID, allergy WARN field).
PATDB_PATH: str = "mock/Data/S/PATDB.DBF"

# Path to QLOOK1.DBF (live waiting-room queue written by the HIS).
QUEUE_PATH: str = "mock/Data/S/QLOOK1.DBF"

# Folder containing bioc.dbf / BIO2C.DBF / CBCC.DBF / PAT_HIST.DBF (血液檢驗).
# On PC1 this was the Z: network drive's Z subfolder; on the doctor's PC
# it is a local path — override in config_local.py.
ZZ_DIR: str = r"Z:\Z"

# Folder containing IC?????.DBF used by lab_results.py for patient-code lookup.
# Normally the same folder as IC_DATA_PATH but kept separate so lab_results
# can be configured independently if the folder layout differs.
IC_DIR_LAB: str = r"Z:\IC"

# UV_APP.DBF — stores manually-entered patient 手機 (mobile) numbers.
# One record per patient appointment/contact; MOBILE field (10 chars) keyed by PAT_IDNO.
# On PC1 this was Z:\Z\UV_APP.DBF; on the doctor's PC override in config_local.py.
UV_APP_PATH: str = r"Z:\Z\UV_APP.DBF"

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
