"""Phase 3d — Office query pair (Avalonia vs Access) end-to-end smoke.

Mirror of `test_phase3c_entry_pair`: runs Avalonia-side SQL re-execution
and the Access-side cbdb_replay replay against the SAME Datadump's
products, then diffs the rows on the common cross-section.

Pytest.skip if the database files aren't built, if their manifest
provenance disagrees (per WORK_PLAN §1's strict-pipeline rule), or if
the Windows-only drivers aren't installed.
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
    try:
        from cbdb_parity.config import load_config
        return load_config()
    except Exception as exc:
        pytest.skip(f"config load failed: {exc}")


def _both_products_match_datadump(
    manifest_path: Path,
    sqlite_path: Path,
    mdb_path: Path,
) -> tuple[bool, str | None]:
    """Strict same-dump gate: the manifest must record both products at
    the SAME Datadump SHA AND the recorded paths must resolve to the
    very files this test is about to open (else `BUILD_OUTPUT_DIR` has
    shifted under us / stale artifacts are masquerading as cached ones,
    and the parity report would be misleading)."""
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

    def _path_matches(entry: object, target: Path) -> bool:
        if not isinstance(entry, dict):
            return False
        recorded = entry.get("path")
        if not isinstance(recorded, str):
            return False
        try:
            return Path(recorded).resolve() == target.resolve()
        except OSError:
            return False

    if not _path_matches(products.get("sqlite"), sqlite_path):
        return False, sha
    if not _path_matches(products.get("mdb"), mdb_path):
        return False, sha
    return True, sha


def test_office_pair_smoke_end_to_end(tmp_path: Path) -> None:
    """Pair test: same OfficeQueryRequest into both backends; rows must
    agree on the common cross-section keyed by (person_id, posting_id,
    sequence). Skips cleanly when prerequisites aren't met."""
    cfg = _load_config_or_skip()
    sqlite_path = cfg.build_output_dir / "cbdb.sqlite"
    mdb_path = cfg.build_output_dir / "cbdb_data.mdb"
    # Workspace-root manifest discovery (mirrors Phase 3c).
    manifest = Path.cwd() / "build_manifest.json"
    if not manifest.exists():
        try:
            from dotenv import find_dotenv
            found = find_dotenv(usecwd=True)
            if found:
                manifest = Path(found).parent / "build_manifest.json"
        except ImportError:
            pass

    _skip_if_missing(sqlite_path, mdb_path)

    same_sha, sha = _both_products_match_datadump(manifest, sqlite_path, mdb_path)
    if not same_sha:
        pytest.skip(
            f"strict-pipeline rule: sqlite and mdb must share a SHA AND the manifest's "
            f"recorded paths must resolve to {sqlite_path} / {mdb_path}; manifest={manifest} sha={sha!r}"
        )

    try:
        import pyodbc  # noqa: F401
    except ImportError:
        pytest.skip("pyodbc not installed")

    from cbdb_parity.access_office_query import (
        _ensure_cbdb_replay_on_path,
        office_query_access,
        office_query_common_fields,
    )
    _ensure_cbdb_replay_on_path(cfg.access_tests_repo)
    try:
        import cbdb_replay.lookatoffice  # noqa: F401
    except ImportError as exc:
        pytest.skip(f"cbdb_replay not importable: {exc}")

    from cbdb_parity.avalonia_office_query import OfficeQueryRequest, office_query
    from cbdb_parity.diff_report import diff_rows, write_report

    # Small-scope query: a single well-known office code.
    # CBDB office_id 7 (= "尚書") is one of the most-attested office
    # codes in BIOG/POSTED_TO_OFFICE_DATA — gives us a substantial but
    # bounded row set with which to exercise diff.
    request = OfficeQueryRequest(office_codes=(7,), limit=200)

    avalonia_data = cfg.avalonia_repo / "Cbdb.App.Data"
    avalonia_rows = office_query(
        sqlite_path,
        request,
        avalonia_data_dir=avalonia_data,
    )
    access_rows = office_query_access(
        mdb_path,
        request,
        access_tests_repo=cfg.access_tests_repo,
    )

    # Key includes office_addr_id because Avalonia LEFT JOINs
    # POSTED_TO_ADDR_DATA — one posting can fan into multiple rows,
    # one per office address. Keying without it would let duplicate
    # postings collapse in diff_rows()'s internal dict and hide
    # mismatches (codex 5.4 P1 finding).
    diff = diff_rows(
        avalonia_rows,
        access_rows,
        key_fields=("person_id", "posting_id", "sequence", "office_address_id"),
        compare_fields=office_query_common_fields(),
    )

    reports_dir = Path.cwd() / "reports"
    write_report(
        reports_dir,
        query_id="office_basic",
        request={
            "office_codes": list(request.office_codes),
            "limit": request.limit,
        },
        avalonia_rows=avalonia_rows,
        access_rows=access_rows,
        diff=diff,
        datadump_sha=sha,
    )

    assert diff.stats.matches, (
        f"office-pair diff for office_code=7 has mismatches: "
        f"only_in_avalonia={diff.stats.rows_only_in_avalonia}, "
        f"only_in_access={diff.stats.rows_only_in_access}, "
        f"value_mismatches={diff.stats.rows_value_mismatch}. "
        f"See reports/office_basic/ for detail."
    )
