"""
Root-level conftest.py so `packages`, `services`, and `scripts` import correctly
under `pytest` regardless of installation state -- the project uses a flat
(non-src) layout and this guarantees the repo root is on sys.path.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
