"""Access-side bridge for the Phase 3e status-query pair.

Mirrors `cbdb_parity.access_office_query` / `cbdb_parity.access_query`:
wraps `cbdb_replay.lookatstatus`, projects rows onto the Avalonia
field names, sorts and clamps to match the Avalonia ORDER BY / LIMIT.

Per WORK_PLAN §1, `mdb_path` MUST be the Phase 1.3b / 1.6 generated
`cbdb_data.mdb` from the same Datadump that produced cbdb.sqlite.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_status_query import StatusQueryRequest


def _ensure_cbdb_replay_on_path(access_tests_repo: Path) -> None:
    tests_dir = access_tests_repo / "tests"
    tests_dir_str = str(tests_dir)
    if tests_dir_str not in sys.path:
        sys.path.insert(0, tests_dir_str)


# Avalonia field → cbdb_replay/lookatstatus column. Restricted to
# columns both sides emit with the same semantics.
_COMMON_FIELDS_AVALONIA_TO_REPLAY: dict[str, str] = {
    "person_id":         "c_personid",
    "name":              "c_name",
    "name_chn":          "c_name_chn",
    "index_year":        "c_index_year",
    "index_address_id":  "c_addr_id",
    "sequence":          "c_sequence",
    "status_code":       "c_status_code",
    "source_id":         "c_source",
}


def status_query_common_fields() -> tuple[str, ...]:
    return tuple(_COMMON_FIELDS_AVALONIA_TO_REPLAY.keys())


def _lookup_dynasty_year_range(
    mdb_path: Path,
    dynasty_ids: tuple[int, ...] | list[int] | Any,
) -> tuple[int, int, int, int] | None:
    """Look up `(from_dynasty, to_dynasty, from_dynasty_begin, to_dynasty_end)`
    for a set of Avalonia `dynasty_ids` by reading the DYNASTIES table.

    cbdb_replay's `year_mode='dynasty'` expects the four values together
    (from/to bracket on c_dy and on c_dy_begin_year / c_dy_end_year).
    Avalonia exposes only the list of `dynasty_ids`; we materialise the
    equivalent range here.

    Returns `None` when no rows match (caller should treat as empty result).
    """
    import pyodbc

    ids = [int(d) for d in dynasty_ids]
    if not ids:
        return None
    placeholders = ",".join("?" for _ in ids)
    conn_str = (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        rf"DBQ={mdb_path};"
    )
    with pyodbc.connect(conn_str) as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT MIN(c_dy), MAX(c_dy), MIN(c_start), MAX(c_end) "
            f"FROM DYNASTIES WHERE c_dy IN ({placeholders})",
            *ids,
        )
        row = cur.fetchone()
        cur.close()
    if row is None or row[0] is None:
        return None
    return int(row[0]), int(row[1]), int(row[2] or 0), int(row[3] or 0)


def _avalonia_request_to_replay_inputs(
    request: StatusQueryRequest,
    *,
    mdb_path: Path | None = None,
) -> Any | None:
    """Map StatusQueryRequest → cbdb_replay.lookatstatus.StatusQueryInputs.

    Returns `None` to signal the caller should short-circuit to an
    empty result (used for `status_codes=()`, where cbdb_replay
    returns no rows AND Avalonia returns no rows because its SELECT
    requires `c_status_code IN (...)`-style filtering by the picker).

    Rejects (raises NotImplementedError) only for genuinely
    unsupported request shapes (currently `person_keyword`, which
    cbdb_replay/lookatstatus has no input slot for).
    """
    if request.person_keyword and request.person_keyword.strip():
        raise NotImplementedError(
            "cbdb_replay/lookatstatus does not model `person_keyword`; "
            "the picker writes selected IDs, not a free-text keyword."
        )

    # Empty status_codes: both sides agree on empty results after
    # the upstream Avalonia commit added the picker-contract
    # short-circuit (SqliteStatusQueryService.QueryAsync now early-
    # returns Array.Empty<…> when StatusCodes.Count == 0, matching
    # cbdb_replay's behavior). Signal short-circuit to the caller.
    if not request.status_codes:
        return None

    from cbdb_replay.lookatstatus import StatusQueryInputs

    year_mode: str = "none"
    from_year: int | None = None
    to_year: int | None = None
    from_dynasty: int | None = None
    to_dynasty: int | None = None
    from_dynasty_begin: int | None = None
    to_dynasty_end: int | None = None

    if request.use_index_year_range:
        year_mode = "index"
        from_year = min(request.index_year_from, request.index_year_to)
        to_year = max(request.index_year_from, request.index_year_to)
    elif request.dynasty_ids:
        # Multi-dynasty fan-out is handled in status_query_access;
        # this translator only sees the single-dy case.
        assert len(request.dynasty_ids) == 1, (
            f"_avalonia_request_to_replay_inputs expects ≤1 dynasty_id; "
            f"caller must fan out multi-dy requests. Got "
            f"{tuple(request.dynasty_ids)!r}."
        )
        if mdb_path is None:
            raise RuntimeError(
                "dynasty_ids translation requires `mdb_path` so DYNASTIES "
                "can be queried for the begin/end year range."
            )
        looked = _lookup_dynasty_year_range(mdb_path, request.dynasty_ids)
        if looked is None:
            # No matching dynasty rows: equivalent to zero results.
            return None
        from_dynasty, to_dynasty, from_dynasty_begin, to_dynasty_end = looked
        year_mode = "dynasty"

    try:
        status_codes_int: list[int] = [int(c) for c in request.status_codes]
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"non-integer status_code in Avalonia request: {list(request.status_codes)!r}"
        ) from exc

    addr_ids = list(request.place_ids) if request.place_ids else None

    return StatusQueryInputs(
        status_codes=status_codes_int,
        addr_ids=addr_ids,
        include_subunits=request.include_subordinate_units,
        use_xy_radius=False,
        year_mode=year_mode,  # type: ignore[arg-type]
        from_year=from_year,
        to_year=to_year,
        from_dynasty=from_dynasty,
        to_dynasty=to_dynasty,
        from_dynasty_begin=from_dynasty_begin,
        to_dynasty_end=to_dynasty_end,
    )


def _replay_row_to_avalonia_shape(replay_row: dict[str, Any]) -> dict[str, Any]:
    """Project a replay row dict onto Avalonia field names. Mirrors the
    same per-column normalisations the Avalonia SELECT bakes in:
      - `status_code`: int → str (Avalonia does CAST(... AS TEXT)).
      - `sequence`: NULL → 0 (Avalonia does COALESCE(..., 0)).
    """
    import math

    out: dict[str, Any] = {}
    for av_field, replay_col in _COMMON_FIELDS_AVALONIA_TO_REPLAY.items():
        value = replay_row.get(replay_col)
        # pandas NaN → None (see access_query.py _replay_row_to_avalonia_shape
        # for the full rationale; both shape functions need the same
        # SQL-NULL normalisation).
        if isinstance(value, float) and math.isnan(value):
            value = None
        if av_field == "status_code" and value is not None:
            value = str(value)
        elif av_field == "sequence" and value is None:
            value = 0
        out[av_field] = value
    return out


def status_query_access(
    mdb_path: Path,
    request: StatusQueryRequest,
    *,
    access_tests_repo: Path,
) -> list[dict[str, Any]]:
    """Run the Access-side equivalent of a StatusQueryRequest.

    Multi-dynasty requests fan out per-id (cbdb_replay's dynasty mode
    only models a contiguous from/to range); single-dy and no-dy
    requests go through `_status_query_access_single`.
    """
    if len(request.dynasty_ids) > 1:
        from dataclasses import replace
        import pyodbc
        combined: list[dict[str, Any]] = []
        seen: set[tuple[Any, Any]] = set()
        for dy in request.dynasty_ids:
            sub = replace(request, dynasty_ids=(dy,))
            for row in _status_query_access_single(
                mdb_path, sub, access_tests_repo=access_tests_repo
            ):
                key = (row.get("person_id"), row.get("sequence"))
                if key in seen:
                    continue
                seen.add(key)
                combined.append(row)
        # Avalonia's `ORDER BY status_label, c_personid, c_sequence`
        # — re-sort with the actual STATUS_CODES label before clamping.
        # Without this the merged top-N slice depends on dynasty_ids
        # iteration order (codex round-12 P1).
        conn_str = (
            r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
            rf"DBQ={mdb_path};"
        )
        # pyodbc context exit commits but does not close — explicit
        # close to avoid leaking ODBC handles (codex round-13 P2).
        conn = pyodbc.connect(conn_str)
        try:
            cur = conn.cursor()
            cur.execute("SELECT c_status_code, c_status_desc, c_status_desc_chn FROM STATUS_CODES")
            status_labels: dict[str, str] = {}
            for code, desc, desc_chn in cur.fetchall():
                label = desc_chn if desc_chn is not None else desc
                status_labels[str(code)] = label if label is not None else ""
            cur.close()
        finally:
            conn.close()
        combined.sort(key=lambda r: (
            status_labels.get(str(r.get("status_code") or ""), ""),
            r.get("person_id") if r.get("person_id") is not None else -1,
            r.get("sequence") if r.get("sequence") is not None else -1,
        ))
        return combined[: max(1, min(request.limit, 100000))]
    return _status_query_access_single(
        mdb_path, request, access_tests_repo=access_tests_repo
    )


def _status_query_access_single(
    mdb_path: Path,
    request: StatusQueryRequest,
    *,
    access_tests_repo: Path,
) -> list[dict[str, Any]]:
    """Single-dynasty (or no-dynasty) Access-side replay."""
    _ensure_cbdb_replay_on_path(access_tests_repo)
    import pyodbc
    from cbdb_replay.lookatstatus import run as replay_run

    inputs = _avalonia_request_to_replay_inputs(request, mdb_path=mdb_path)
    # Short-circuit: empty status_codes (or no-match dynasty_ids) → both
    # backends return the empty list, no need to round-trip cbdb_replay.
    if inputs is None:
        return []
    conn_str = (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        rf"DBQ={mdb_path};"
    )
    with pyodbc.connect(conn_str) as conn:
        df = replay_run(conn, inputs)
        # STATUS_CODES is small (~hundreds of rows); fetch once for the
        # ORDER BY mirror. Avalonia uses
        # `COALESCE(sc.c_status_desc_chn, sc.c_status_desc)`.
        cursor = conn.cursor()
        cursor.execute(
            "SELECT c_status_code, c_status_desc, c_status_desc_chn FROM STATUS_CODES"
        )
        status_labels: dict[int, str | None] = {}
        for code, desc, desc_chn in cursor.fetchall():
            label = desc_chn if desc_chn is not None else desc
            status_labels[int(code)] = label
        cursor.close()

    records = df.to_dict("records")

    effective_limit = max(1, min(request.limit, 100000))

    def _sort_key(r: dict[str, Any]) -> tuple[Any, ...]:
        code = r.get("c_status_code")
        label = status_labels.get(int(code), "") if code is not None else ""
        return (
            label if label is not None else "",
            r.get("c_personid") if r.get("c_personid") is not None else -1,
            r.get("c_sequence") if r.get("c_sequence") is not None else -1,
        )

    records.sort(key=_sort_key)
    records = records[:effective_limit]

    return [_replay_row_to_avalonia_shape(r) for r in records]


__all__ = [
    "status_query_access",
    "status_query_common_fields",
]
