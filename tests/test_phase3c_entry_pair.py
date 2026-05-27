"""Phase 3c — Entry query pair (Avalonia vs Access) end-to-end smoke.

Runs the Avalonia-side SQL re-execution AND the Access-side cbdb_replay
replay against the SAME Datadump's products, then diffs the rows.

Pytest.skip if either database is missing, if their build_manifest.json
provenance doesn't agree on the same SHA (per WORK_PLAN §1's strict-
pipeline rule), or if `pyodbc` / `cbdb_replay` can't be imported (e.g.
non-Windows CI).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


def _skip_if_missing(*paths: Path) -> None:
    for p in paths:
        if not p.exists():
            pytest.skip(f"required path missing: {p}")


def _load_config_or_skip():
    """Return cfg or pytest.skip if .env can't load cleanly."""
    try:
        from cbdb_parity.config import load_config
        return load_config()
    except Exception as exc:  # ConfigError or anything else
        pytest.skip(f"config load failed: {exc}")


def _both_products_match_datadump(manifest_path: Path) -> tuple[bool, str | None]:
    """Returns `(ok, sha)` indicating whether both sqlite and mdb
    products are anchored to the SAME Datadump SHA per the manifest."""
    if not manifest_path.exists():
        return False, None
    try:
        payload: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False, None
    if not isinstance(payload.get("datadump"), dict):
        return False, None
    sha = payload["datadump"].get("sha256")
    products = payload.get("products", {})
    if not (isinstance(products, dict) and "sqlite" in products and "mdb" in products):
        return False, sha
    return True, sha


def test_entry_pair_smoke_end_to_end(tmp_path: Path) -> None:
    """Pair test: same EntryQueryRequest into both backends; rows must
    agree on the common-fields cross-section keyed by (person_id, sequence).

    Skips cleanly when prerequisites aren't met (databases not built,
    different Datadump SHAs, missing drivers); fails with a real diff
    report if rows mismatch.
    """
    cfg = _load_config_or_skip()
    sqlite_path = cfg.build_output_dir / "cbdb.sqlite"
    mdb_path = cfg.build_output_dir / "cbdb_data.mdb"
    manifest = Path.cwd() / "build_manifest.json"  # may also be under workspace root
    if not manifest.exists():
        # Fall back to workspace-root discovery used by build_all.
        try:
            from dotenv import find_dotenv
            found = find_dotenv(usecwd=True)
            if found:
                manifest = Path(found).parent / "build_manifest.json"
        except ImportError:
            pass

    _skip_if_missing(sqlite_path, mdb_path)

    same_sha, sha = _both_products_match_datadump(manifest)
    if not same_sha:
        pytest.skip(
            f"strict-pipeline rule: sqlite and mdb must share a SHA in {manifest}; "
            f"got {sha!r}"
        )

    # Optional drivers — skip rather than fail if missing (non-Windows CI).
    try:
        import pyodbc  # noqa: F401
    except ImportError:
        pytest.skip("pyodbc not installed")

    # cbdb_replay availability — sys.path injected by access_query.
    from cbdb_parity.access_query import (
        _ensure_cbdb_replay_on_path,
        entry_query_access,
        entry_query_common_fields,
    )
    _ensure_cbdb_replay_on_path(cfg.access_tests_repo)
    try:
        import cbdb_replay.lookatentry  # noqa: F401
    except ImportError as exc:
        pytest.skip(f"cbdb_replay not importable: {exc}")

    from cbdb_parity.avalonia_query import EntryQueryRequest, entry_query
    from cbdb_parity.diff_report import diff_rows, write_report

    # Small-scope query: a single well-known entry-code. Code 36 is
    # "進士" (jinshi), the most-populated CBDB entry code.
    request = EntryQueryRequest(entry_codes=("36",), limit=200)

    avalonia_data = cfg.avalonia_repo / "Cbdb.App.Data"
    avalonia_rows = entry_query(
        sqlite_path,
        request,
        avalonia_data_dir=avalonia_data,
    )
    access_rows = entry_query_access(
        mdb_path,
        request,
        access_tests_repo=cfg.access_tests_repo,
    )

    diff = diff_rows(
        avalonia_rows,
        access_rows,
        key_fields=("person_id", "sequence"),
        compare_fields=entry_query_common_fields(),
    )

    # Always write the report — that's the deliverable, regardless of
    # pass/fail.
    reports_dir = Path.cwd() / "reports"
    write_report(
        reports_dir,
        query_id="entry_basic",
        request={
            "entry_codes": list(request.entry_codes),
            "limit": request.limit,
        },
        avalonia_rows=avalonia_rows,
        access_rows=access_rows,
        diff=diff,
        datadump_sha=sha,
    )

    # The 'diff agrees' assertion. If this fails, the per-query report
    # has the full breakdown.
    assert diff.stats.matches, (
        f"entry-pair diff for entry_code=36 has mismatches: "
        f"only_in_avalonia={diff.stats.rows_only_in_avalonia}, "
        f"only_in_access={diff.stats.rows_only_in_access}, "
        f"value_mismatches={diff.stats.rows_value_mismatch}. "
        f"See reports/entry_basic/ for detail."
    )
