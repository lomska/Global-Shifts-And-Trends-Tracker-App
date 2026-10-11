"""
Shared import-path setup for this test suite. Every test_*.py in this folder starts
with `from _pathfix import *` (or just imports this module for its side effect) so it
can `import data_utils`/`import app` and import fixtures from sibling test files (e.g.
`from test_app2 import fake_get`), regardless of which directory it's actually run
from or what OS it's running on -- both matter now that these tests run on whatever
machine has this project checked out, not just the one sandbox they were written in.
"""
import os
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent

# Point data_utils' on-disk cache at a throwaway temp dir, never the app's real
# .wb_data_cache/: tests fill the cache with fake API data, and a test that didn't clear
# it afterwards (or crashed first) used to leave the real app showing that fake data --
# flat lines, 100% bars -- for up to 24h. Must run before data_utils is imported, since
# it reads this once at import time; every test imports this module first.
os.environ["WB_DATA_CACHE_DIR"] = str(Path(tempfile.gettempdir()) / "wb_population_test_cache")

for _p in (_PROJECT_ROOT, _HERE):
    _p_str = str(_p)
    if _p_str not in sys.path:
        sys.path.insert(0, _p_str)

APP_PATH = str(_PROJECT_ROOT / "app.py")
