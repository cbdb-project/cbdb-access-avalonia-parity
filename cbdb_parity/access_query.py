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


def _avalonia_request_to_replay_inputs(request: EntryQueryRequest) -> Any:
    """Map cbdb_parity.avalonia_query.EntryQueryRequest →
    cbdb_replay.lookatentry.EntryQueryInputs.

    The replay class has a different shape (year_mode strings, separate
    addr_ids/addr_field, dynasty range pair rather than list of ids).
    The conservative mapping below picks ALL/none/full-range for the
    fields Avalonia doesn't expose; Phase 3c smoke uses requests that
    only exercise the common cross-section.
    """
    from cbdb_replay.lookatentry import EntryQueryInputs

    year_mode: str = "none"
    from_year: int | None = None
    to_year: int | None = None
    if request.use_entry_year_range:
        year_mode = "entry"
        from_year = min(request.entry_year_from, request.entry_year_to)
        to_year = max(request.entry_year_from, request.entry_year_to)
    elif request.use_index_year_range:
        year_mode = "index"
        from_year = min(request.index_year_from, request.index_year_to)
        to_year = max(request.index_year_from, request.index_year_to)
    elif request.dynasty_ids:
        # cbdb_replay's dynasty mode uses a single from/to pair, not a
        # list. For the initial parity smoke we pin to "none" and let
        # caller use entry_codes / address filters instead.
        year_mode = "none"

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

    return EntryQueryInputs(
        entry_codes=entry_codes_int,
        addr_ids=addr_ids,
        addr_field="entry",
        include_subunits=request.include_subordinate_units,
        use_xy_radius=False,
        year_mode=year_mode,  # type: ignore[arg-type]
        from_year=from_year,
        to_year=to_year,
    )


def _replay_row_to_avalonia_shape(replay_row: dict[str, Any]) -> dict[str, Any]:
    """Project a cbdb_replay/lookatentry row dict onto the Avalonia
    field names, restricted to the common-fields cross-section."""
    out: dict[str, Any] = {}
    for av_field, replay_col in _COMMON_FIELDS_AVALONIA_TO_REPLAY.items():
        value = replay_row.get(replay_col)
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

    `access_tests_repo` is `cfg.access_tests_repo` from .env; resolved
    at the call site.
    """
    _ensure_cbdb_replay_on_path(access_tests_repo)
    # Lazy import — pyodbc + the cbdb_replay package only need to load
    # when the Access side actually runs.
    import pyodbc
    from cbdb_replay.lookatentry import run as replay_run

    inputs = _avalonia_request_to_replay_inputs(request)
    conn_str = (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        rf"DBQ={mdb_path};"
    )
    rows: list[dict[str, Any]] = []
    with pyodbc.connect(conn_str) as conn:
        df = replay_run(conn, inputs)
        # df is a pandas DataFrame with cbdb_replay's column shape.
        for record in df.to_dict("records"):
            rows.append(_replay_row_to_avalonia_shape(record))
    return rows


__all__ = [
    "entry_query_access",
    "entry_query_common_fields",
]


def _quiet_unused(*_args: Sequence[Any]) -> None:
    """Belt for linters about Sequence import."""


_quiet_unused(_COMMON_FIELDS_AVALONIA_TO_REPLAY)
