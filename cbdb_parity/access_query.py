"""Access-side query bridge — drives the existing cbdb_replay
implementations against the generated `cbdb_data.mdb` (Phase 3b).

Per WORK_PLAN §1's strict-pipeline rule, the mdb passed in MUST be the
Phase 1.3b-generated `cbdb_data.mdb` from the SAME Datadump that
produced cbdb.sqlite — never the user's pre-existing mdb files.

We import `cbdb_replay.lookatentry` (and siblings) from
`$ACCESS_TESTS_REPO/tests/cbdb_replay/` — they're the canonical
Python replay of the Access VBA forms maintained alongside the
cbdb-user-mdb-tests test suite. Re-implementing them here would mean
two implementations of the same Access SQL drifting apart over time.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_query import EntryQueryRequest


def _ensure_cbdb_replay_on_path(access_tests_repo: Path) -> None:
    """Insert `$ACCESS_TESTS_REPO/tests` into sys.path so the
    `cbdb_replay` package becomes importable.

    Lazy / idempotent so callers can invoke this multiple times.
    """
    tests_dir = access_tests_repo / "tests"
    tests_dir_str = str(tests_dir)
    if tests_dir_str not in sys.path:
        sys.path.insert(0, tests_dir_str)


# Avalonia-side EntryQueryRecord field → cbdb_replay/lookatentry SELECT
# column name. Avalonia returns 36 enriched/labelled fields; cbdb_replay
# returns 21 raw fields plus a couple of derived ones. The intersection
# below is what diff_rows can directly compare without further
# normalisation. Fields outside this list are dropped on both sides
# before diffing.
_COMMON_FIELDS_AVALONIA_TO_REPLAY: dict[str, str] = {
    "person_id": "c_personid",
    "name": "c_name",
    "name_chn": "c_name_chn",
    "index_year": "c_index_year",
    "entry_code": "c_entry_code",
    "entry_year": "c_year",
    "sequence": "c_sequence",
    "exam_rank": "c_exam_rank",
    "entry_address_id": "c_entry_addr_id",
}


def entry_query_common_fields() -> tuple[str, ...]:
    """Avalonia-side field names of the row columns that map cleanly to
    cbdb_replay's lookatentry output. Phase 3c uses this as
    `diff_rows(..., compare_fields=...)`."""
    return tuple(_COMMON_FIELDS_AVALONIA_TO_REPLAY.keys())


def _lookup_dynasty_year_range_entry(
    mdb_path: Path,
    dynasty_id: int,
) -> tuple[int, int, int, int] | None:
    """Look up `(from_dynasty, to_dynasty, from_dynasty_begin,
    to_dynasty_end)` for a single Avalonia `dynasty_id` from the
    DYNASTIES table. Returns `None` when the id has no row.

    This is the entry-bridge twin of
    `cbdb_parity.access_status_query._lookup_dynasty_year_range`. The
    two could share an implementation, but they currently live in
    separate modules to keep the access_query / access_status_query
    bridges independent of each other.
    """
    import pyodbc

    conn_str = (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        rf"DBQ={mdb_path};"
    )
    with pyodbc.connect(conn_str) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT c_dy, c_start, c_end FROM DYNASTIES WHERE c_dy = ?",
            int(dynasty_id),
        )
        row = cur.fetchone()
        cur.close()
    if row is None or row[0] is None:
        return None
    dy, start, end = row
    return int(dy), int(dy), int(start or 0), int(end or 0)


def _avalonia_request_to_replay_inputs(
    request: EntryQueryRequest,
    *,
    mdb_path: Path | None = None,
) -> Any | None:
    """Map cbdb_parity.avalonia_query.EntryQueryRequest →
    cbdb_replay.lookatentry.EntryQueryInputs.

    The replay class has a different shape (year_mode strings, separate
    addr_ids/addr_field, dynasty range pair rather than list of ids).
    Single-dynasty selections are translated via DYNASTIES lookup;
    multi-dynasty is rejected (same reason as `access_status_query`:
    cbdb_replay's contiguous `from/to_dynasty` range would silently
    broaden a multi-id set into the dynasties in between).
    """
    from cbdb_replay.lookatentry import EntryQueryInputs

    year_mode: str = "none"
    from_year: int | None = None
    to_year: int | None = None
    from_dynasty: int = -1
    to_dynasty: int = -1
    from_dynasty_begin: int | None = None
    to_dynasty_end: int | None = None

    if request.use_entry_year_range:
        year_mode = "entry"
        from_year = min(request.entry_year_from, request.entry_year_to)
        to_year = max(request.entry_year_from, request.entry_year_to)
    elif request.use_index_year_range:
        year_mode = "index"
        from_year = min(request.index_year_from, request.index_year_to)
        to_year = max(request.index_year_from, request.index_year_to)
    elif request.dynasty_ids:
        # See access_status_query for the multi-dynasty rationale:
        # cbdb_replay's dynasty mode is a contiguous range, not an
        # exact set; collapsing a non-singleton selection would
        # silently include intermediate dynasties.
        if len(request.dynasty_ids) > 1:
            raise NotImplementedError(
                f"dynasty_ids={tuple(request.dynasty_ids)!r}: "
                f"cbdb_replay/lookatentry only models a contiguous "
                f"from/to dynasty range, not an exact set. Multi-"
                f"dynasty selections with gaps would silently broaden "
                f"the Access-side filter to include intermediate "
                f"dynasties. Restrict the parity input to a single "
                f"dynasty until the bridge supports per-id replay."
            )
        if mdb_path is None:
            raise RuntimeError(
                "dynasty_ids translation requires `mdb_path` so "
                "DYNASTIES can be queried for the begin/end year range."
            )
        looked = _lookup_dynasty_year_range_entry(
            mdb_path, int(request.dynasty_ids[0])
        )
        if looked is None:
            # DYNASTIES has no row for this id. Avalonia still applies
            # `b.c_dy IN (id)` and gets zero rows because no BIOG_MAIN
            # row has that c_dy either. The cbdb_replay path, with no
            # year_mode set, would run UNFILTERED — silently broadening
            # the Access ground truth, exactly the regression codex
            # round-3 flagged. Return None so the caller short-circuits
            # to an empty Access-side result, matching Avalonia.
            return None
        from_dynasty, to_dynasty, from_dynasty_begin, to_dynasty_end = looked
        year_mode = "dynasty"

    entry_codes = list(request.entry_codes) if request.entry_codes else None
    # cbdb_replay expects int entry codes; the Avalonia request uses str.
    entry_codes_int: list[int] | None
    if entry_codes is not None:
        try:
            entry_codes_int = [int(c) for c in entry_codes]
        except ValueError as exc:
            raise ValueError(
                f"non-integer entry_code in Avalonia request: {entry_codes!r}"
            ) from exc
    else:
        entry_codes_int = None

    addr_ids = list(request.place_ids) if request.place_ids else None

    # AddrField passthrough: Avalonia's "entry" maps directly to
    # cbdb_replay's "entry"; Avalonia's "person" maps to cbdb_replay's
    # "person". The upstream EntryQueryRequest enforces the same
    # vocabulary (any other value falls back to "entry").
    addr_field_replay: str = "person" if request.addr_field == "person" else "entry"

    return EntryQueryInputs(
        entry_codes=entry_codes_int,
        addr_ids=addr_ids,
        addr_field=addr_field_replay,  # type: ignore[arg-type]
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
    """Project a cbdb_replay/lookatentry row dict onto the Avalonia
    field names, restricted to the common-fields cross-section.

    Critically: `cbdb_replay` returns rows that came from pandas
    `DataFrame.to_dict("records")`, which materialises SQL NULL as
    `float('nan')` (NaN), NOT Python `None`. Avalonia's sqlite3
    output uses real `None`. Without this coercion every NULL-bearing
    column produces a spurious value_mismatch in `diff_rows()` (200
    rows x NULL `entry_address_id` -> 198 false mismatches on
    entry_basic, observed 2026-05-28). We coerce NaN → None here so
    both sides compare on the same SQL-NULL sentinel.
    """
    import math

    out: dict[str, Any] = {}
    for av_field, replay_col in _COMMON_FIELDS_AVALONIA_TO_REPLAY.items():
        value = replay_row.get(replay_col)
        # pandas NaN → SQL NULL → Avalonia None. `isinstance(v, float)
        # and math.isnan(v)` is the canonical NaN check (Python's `v is
        # nan` doesn't work because NaN != NaN). Apply BEFORE the
        # entry_code str() coercion so we don't accidentally stringify
        # `nan`.
        if isinstance(value, float) and math.isnan(value):
            value = None
        # entry_code arrives as int from Access (POSTED_TO_OFFICE_DATA has int
        # codes); Avalonia returns it as text (CAST in the SELECT). Normalise.
        if av_field == "entry_code" and value is not None:
            value = str(value)
        out[av_field] = value
    return out


def entry_query_access(
    mdb_path: Path,
    request: EntryQueryRequest,
    *,
    access_tests_repo: Path,
) -> list[dict[str, Any]]:
    """Run the Access-side equivalent of EntryQueryRequest against
    `mdb_path` (which MUST be a Phase 1.3b-generated cbdb_data.mdb).

    Returns rows in the common-fields cross-section, keyed by Avalonia
    field names, so they can be diffed directly against
    `cbdb_parity.avalonia_query.entry_query(...)` output.

    Ordering / limit: mirrors what the Avalonia SQL appends:
        ORDER BY entry_label, ed.c_year, b.c_personid, ed.c_sequence
        LIMIT :limit
    cbdb_replay doesn't join ENTRY_CODES (so `entry_label` isn't on
    each row), but for a SINGLE entry_code filter the label is
    constant and `(year, person_id, sequence)` is a strict prefix of
    the Avalonia order. For multi-code requests, the Access side
    sorts by `(entry_code, year, person_id, sequence)` so that two
    rows with different codes are at least in a stable canonical
    order even though the precise position relative to Avalonia's
    Chinese-collation `entry_label` may differ at code boundaries.

    `access_tests_repo` is `cfg.access_tests_repo` from .env; resolved
    at the call site.
    """
    _ensure_cbdb_replay_on_path(access_tests_repo)
    # Lazy import — pyodbc + the cbdb_replay package only need to load
    # when the Access side actually runs.
    import pyodbc
    from cbdb_replay.lookatentry import run as replay_run

    inputs = _avalonia_request_to_replay_inputs(request, mdb_path=mdb_path)
    # Translator returned None: empty Access-side result by design
    # (e.g. dynasty_ids references a row not in DYNASTIES, where
    # Avalonia would also return zero rows via b.c_dy IN (...)).
    if inputs is None:
        return []
    conn_str = (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        rf"DBQ={mdb_path};"
    )
    with pyodbc.connect(conn_str) as conn:
        df = replay_run(conn, inputs)
        # Load the ENTRY_CODES label map so we can mirror Avalonia's
        # `ORDER BY entry_label, year, personid, sequence LIMIT N`
        # exactly. ENTRY_CODES is small (~700 rows); fetching the whole
        # table once is cheaper than a per-row JOIN.
        cursor = conn.cursor()
        cursor.execute("SELECT c_entry_code, c_entry_desc, c_entry_desc_chn FROM ENTRY_CODES")
        entry_labels: dict[int, str | None] = {}
        for code, desc, desc_chn in cursor.fetchall():
            # Avalonia uses COALESCE(c_entry_desc_chn, c_entry_desc) —
            # which falls back ONLY for NULL, not for empty string.
            # Mirroring `desc_chn is not None` (NOT `if desc_chn`).
            entry_labels[int(code)] = desc_chn if desc_chn is not None else desc
        cursor.close()

    records = df.to_dict("records")

    # Avalonia clamps limit to [1, 100000] (bumped from 10000 in
    # cbdb-desktop-app commit c94157d); mirror that contract.
    effective_limit = max(1, min(request.limit, 100000))

    def _sort_key(r: dict[str, Any]) -> tuple[Any, ...]:
        code = r.get("c_entry_code")
        label = entry_labels.get(int(code), "") if code is not None else ""
        # Pad with sentinels for None so the sort is stable + total.
        # Note: Python's default string ordering is codepoint-based —
        # SQLite's ORDER BY on a TEXT column is also codepoint-based by
        # default (no COLLATE specified in the Avalonia SQL), so the
        # primary `entry_label` key sorts identically on both sides.
        return (
            label if label is not None else "",
            r.get("c_year") if r.get("c_year") is not None else -10**9,
            r.get("c_personid") if r.get("c_personid") is not None else -1,
            r.get("c_sequence") if r.get("c_sequence") is not None else -1,
        )

    records.sort(key=_sort_key)
    records = records[:effective_limit]

    return [_replay_row_to_avalonia_shape(r) for r in records]


__all__ = [
    "entry_query_access",
    "entry_query_common_fields",
]


def _quiet_unused(*_args: Sequence[Any]) -> None:
    """Belt for linters about Sequence import."""


_quiet_unused(_COMMON_FIELDS_AVALONIA_TO_REPLAY)
