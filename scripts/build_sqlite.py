"""CLI: build cbdb.sqlite from the latest Datadump (Phase 1.2).

Usage:
    python scripts/build_sqlite.py
    cbdb-parity-build-sqlite          # if pip-installed

Exit codes:
    0 = build complete
    1 = build failed (dump corruption, write error, etc.)
    2 = .env config error
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cbdb_parity.sqlite_builder import cli_main  # noqa: E402

if __name__ == "__main__":
    sys.exit(cli_main())
