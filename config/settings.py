"""Project configuration.

Values that can differ between machines are read from environment variables
(see .env.example). Everything else is a documented constant.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATABASE_PATH = Path(
    os.environ.get("MARKETLENS_DATABASE_PATH", PROJECT_ROOT / "data" / "marketlens.db")
)
LOG_LEVEL = os.environ.get("MARKETLENS_LOG_LEVEL", "INFO")

# First date requested on an initial load. Long enough to cover several
# market regimes (2018 sell-off, 2020 crash, 2022 rate hikes).
HISTORY_START_DATE = "2018-01-01"

# Number of already stored observations re-downloaded on every incremental
# update to detect retroactive changes in adjusted prices.
OVERLAP_OBSERVATIONS = 5

# Maximum relative difference in adjusted_close on overlapping dates before
# an asset's history is reloaded. Small dividends move adjusted prices by
# about 0.1% (1e-3), so 1e-4 detects them while ignoring rounding noise.
ADJUSTMENT_TOLERANCE = 1e-4

# Yahoo Finance rate limits are undocumented; these values are conservative.
REQUEST_PAUSE_SECONDS = 1.0
MAX_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 2.0
