"""Phase 4 / Tier 2 — per-person statuses accessor (Avalonia vs Access).

NB: this is the PER-PERSON statuses accessor on SqlitePersonBrowserService,
distinct from Phase 3e's cross-person status query.
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


def test_statuses_person_pair_smoke_end_to_end(tmp_path: Path) -> None:
    cfg = _load_config_or_skip()
    sqlite_path = cfg.build_output_dir / "cbdb.sqlite"
    mdb_path = cfg.build_output_dir / "cbdb_data.mdb"
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

    from cbdb_parity.access_statuses_person import statuses_person_query_access
    from cbdb_parity.avalonia_statuses_person import (
        statuses_person_field_names,
        statuses_person_query,
    )
    from cbdb_parity.diff_report import diff_rows, write_report

    person_id = 1762

    avalonia_data = cfg.avalonia_repo / "Cbdb.App.Data"
    avalonia_rows = statuses_person_query(
        sqlite_path,
        person_id,
        avalonia_data_dir=avalonia_data,
    )
    access_rows = statuses_person_query_access(mdb_path, person_id)

    diff = diff_rows(
        avalonia_rows,
        access_rows,
        key_fields=("sequence", "status_code"),
        compare_fields=statuses_person_field_names(),
    )

    reports_dir = Path.cwd() / "reports"
    write_report(
        reports_dir,
        query_id="statuses_basic_person",
        request={"person_id": person_id},
        avalonia_rows=avalonia_rows,
        access_rows=access_rows,
        diff=diff,
        datadump_sha=sha,
    )

    assert diff.stats.matches, (
        f"statuses-person-pair diff for person_id={person_id} has mismatches: "
        f"only_in_avalonia={diff.stats.rows_only_in_avalonia}, "
        f"only_in_access={diff.stats.rows_only_in_access}, "
        f"value_mismatches={diff.stats.rows_value_mismatch}. "
        f"See reports/statuses_basic_person/ for detail."
    )
