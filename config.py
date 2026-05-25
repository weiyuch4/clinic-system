# Path to the folder containing IC?????.DBF files from 燿聖.
IC_DATA_PATH: str = "mock/Data/IC"

# Set to True to use hardcoded Python mock data instead of DBF files.
USE_MOCK_DATA: bool = False

# Days after last visit before a 代謝症候群 patient is considered overdue.
METABOLIC_FOLLOWUP_DAYS: int = 70

# config.local.py overrides the above — create it on the clinic PC with the real path.
# It is gitignored and never committed.
try:
    from config_local import *  # noqa: F401, F403
except ImportError:
    pass
