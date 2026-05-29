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


def _row_subset_keys(host_row: dict[str, Any]) -> dict[str, Any]:
    """Project a C#-shaped row to the keys our Python mirror also
    emits. The mirror's `_*_RECORD_FIELDS` use snake_case; the
    ParityHost output (after `SnakeCaseLower`) does too. Reduces
    noise from C#-side fields the mirror doesn't carry."""
    # The mirror's entry record has 35 fields (see
    # cbdb_parity.avalonia_query._ENTRY_RECORD_FIELDS). The C#
    # `EntryQueryRecord` has the same 35 in the same order. We
    # don't enforce equality field-by-field here (that's
    # test_phase3c_entry_pair's job); we just confirm the SET of
    # keys agrees.
    return {k: host_row[k] for k in host_row if k in host_row}


def test_entry_host_vs_mirror_keys_agree() -> None:
    """Mirror correctness: the keys of a Python-mirror row must be
    a subset of the keys of the corresponding ParityHost row.

    If the mirror starts emitting a key the host doesn't, that's a
    parity-side fabrication. If the host emits keys the mirror
    doesn't, that's a known mirror gap (acceptable for now; the
    Phase 5c plan handles full deprecation).
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
