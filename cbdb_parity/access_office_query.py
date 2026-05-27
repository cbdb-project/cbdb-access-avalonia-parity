"""Access-side bridge for the Phase 3d office-query pair.

Mirrors `cbdb_parity.access_query` (Phase 3c) but wraps
`cbdb_replay.lookatoffice` instead of `lookatentry`. Returns row dicts
shaped against the Avalonia field names so `diff_rows(...)` can compare
the two backends without further normalisation.

Per WORK_PLAN §1's strict-pipeline rule, `mdb_path` MUST be the
Phase 1.3b-generated `cbdb_data.mdb` from the SAME Datadump that
produced cbdb.sqlite.

Scope: cbdb_replay's LookAtOffice covers the "office_codes + index year
filter + office year filter" branches. It does NOT model the
person/office place-id filters or the person_keyword search of the
Avalonia request, and its dynasty handling uses a single from/to pair
rather than the list-of-ids the Avalonia request exposes. Requests
that use any of those unsupported branches are rejected with
NotImplementedError — silently dropping them would let the Access side
run a broader query than Avalonia and produce false parity mismatches.
Phase 4 will widen the bridge as the cross-section grows.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_office_query import OfficeQueryRequest


def _ensure_cbdb_replay_on_path(access_tests_repo: Path) -> None:
    """Mirror of `cbdb_parity.access_query._ensure_cbdb_replay_on_path`."""
    tests_dir = access_tests_repo / "tests"
    tests_dir_str = str(tests_dir)
    if tests_dir_str not in sys.path:
        sys.path.insert(0, tests_dir_str)


# Avalonia OfficeQueryRecord field → cbdb_replay/lookatoffice column name.
# Restricted to columns both backends emit with the SAME semantics. The
# Avalonia query exposes ~65 columns (labels, joins to lookup tables,
# CASE expressions); the replay emits 17 raw columns. Anything that
# requires a join the replay doesn't make (office_label, appointment
# desc, ganzhi descriptions, etc.) is omitted from this map. Phase 4
# can widen the cross-section by either teaching cbdb_replay the
# missing joins or doing post-fetch lookups Python-side.
#
# `office_addr_id` is special: it comes from the post-fetch
# POSTED_TO_ADDR_DATA expansion (see `office_query_access`), not from
# the lookatoffice replay itself. It is part of the cross-section
# because the Avalonia query LEFT JOINs POSTED_TO_ADDR_DATA, which can
# fan a single posting into >1 row.
_COMMON_FIELDS_AVALONIA_TO_REPLAY: dict[str, str] = {
    "person_id":        "c_personid",
    "name":             "c_name",
    "name_chn":         "c_name_chn",
    "index_year":       "c_index_year",
    "office_code":      "c_office_id",
    "posting_id":       "c_posting_id",
    "sequence":         "c_sequence",
    "first_year":       "c_firstyear",
    "last_year":        "c_lastyear",
    "assume_office_code": "c_assume_office_code",
    "inst_code":        "c_inst_code",
    "source_id":        "c_source",
    "index_addr_id":    "c_person_addr_id",
    "office_addr_id":   "c_office_addr_id",
}


def office_query_common_fields() -> tuple[str, ...]:
    """Avalonia field names of the columns this bridge can compare."""
    return tuple(_COMMON_FIELDS_AVALONIA_TO_REPLAY.keys())


def _avalonia_request_to_replay_inputs(request: OfficeQueryRequest) -> Any:
    """Map `OfficeQueryRequest` → `cbdb_replay.lookatoffice.OfficeQueryInputs`.

    Year-filter selection mirrors `cbdb_parity.access_query`:
      - `use_office_year_range` → cbdb_replay's separate
        `use_office_years` / `office_from_year` / `office_to_year`.
      - `use_index_year_range` → `YearFilter(mode='index')`.
      - dynasty-only filters fall back to `mode='none'` (cbdb_replay
        models dynasty as a single from/to pair, not a list of ids;
        Phase 3d smoke tests don't exercise that branch).

    Avalonia filters cbdb_replay's LookAtOffice CANNOT honour are
    rejected upfront — silently dropping them would let the Access side
    run a broader query than Avalonia and produce false parity
    mismatches. Phase 4 can either teach cbdb_replay these branches or
    bypass the replay with a direct pyodbc SELECT.
    """
    # Reject branches where cbdb_replay/lookatoffice would NOT match the
    # Avalonia SQL.
    #
    # Note on subordinate-units flags: Avalonia evaluates them as a
    # no-op when the corresponding place-id list is empty (the C# code
    # only appends those WHERE clauses inside `if (request.*PlaceIds.
    # Count > 0)` blocks). So we only flag them when their gating
    # place-id list is also set.
    #
    # Note on office_codes: cbdb_replay's lookatoffice early-returns an
    # empty DataFrame when `office_codes` is None/empty, while Avalonia
    # would happily run an unfiltered office-wide query. Allowing that
    # shape through would silently report "Access has zero rows" against
    # whatever Avalonia returned. Reject it explicitly here.
    unsupported: list[str] = []
    if request.person_keyword and request.person_keyword.strip():
        unsupported.append("person_keyword")
    if request.dynasty_ids:
        unsupported.append("dynasty_ids")
    if request.person_place_ids:
        unsupported.append("person_place_ids")
    if request.office_place_ids:
        unsupported.append("office_place_ids")
    if request.include_subordinate_person_units and request.person_place_ids:
        unsupported.append("include_subordinate_person_units")
    if request.include_subordinate_office_units and request.office_place_ids:
        unsupported.append("include_subordinate_office_units")
    if not request.office_codes:
        unsupported.append("office_codes (empty — cbdb_replay returns no rows; "
                          "Avalonia runs unfiltered)")
    if unsupported:
        raise NotImplementedError(
            "cbdb_replay/lookatoffice does not model these OfficeQueryRequest "
            f"branches; cannot give a faithful Access replay: {sorted(unsupported)!r}. "
            "Drop them from the parity request or extend the bridge to handle "
            "them before treating its output as the Access ground truth."
        )

    from cbdb_replay.common import YearFilter
    from cbdb_replay.lookatoffice import OfficeQueryInputs

    if request.use_index_year_range:
        year_filter = YearFilter(
            mode="index",
            from_year=min(request.index_year_from, request.index_year_to),
            to_year=max(request.index_year_from, request.index_year_to),
        )
    else:
        year_filter = YearFilter(mode="none")

    use_office_years = request.use_office_year_range
    if use_office_years:
        office_from_year: int | None = min(request.office_year_from, request.office_year_to)
        office_to_year: int | None = max(request.office_year_from, request.office_year_to)
    else:
        office_from_year = None
        office_to_year = None

    office_codes_int: list[int] | None
    if request.office_codes:
        try:
            office_codes_int = [int(c) for c in request.office_codes]
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"non-integer office_code in Avalonia request: {list(request.office_codes)!r}"
            ) from exc
    else:
        office_codes_int = None

    return OfficeQueryInputs(
        office_codes=office_codes_int,
        year_filter=year_filter,
        use_office_years=use_office_years,
        office_from_year=office_from_year,
        office_to_year=office_to_year,
    )


def _replay_row_to_avalonia_shape(replay_row: dict[str, Any]) -> dict[str, Any]:
    """Project a cbdb_replay/lookatoffice row dict onto Avalonia field
    names, applying the column-level normalisations Avalonia bakes into
    its SELECT so the two sides compare apples to apples:

    - `office_code`: cast to str — Avalonia's SELECT does
      `CAST(pto.c_office_id AS TEXT)`. Replay returns the raw int.
    - `sequence`:    NULL → 0 — Avalonia's SELECT does
      `COALESCE(pto.c_sequence, 0)`. Forwarding the raw `None` would
      diverge both the compared value AND the diff key (sequence is
      part of `key_fields` in test_phase3d_office_pair), producing
      false only-in-X mismatches for postings with NULL sequence.
    """
    out: dict[str, Any] = {}
    for av_field, replay_col in _COMMON_FIELDS_AVALONIA_TO_REPLAY.items():
        value = replay_row.get(replay_col)
        if av_field == "office_code" and value is not None:
            value = str(value)
        elif av_field == "sequence" and value is None:
            value = 0
        out[av_field] = value
    return out


def office_query_access(
    mdb_path: Path,
    request: OfficeQueryRequest,
    *,
    access_tests_repo: Path,
) -> list[dict[str, Any]]:
    """Run the Access-side equivalent of OfficeQueryRequest.

    Returns rows in the common-fields cross-section, keyed by Avalonia
    field names so they can be diffed directly against
    `cbdb_parity.avalonia_office_query.office_query(...)` output.

    Ordering / limit: mirrors what the Avalonia SQL appends, with the
    Access label lookup post-fetch. The Avalonia ORDER BY is
        office_label, pto.c_firstyear, b.c_personid, pto.c_posting_id,
        pto.c_sequence, pta.c_addr_id
    so we must (a) know each row's office_label (post-fetched from
    OFFICE_CODES; the replay doesn't join that lookup), and (b) expand
    each lookatoffice row by every matching POSTED_TO_ADDR_DATA address
    so the LEFT JOIN cardinality matches Avalonia (one posting can
    produce N >= 1 rows, one per office address; postings without a
    POSTED_TO_ADDR_DATA match still produce one row with office_addr_id
    = NULL, mirroring the LEFT-JOIN miss).

    Only AFTER that expansion can the `LIMIT N` truncation safely be
    applied to the same canonical row set Avalonia truncates.
    """
    _ensure_cbdb_replay_on_path(access_tests_repo)
    import pyodbc
    from cbdb_replay.lookatoffice import run as replay_run

    inputs = _avalonia_request_to_replay_inputs(request)
    conn_str = (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        rf"DBQ={mdb_path};"
    )
    with pyodbc.connect(conn_str) as conn:
        df = replay_run(conn, inputs)
        cursor = conn.cursor()

        # OFFICE_CODES label map for the ORDER BY mirror. Small table
        # (~30k rows) — fetching once is cheaper than per-row JOINs.
        # Mirror Avalonia's COALESCE — first non-NULL wins.
        cursor.execute(
            "SELECT c_office_id, c_office_chn, c_office_trans, c_office_pinyin "
            "FROM OFFICE_CODES"
        )
        office_labels: dict[int, str | None] = {}
        for code, chn, trans, pinyin in cursor.fetchall():
            # IMPORTANT: compare to `None` (NULL-only fallback), not
            # truthiness — empty strings should NOT trigger fallback in
            # SQL COALESCE, and we replicate that contract here.
            label = chn if chn is not None else (
                trans if trans is not None else pinyin
            )
            office_labels[int(code)] = label

        # Post-fetch POSTED_TO_ADDR_DATA expansion. Avalonia's LEFT JOIN
        # is on (posting_id, office_id, personid). For each lookatoffice
        # row we look up every matching c_addr_id (preserving LEFT-JOIN
        # semantics with a single NULL row when no match exists).
        base_records: list[dict[str, Any]] = df.to_dict("records")
        addrs_by_key: dict[tuple[int, int, int], list[int | None]] = {}
        if base_records:
            keys = [
                (
                    int(r["c_posting_id"]) if r.get("c_posting_id") is not None else None,
                    int(r["c_office_id"]) if r.get("c_office_id") is not None else None,
                    int(r["c_personid"]) if r.get("c_personid") is not None else None,
                )
                for r in base_records
            ]
            unique_keys = {k for k in keys if None not in k}
            # Access ODBC handles ~1000-element IN-lists comfortably; batch
            # if there are more lookatoffice rows than that.
            BATCH = 800
            unique_list = list(unique_keys)
            for start in range(0, len(unique_list), BATCH):
                batch = unique_list[start:start + BATCH]
                if not batch:
                    continue
                # Build the 3-column-tuple IN clause manually — Access
                # ODBC doesn't support tuple-IN syntax, so we OR together
                # AND-triplets. Parameter style is `?`.
                placeholders = " OR ".join(
                    "(c_posting_id = ? AND c_office_id = ? AND c_personid = ?)"
                    for _ in batch
                )
                flat_params: list[int] = []
                for pid, oid, perid in batch:
                    flat_params.extend([pid, oid, perid])  # type: ignore[list-item]
                cursor.execute(
                    f"SELECT c_posting_id, c_office_id, c_personid, c_addr_id "
                    f"FROM POSTED_TO_ADDR_DATA WHERE {placeholders}",
                    flat_params,
                )
                for posting_id, office_id, personid, addr_id in cursor.fetchall():
                    key = (int(posting_id), int(office_id), int(personid))
                    addrs_by_key.setdefault(key, []).append(
                        int(addr_id) if addr_id is not None else None
                    )

        cursor.close()

    # Build the expanded record list. Rows without a POSTED_TO_ADDR_DATA
    # match get a single output row with c_office_addr_id = None
    # (the LEFT-JOIN miss). Rows with N matches produce N output rows.
    expanded: list[dict[str, Any]] = []
    for r in base_records:
        key = (
            int(r["c_posting_id"]) if r.get("c_posting_id") is not None else None,
            int(r["c_office_id"]) if r.get("c_office_id") is not None else None,
            int(r["c_personid"]) if r.get("c_personid") is not None else None,
        )
        addrs = addrs_by_key.get(key, []) if None not in key else []  # type: ignore[operator]
        if not addrs:
            row = dict(r)
            row["c_office_addr_id"] = None
            expanded.append(row)
        else:
            for addr in addrs:
                row = dict(r)
                row["c_office_addr_id"] = addr
                expanded.append(row)

    effective_limit = max(1, min(request.limit, 10000))

    def _sort_key(r: dict[str, Any]) -> tuple[Any, ...]:
        code = r.get("c_office_id")
        label = office_labels.get(int(code), "") if code is not None else ""
        # Full Avalonia ORDER BY suffix; None values get sentinels so
        # the comparator is total. addr_id sentinel uses -1 so NULL
        # office_addr_id sorts before any real id (matching SQLite's
        # NULL-first ascending ordering — Avalonia issues a bare
        # ORDER BY which under SQLite default settings places NULLs
        # before non-NULLs).
        return (
            label if label is not None else "",
            r.get("c_firstyear") if r.get("c_firstyear") is not None else -10**9,
            r.get("c_personid") if r.get("c_personid") is not None else -1,
            r.get("c_posting_id") if r.get("c_posting_id") is not None else -1,
            r.get("c_sequence") if r.get("c_sequence") is not None else -1,
            r.get("c_office_addr_id") if r.get("c_office_addr_id") is not None else -1,
        )

    expanded.sort(key=_sort_key)
    expanded = expanded[:effective_limit]

    return [_replay_row_to_avalonia_shape(r) for r in expanded]


__all__ = [
    "office_query_access",
    "office_query_common_fields",
]
