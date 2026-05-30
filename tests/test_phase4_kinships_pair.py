"""Phase 4 / Tier 2 — kinships per-person accessor (Avalonia vs Access).

Covers GetKinshipsAsync's direct (expandNetwork=false) branch.
The expandNetwork=true graph-traversal branch is not replicated.
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


def test_kinships_pair_smoke_end_to_end(tmp_path: Path) -> None:
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

    from cbdb_parity.access_kinships import (
        kinships_common_fields,
        kinships_query_access,
    )
    from cbdb_parity.avalonia_kinships import kinships_query
    from cbdb_parity.diff_report import diff_rows, write_report

    person_id = 1762

    avalonia_data = cfg.avalonia_repo / "Cbdb.App.Data"
    avalonia_rows = kinships_query(
        sqlite_path,
        person_id,
        avalonia_data_dir=avalonia_data,
    )
    access_rows = kinships_query_access(
        mdb_path, person_id, access_tests_repo=cfg.access_tests_repo,
    )

    # Per WORK_PLAN §0.b: only diff on raw columns both backends emit
    # without transcribed formatting. Excludes `kinship` (Avalonia's
    # JoinDisplay output), `source` / `pages` / `notes` (cbdb_replay
    # doesn't fetch them).
    diff = diff_rows(
        avalonia_rows,
        access_rows,
        key_fields=("kin_person_id", "kin_code"),
        compare_fields=kinships_common_fields(),
    )

    reports_dir = Path.cwd() / "reports"
    write_report(
        reports_dir,
        query_id="kinships_basic_person",
        request={"person_id": person_id},
        avalonia_rows=avalonia_rows,
        access_rows=access_rows,
        diff=diff,
        datadump_sha=sha,
    )

    assert diff.stats.matches, (
        f"kinships-pair diff for person_id={person_id} has mismatches: "
        f"only_in_avalonia={diff.stats.rows_only_in_avalonia}, "
        f"only_in_access={diff.stats.rows_only_in_access}, "
        f"value_mismatches={diff.stats.rows_value_mismatch}. "
        f"See reports/kinships_basic_person/ for detail."
    )


def _find_orphan_kin_person(sqlite_path: Path) -> tuple[int, int] | None:
    """Scan KIN_DATA for the first person whose kinship list
    includes at least one row pointing at a `c_kin_id` that has no
    matching `BIOG_MAIN.c_personid`.

    Returns `(person_id, expected_orphan_count)` or `None` if the
    current dataset has no such person. Used by the Phase 7e
    orphan-kin proof case.

    NOTE: this is the SAME orphan condition that
    `reports/known_issues.md#kinships_basic_person` describes —
    cbdb_replay's INNER JOIN would drop these rows while Avalonia's
    LEFT JOIN would surface them with NULL kin names. The Datadump
    we built the harness against happens to have zero such rows
    (verified 2026-05-31); the test below skips with a precise
    diagnostic when that's the case and arms automatically the
    moment a future dump produces any.
    """
    import sqlite3
    with sqlite3.connect(sqlite_path) as conn:
        row = conn.execute(
            """
            SELECT kd.c_personid, COUNT(*) AS orphan_count
            FROM KIN_DATA kd
            LEFT JOIN BIOG_MAIN bm ON bm.c_personid = kd.c_kin_id
            WHERE bm.c_personid IS NULL
              AND kd.c_kin_id IS NOT NULL
            GROUP BY kd.c_personid
            ORDER BY COUNT(*) DESC, kd.c_personid ASC
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        return None
    return int(row[0]), int(row[1])


