"""CLI: build everything (Phase 1.4 orchestrator entry point).

Usage:
    python scripts/build_all.py [--rebuild]
    cbdb-parity-build-all       # if pip-installed

Exit codes:
    0 = all products built (or cached); manifest written
    1 = build failure (refresh failed, dump corrupt, sqlite/mdb write error)
    2 = .env config error or Datadump discovery error
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cbdb_parity.build_all import cli_main  # noqa: E402

if __name__ == "__main__":
    sys.exit(cli_main(sys.argv[1:]))
