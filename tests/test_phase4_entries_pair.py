"""Phase 4 / Tier 2 — entries per-person accessor (Avalonia vs Access).

Mirror of `test_phase4_altnames_pair`: same strict-pipeline gate,
same diff-key shape (raw ID column rather than post-processed display).
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


def test_entries_pair_smoke_end_to_end(tmp_path: Path) -> None:
    """Su Shi (person_id=1762) — canonical Song-dynasty figure with
    a known set of jinshi/recommendation/etc entries; small enough
    that the diff stays human-auditable but exercises most of the
    JOINs (kinship/association/source)."""
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

    from cbdb_parity.access_entries import entries_query_access
    from cbdb_parity.avalonia_entries import entries_field_names, entries_query
    from cbdb_parity.diff_report import diff_rows, write_report

    person_id = 1762

    avalonia_data = cfg.avalonia_repo / "Cbdb.App.Data"
    avalonia_rows = entries_query(
        sqlite_path,
        person_id,
        avalonia_data_dir=avalonia_data,
    )
    access_rows = entries_query_access(mdb_path, person_id)

    # Key on raw `entry_code` + `sequence` + `year` — ENTRY_DATA's
    # natural identifier within a person. Pure post-processed display
    # values stay out of the key so a diff on those surfaces as
    # value_mismatch instead of only_in_X.
    diff = diff_rows(
        avalonia_rows,
        access_rows,
        key_fields=("sequence", "year", "entry_code"),
        compare_fields=entries_field_names(),
    )

    reports_dir = Path.cwd() / "reports"
    write_report(
        reports_dir,
        query_id="entries_basic_person",
        request={"person_id": person_id},
        avalonia_rows=avalonia_rows,
        access_rows=access_rows,
        diff=diff,
        datadump_sha=sha,
    )

    assert diff.stats.matches, (
        f"entries-pair diff for person_id={person_id} has mismatches: "
        f"only_in_avalonia={diff.stats.rows_only_in_avalonia}, "
        f"only_in_access={diff.stats.rows_only_in_access}, "
        f"value_mismatches={diff.stats.rows_value_mismatch}. "
        f"See reports/entries_basic_person/ for detail."
    )
