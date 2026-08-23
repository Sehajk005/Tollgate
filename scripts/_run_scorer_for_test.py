"""
Test harness only -- NOT a Day 1 product deliverable. Launches the real
scorer app as a standalone uvicorn process against a given db/spool path, so
the durability and lock-contention acceptance tests can exercise a real,
killable OS process rather than an in-process TestClient.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn

from services.scorer.app import create_app
from services.scorer.deps import ScorerState


def main() -> None:
    db_path = Path(os.environ["TOLLGATE_TEST_DB"])
    spool_dir = Path(os.environ["TOLLGATE_TEST_SPOOL"])
    port = int(os.environ["TOLLGATE_TEST_PORT"])
    state = ScorerState.build_default(db_path=db_path, spool_dir=spool_dir)
    app = create_app(state=state)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
