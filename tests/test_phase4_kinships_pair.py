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


def _find_orphan_kin_person(
    sqlite_path: Path,
) -> tuple[int, int, frozenset[object]] | None:
    """Scan KIN_DATA for the first person whose kinship list
    includes at least one row pointing at a `c_kin_id` that has no
    matching `BIOG_MAIN.c_personid`.

    Returns `(person_id, expected_orphan_count, orphan_kin_ids)`
    or `None` if the current dataset has no such person.
    `orphan_kin_ids` is the set of `c_kin_id` values that flagged
    the gap (may include `None` if NULL c_kin_id contributed) so
    callers can verify the specific Avalonia-only rows ARE the
    orphan ones rather than a count-only check.

    Codex 7e round flagged two things:
    1. The earlier query had `AND kd.c_kin_id IS NOT NULL`, which
       missed the case where the upstream gap fires on NULL
       c_kin_id (cbdb_replay's INNER JOIN drops NULL since NULL =
       anything is unknown; Avalonia's LEFT JOIN keeps it). NULL
       rows are now included.
    2. A count-only assertion can be offset by an unrelated
       only-in-Avalonia divergence for the same person; the caller
       now uses the returned `orphan_kin_ids` set to verify row
       identity, not just count.
    """
    import sqlite3
    with sqlite3.connect(sqlite_path) as conn:
        # Find the affected person with the most orphans.
        head = conn.execute(
            """
            SELECT kd.c_personid, COUNT(*) AS orphan_count
            FROM KIN_DATA kd
            LEFT JOIN BIOG_MAIN bm ON bm.c_personid = kd.c_kin_id
            WHERE bm.c_personid IS NULL
            GROUP BY kd.c_personid
            ORDER BY COUNT(*) DESC, kd.c_personid ASC
            LIMIT 1
            """
        ).fetchone()
        if head is None:
            return None
        person_id, expected_orphan_count = int(head[0]), int(head[1])

        # Capture the specific c_kin_id values that were orphans for
        # that person; the caller will check these against the
        # diff's only-in-Avalonia bucket.
        kin_ids = conn.execute(
            """
            SELECT kd.c_kin_id
            FROM KIN_DATA kd
            LEFT JOIN BIOG_MAIN bm ON bm.c_personid = kd.c_kin_id
            WHERE bm.c_personid IS NULL
              AND kd.c_personid = ?
            """,
            (person_id,),
        ).fetchall()
    return person_id, expected_orphan_count, frozenset(r[0] for r in kin_ids)


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
    an orphan, modulo the existing preconditions inherited from
    the smoke test above: built `cbdb.sqlite` + `cbdb_data.mdb`,
    matching `build_manifest.json` SHA, and `pyodbc` available.
    Those gates remain `pytest.skip` causes (not failures), so
    "auto-arms" here means "fires when the upstream-data
    precondition becomes satisfiable", not "ignores the rest of
    the strict-pipeline gates".

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
            "c_kin_id has no matching BIOG_MAIN row, including NULL "
            "c_kin_id rows); the INNER vs LEFT JOIN gap described in "
            "reports/known_issues.md#kinships_basic_person cannot fire "
            "on this build. The test arms on any future dump that "
            "satisfies the smoke-test preconditions above AND has at "
            "least one orphan kin row."
        )
    person_id, expected_orphan_count, expected_orphan_kin_ids = found

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

    # Codex 7e round flagged that a count-only check (just
    # `rows_only_in_avalonia == expected_orphan_count`) could
    # silently pass if the person also has SOME OTHER source of
    # only-in-Avalonia divergence — the unrelated divergence
    # would inflate the count while masking the orphan rows
    # going missing. Verify by identity instead: collect the
    # `kin_person_id` values of the diff's only-in-Avalonia
    # bucket and require it to equal the orphan c_kin_id set we
    # computed at fixture-design time.

    # diff_rows exposes only summary stats; reconstruct the
    # only-in-Avalonia kin set by re-doing the key projection
    # locally. Per §0.b this is set difference on already-
    # produced rows, not a re-implementation of either upstream
    # query.
    av_kins = {(r.get("kin_person_id"), r.get("kin_code")) for r in avalonia_rows}
    ax_kins = {(r.get("kin_person_id"), r.get("kin_code")) for r in access_rows}
    only_av = av_kins - ax_kins
    only_av_kin_person_ids = {kin_pid for (kin_pid, _kin_code) in only_av}

    assert diff.stats.rows_only_in_avalonia == expected_orphan_count, (
        f"orphan-kin gap shape changed: expected exactly "
        f"{expected_orphan_count} only-in-Avalonia rows (the orphan "
        f"kin BIOG_MAIN doesn't have), got "
        f"{diff.stats.rows_only_in_avalonia}. Either cbdb_replay's "
        f"INNER JOIN behaviour changed, our LEFT-JOIN scan and "
        f"the pair test see different KIN_DATA rows, or the same "
        f"person has an unrelated divergence inflating the count."
    )
    # NULL c_kin_id rows show up here as `None`; the access bridge
    # never emits them so they are guaranteed to be only-in-Avalonia.
    # Use a coercion that treats DB-NULL as Python None on both sides
    # of the comparison.
    expected_set = {
        (None if kid is None else int(kid))
        for kid in expected_orphan_kin_ids
    }
    actual_set = {
        (None if kpid is None else int(kpid))
        for kpid in only_av_kin_person_ids
    }
    assert actual_set == expected_set, (
        f"only-in-Avalonia rows are not the documented orphan kin: "
        f"expected kin set {sorted(repr(x) for x in expected_set)}, "
        f"got {sorted(repr(x) for x in actual_set)}. The gap shape "
        f"described in known_issues#kinships_basic_person has changed; "
        f"investigate before refreshing the suppression."
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
