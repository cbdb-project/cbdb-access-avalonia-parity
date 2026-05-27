"""CLI: refresh the four external git repos before any parity work.

Usage:
    python scripts/refresh_external_repos.py        # from a source checkout
    cbdb-parity-refresh                             # if pip-installed

Both paths land in `cbdb_parity.refresh:cli_main`; this file is a thin
bootstrap that prepends the repo root to sys.path so the package import
works from a fresh checkout without `pip install -e .`.

Exit codes:
    0 = all repos fast-forwarded (or already up to date)
    1 = one or more `git pull --ff-only` failed
    2 = `.env` config error (missing keys, bad paths, not-a-repo, etc.)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `python scripts/refresh_external_repos.py` from a fresh checkout
# (no `pip install -e .` required) — prepend the repo root so the
# `cbdb_parity` package is importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cbdb_parity.refresh import cli_main  # noqa: E402

if __name__ == "__main__":
    sys.exit(cli_main())
