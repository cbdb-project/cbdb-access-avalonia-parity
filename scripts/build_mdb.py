"""CLI: build cbdb_data.mdb from the latest Datadump (Phase 1.3b).

Usage:
    python scripts/build_mdb.py
    cbdb-parity-build-mdb       # if pip-installed

Exit codes:
    0 = build complete
    1 = build failed (dump corruption, pyodbc error, OS error)
    2 = .env config error
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cbdb_parity.mdb_builder import cli_main  # noqa: E402

if __name__ == "__main__":
    sys.exit(cli_main())
