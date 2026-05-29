"""Compare ParityHost (real C#) output against the Python mirror
output for the same request, on the same SQLite DB.

This is the core diagnostic that Phase 5b promised: any divergence
between the two is a Python-mirror bug we've been failing to catch
(case-folding, NULL coercion, ORDER BY semantics, hardcoded LIMIT
constants, runtime-schema-compat shims like
`SqliteSchemaCompatibility.GetPostingAppointmentCodeExpressionAsync`,
etc.). Tests are written as **mirror correctness checks**, not as
parity gates — they fail if the mirror drifts.

Per `WORK_PLAN.md §0` scope contract: when a divergence is found,
the right action is to fix the Python mirror (in this repo) to
match the C#, NEVER the other way around. Document any genuinely
irreconcilable shape mismatch in `reports/known_issues.md`.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest


def _load_config_or_skip():
    try:
        from cbdb_parity.config import load_config
        return load_config()
    except Exception as exc:
        pytest.skip(f"config load failed: {exc}")


def _prereqs_or_skip(avalonia_repo: Path) -> None:
    """Skip cleanly when ParityHost can't run (no SDK, no DLL,
    stale DLL after upstream refresh, missing cbdb.sqlite).

    Re-uses the predicate semantics from `test_parity_host_smoke`
    so a single skip pattern keeps the entire 5b suite green-by-skip
    in the same machine states.
    """
    if not (shutil.which("dotnet") or Path(r"C:\Program Files\dotnet\dotnet.exe").is_file()):
        pytest.skip(".NET SDK not installed")
    repo_root = Path(__file__).resolve().parent.parent
    host_dll = (
        repo_root / "parity_host" / "Cbdb.App.ParityHost"
        / "bin" / "Debug" / "net8.0" / "cbdb-parity-host.dll"
    )
    if not host_dll.is_file():
        pytest.skip("ParityHost not built. Run cbdb_parity.parity_host.build_parity_host(...)")
    dll_mtime = host_dll.stat().st_mtime
    for sub in ("Cbdb.App.Core", "Cbdb.App.Data"):
        upstream_dir = avalonia_repo / sub
        if not upstream_dir.is_dir():
            return
        for ext in ("*.cs", "*.csproj"):
            for src in upstream_dir.rglob(ext):
                rel_parts = src.relative_to(upstream_dir).parts
                if any(p.lower() in ("bin", "obj") for p in rel_parts):
                    continue
                if src.stat().st_mtime > dll_mtime:
                    pytest.skip(
                        f"ParityHost DLL is older than upstream "
                        f"{src.relative_to(avalonia_repo)}; rebuild required."
                    )


# Each entry below is a host field name the Python mirror is
# allowed to omit. Add a new key to the matching set when the
# upstream C# starts emitting a field we deliberately haven't
# ported, and include a `Suppress until …` rationale alongside.
# An empty set means "the mirror must track upstream exactly" —
# the test fails the moment the host gains or drops a key.
#
# Mirror fabrications (mirror_keys − host_keys) are NEVER OK; the
# test asserts that direction without any allow-list.
_KNOWN_MIRROR_GAPS_ENTRY: frozenset[str] = frozenset()


def test_entry_host_vs_mirror_keys_agree() -> None:
    """Mirror correctness: a Python-mirror row and the corresponding
    ParityHost row must share the same set of keys, modulo a
    documented allow-list of mirror gaps.

    Two directions, both load-bearing:

    - **mirror_keys − host_keys** (mirror fabrication): the Python
      mirror is emitting a field the real C# doesn't. Always a
      mirror bug — never allowed.
    - **host_keys − mirror_keys − _KNOWN_MIRROR_GAPS_ENTRY**
      (mirror gap): the upstream C# is emitting a field we haven't
      ported. Add it to the mirror, or add it to
      `_KNOWN_MIRROR_GAPS_ENTRY` with a rationale.

    Codex 5a-5 P1 caught that only the first direction was checked.
    """
    cfg = _load_config_or_skip()
    _prereqs_or_skip(cfg.avalonia_repo)
    sqlite_path = cfg.build_output_dir / "cbdb.sqlite"
    if not sqlite_path.is_file():
        pytest.skip(f"sqlite not built at {sqlite_path}")

    from cbdb_parity.avalonia_query import EntryQueryRequest, entry_query
    from cbdb_parity.parity_host import invoke_parity_host

    request = EntryQueryRequest(
        entry_codes=("36",),
        limit=3,
    )
    # Python mirror
    mirror_rows = entry_query(
        sqlite_path,
        request,
        avalonia_data_dir=cfg.avalonia_repo / "Cbdb.App.Data",
    )
    # ParityHost (real C#)
    host_response = invoke_parity_host(
        "entry",
        sqlite_path,
        request,
        avalonia_repo=cfg.avalonia_repo,
    )
    host_rows = host_response.get("records") or []

    assert host_rows, "ParityHost returned no records for jinshi/limit=3"
    assert mirror_rows, "Python mirror returned no records for jinshi/limit=3"

    mirror_keys = set(mirror_rows[0].keys())
    host_keys = set(host_rows[0].keys())

    extra_in_mirror = mirror_keys - host_keys
    assert not extra_in_mirror, (
        f"Python mirror emits fields the real C# doesn't: "
        f"{sorted(extra_in_mirror)}. This is a mirror fabrication — "
        f"fix the mirror (cbdb_parity/avalonia_query.py) to match the "
        f"upstream EntryQueryRecord shape."
    )
    extra_in_host = host_keys - mirror_keys - _KNOWN_MIRROR_GAPS_ENTRY
    assert not extra_in_host, (
        f"Upstream C# emits fields the Python mirror doesn't: "
        f"{sorted(extra_in_host)}. Either add them to the mirror "
        f"(cbdb_parity/avalonia_query.py) or extend "
        f"_KNOWN_MIRROR_GAPS_ENTRY with a 'Suppress until …' rationale."
    )

    # Common keys must agree on person_id for the first row (the
    # ORDER BY is deterministic on both sides). This catches the
    # case where the mirror's row 0 is a different SQL output than
    # the C#'s row 0.
    common = mirror_keys & host_keys
    if "person_id" in common:
        assert mirror_rows[0]["person_id"] == host_rows[0]["person_id"], (
            f"mirror row 0 person_id={mirror_rows[0]['person_id']} != "
            f"host row 0 person_id={host_rows[0]['person_id']}. "
            f"Mirror ORDER BY or LIMIT clamp diverges from C#."
        )
