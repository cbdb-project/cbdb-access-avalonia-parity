"""Phase 5d: byte-for-byte cross-check of the kinship BFS port.

The highest-risk Python mirror is
`cbdb_parity/avalonia_kinships_expanded.py` — a hand port of the
upstream `GetExpandedKinshipsAsync` state machine (BFS with
KinshipTraversalState, ReduceKinship, depth caps, tiebreak
ordering). Per WORK_PLAN.md §Phase 5d this MUST be reconciled with
the real C# output before the Python copy can be deleted in
Phase 5c.

These tests run the BFS port and `expanded_kinships_via_host` on
the same person_id and assert the result lists agree, modulo a
`_KNOWN_KINSHIP_GAPS` allow-list for any genuinely irreconcilable
field difference (e.g. format-only string drift).

If a test fails: fix the Python port, NEVER the upstream C#.
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


# Fields the Python port deliberately doesn't carry (or where the
# C# format-only string drift can't be reconciled cheaply). Add an
# entry only with a comment naming the upstream behaviour, so future
# work can decide whether to port or document.
_KNOWN_KINSHIP_GAPS: frozenset[str] = frozenset()


def _key(row: dict[str, Any]) -> tuple[Any, ...]:
    """Canonical key for matching rows between port and host.

    The C# `GetExpandedKinshipsAsync` returns
    `IReadOnlyList<PersonKinshipItem>` ordered by `(IsDerived,
    weighted_step_score, Distance, KinPersonId)`. The Python port
    sorts by the same tuple. So same-index pairs SHOULD describe
    the same kin. We use `kin_person_id` as the stable identifier
    for the error message.
    """
    return (row.get("kin_person_id"),)


def test_kinships_byte_for_byte_su_shi() -> None:
    """Su Shi (person_id=1762) — non-trivial expanded kinship graph
    (155 rows = 24 direct + 131 derived in the Python port's first
    run). Catches BFS depth, ReduceKinship rules, IsBetterThan
    tiebreak, and final OrderBy chain drift.
    """
    cfg = _load_config_or_skip()
    _prereqs_or_skip(cfg.avalonia_repo)
    sqlite_path = cfg.build_output_dir / "cbdb.sqlite"
    if not sqlite_path.is_file():
        pytest.skip(f"sqlite not built at {sqlite_path}")

    from cbdb_parity.avalonia_kinships_expanded import (
        expanded_kinships_query,
        expanded_kinships_via_host,
    )

    person_id = 1762
    avalonia_data = cfg.avalonia_repo / "Cbdb.App.Data"

    port_rows = expanded_kinships_query(
        sqlite_path, person_id, avalonia_data_dir=avalonia_data,
    )
    host_rows = expanded_kinships_via_host(
        sqlite_path, person_id, avalonia_repo=cfg.avalonia_repo,
    )

    # Row count check — first signal of BFS depth drift.
    assert len(port_rows) == len(host_rows), (
        f"row count differs — port={len(port_rows)} host={len(host_rows)}. "
        f"Likely BFS depth cap or visited-set drift in the port."
    )

    # Set comparison on kin_person_id catches one-off omissions /
    # duplicates before we walk position-by-position.
    port_kins = {_key(r) for r in port_rows}
    host_kins = {_key(r) for r in host_rows}
    only_port = port_kins - host_kins
    only_host = host_kins - port_kins
    assert not only_port, (
        f"Port emitted kin_person_ids the host doesn't: "
        f"{sorted(only_port)[:10]}. BFS traversal drift in the port."
    )
    assert not only_host, (
        f"Host emitted kin_person_ids the port doesn't: "
        f"{sorted(only_host)[:10]}. BFS traversal drift in the port "
        f"(it's missing a path the C# found)."
    )

    # Position-by-position schema + value diff. Tiebreak/order drift
    # surfaces here as same-index pairs with different kin_person_ids.
    for i, (p, h) in enumerate(zip(port_rows, host_rows, strict=True)):
        port_keys = set(p) - _KNOWN_KINSHIP_GAPS
        host_keys = set(h) - _KNOWN_KINSHIP_GAPS
        assert port_keys == host_keys, (
            f"row {i} (kin {p.get('kin_person_id')}) schema drift — "
            f"port_only={sorted(port_keys - host_keys)} "
            f"host_only={sorted(host_keys - port_keys)}."
        )
        for key in port_keys:
            assert p[key] == h[key], (
                f"row {i} (kin {p.get('kin_person_id')}) field "
                f"{key!r} differs — port={p[key]!r} host={h[key]!r}"
            )