def test_kinships_pair_orphan_kin_documented_divergence(tmp_path: Path) -> None:
    """Phase 7e — executable evidence for the
    `kinships_basic_person` known-issue (INNER vs LEFT JOIN orphan-
    kin gap).

    Strategy: at runtime, scan the canonical build for a person whose
    KIN_DATA includes orphan kin (c_kin_id with no BIOG_MAIN match).
    If found, run the standard kinships pair against that person
    and EXPECT the documented divergence shape: cbdb_replay drops
    the orphan rows while Avalonia (via ParityHost) keeps them.

    If the current dataset has zero orphan kin (the 2026-04-30
    Datadump's actual state), skip with a precise diagnostic. The
    test arms automatically the moment a future Datadump produces
    an orphan, which is the executable-evidence outcome WORK_PLAN
    Phase 7e called for.

    Per §0.b: no transcription in the test itself — both arms route
    through their respective upstream code (cbdb_replay.lookatkinship
    + ParityHost). The assertion just pins the documented shape of
    the divergence.
    """
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
            f"strict-pipeline rule: sqlite and mdb must share a SHA AND "
            f"the manifest's recorded paths must resolve to "
            f"{sqlite_path} / {mdb_path}; manifest={manifest} sha={sha!r}"
        )

    try:
        import pyodbc  # noqa: F401
    except ImportError:
        pytest.skip("pyodbc not installed")

    found = _find_orphan_kin_person(sqlite_path)
    if found is None:
        pytest.skip(
            "current Datadump has zero orphan kin (KIN_DATA rows whose "
            "c_kin_id has no matching BIOG_MAIN row); the INNER vs LEFT "
            "JOIN gap described in reports/known_issues.md#kinships_basic_person "
            "cannot fire on this build. The test arms automatically on "
            "any future dump that has at least one orphan."
        )
    person_id, expected_orphan_count = found

    from cbdb_parity.access_kinships import (
        kinships_common_fields,
        kinships_query_access,
    )
    from cbdb_parity.avalonia_kinships import kinships_query
    from cbdb_parity.diff_report import diff_rows

    avalonia_data = cfg.avalonia_repo / "Cbdb.App.Data"
    avalonia_rows = kinships_query(
        sqlite_path, person_id, avalonia_data_dir=avalonia_data,
    )
    access_rows = kinships_query_access(
        mdb_path, person_id, access_tests_repo=cfg.access_tests_repo,
    )

    diff = diff_rows(
        avalonia_rows,
        access_rows,
        key_fields=("kin_person_id", "kin_code"),
        compare_fields=kinships_common_fields(),
    )

    # The documented divergence shape: orphan-kin rows appear on
    # the Avalonia side (LEFT JOIN keeps them) but not on the
    # Access side (INNER JOIN drops them). They land in the
    # diff's "only_in_avalonia" bucket. The count must match the
    # number of orphans we counted directly against BIOG_MAIN.
    assert diff.stats.rows_only_in_avalonia == expected_orphan_count, (
        f"orphan-kin gap shape changed: expected exactly "
        f"{expected_orphan_count} only-in-Avalonia rows (the orphan "
        f"kin BIOG_MAIN doesn't have), got "
        f"{diff.stats.rows_only_in_avalonia}. Either cbdb_replay's "
        f"INNER JOIN behaviour changed, or our LEFT-JOIN scan and "
        f"the pair test see different KIN_DATA rows."
    )
    assert diff.stats.rows_only_in_access == 0, (
        f"unexpected only-in-Access rows: {diff.stats.rows_only_in_access}. "
        f"That direction shouldn't happen — cbdb_replay's INNER JOIN "
        f"is a subset of Avalonia's LEFT JOIN row set, not a "
        f"superset."
    )
    # Value mismatches on matched rows are a SEPARATE class from
    # the orphan-kin gap and would indicate a real cross-engine
    # divergence (e.g. step counts diverge). Surface that loudly
    # rather than hide it under the orphan suppression.
    assert diff.stats.rows_value_mismatch == 0, (
        f"value mismatches on matched (non-orphan) rows: "
        f"{diff.stats.rows_value_mismatch}. That's a real cross-engine "
        f"divergence outside the known orphan-kin gap; investigate."
    )
