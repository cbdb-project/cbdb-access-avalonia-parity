"""Phase 4 / Tier 2 — altnames per-person accessor (Avalonia vs Access).

First Tier 2 query landed (per `coverage/matrix.md`). The Avalonia
side runs `SqlitePersonBrowserService.GetAltNamesAsync` SQL against
cbdb.sqlite; the Access side runs the same-shape SQL against
cbdb_data.mdb via pyodbc. JoinDisplay post-fetch is applied on both
sides so the row dicts diff cleanly.

Same skip semantics as Phase 3c/3d/3e: prerequisites must exist and
the build_manifest must record both products at the current Datadump
SHA at the paths the test opens.
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


def test_altnames_pair_smoke_end_to_end(tmp_path: Path) -> None:
    """Person 1762 (the test corpus's canonical example, Su Shi) has
    multiple alt names; small, well-known, stable across Datadumps."""
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

    from cbdb_parity.access_altnames import altnames_query_access
    from cbdb_parity.avalonia_altnames import altnames_field_names, altnames_query
    from cbdb_parity.diff_report import diff_rows, write_report

    person_id = 1762  # Su Shi — canonical example in CBDB tests

    avalonia_data = cfg.avalonia_repo / "Cbdb.App.Data"
    avalonia_rows = altnames_query(
        sqlite_path,
        person_id,
        avalonia_data_dir=avalonia_data,
    )
    access_rows = altnames_query_access(mdb_path, person_id)

    # Diff key uses the RAW identifier columns (`name_type_code`,
    # `source_id`) that both sides surface alongside the user-visible
    # `PersonAltNameItem` payload. Keying on the post-processed
    # `name_type` / `source` display strings would be unstable: if
    # those values disagree between Access and Avalonia (which is
    # exactly what we want the diff to surface as a value_mismatch),
    # the same logical row would split into only_in_X + only_in_Y
    # instead. The raw codes are by definition identical from both
    # backends since both read them directly from the same ALTNAME_DATA
    # table.
    diff = diff_rows(
        avalonia_rows,
        access_rows,
        key_fields=("sequence", "alt_name_chn", "name_type_code", "source_id"),
        compare_fields=altnames_field_names(),
    )

    reports_dir = Path.cwd() / "reports"
    write_report(
        reports_dir,
        query_id="altnames_basic",
        request={"person_id": person_id},
        avalonia_rows=avalonia_rows,
        access_rows=access_rows,
        diff=diff,
        datadump_sha=sha,
    )

    assert diff.stats.matches, (
        f"altnames-pair diff for person_id={person_id} has mismatches: "
        f"only_in_avalonia={diff.stats.rows_only_in_avalonia}, "
        f"only_in_access={diff.stats.rows_only_in_access}, "
        f"value_mismatches={diff.stats.rows_value_mismatch}. "
        f"See reports/altnames_basic/ for detail."
    )
