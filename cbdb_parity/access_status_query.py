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


def _avalonia_request_to_replay_inputs(request: StatusQueryRequest) -> Any:
    """Map StatusQueryRequest → cbdb_replay.lookatstatus.StatusQueryInputs.

    cbdb_replay/lookatstatus models a narrower request space than the
    Avalonia side. Branches we cannot faithfully replay are rejected
    upfront — silently dropping them would let the Access side return
    a broader result set and produce false parity mismatches.
    """
    unsupported: list[str] = []
    if request.person_keyword and request.person_keyword.strip():
        unsupported.append("person_keyword")
    if request.dynasty_ids:
        unsupported.append("dynasty_ids")
    if not request.status_codes:
        unsupported.append(
            "status_codes (empty — cbdb_replay returns no rows; Avalonia "
            "runs unfiltered)"
        )
    if unsupported:
        raise NotImplementedError(
            "cbdb_replay/lookatstatus does not model these StatusQueryRequest "
            f"branches: {sorted(unsupported)!r}. Drop them from the parity "
            "request or extend the bridge before treating its output as the "
            "Access ground truth."
        )

    from cbdb_replay.lookatstatus import StatusQueryInputs

    # `StatusQueryInputs` exposes year filtering as three flat fields
    # (`year_mode` / `from_year` / `to_year`), NOT a `YearFilter` object
    # like `lookatoffice.OfficeQueryInputs` does. The two replay
    # interfaces diverge here; we map directly to whichever shape each
    # one ships.
    if request.use_index_year_range:
        year_mode: str = "index"
        from_year: int | None = min(request.index_year_from, request.index_year_to)
        to_year: int | None = max(request.index_year_from, request.index_year_to)
    else:
        year_mode = "none"
        from_year = None
        to_year = None

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

    Ordering / limit: mirrors Avalonia's
        ORDER BY status_label, b.c_personid, sd.c_sequence  LIMIT N
    via a post-fetch STATUS_CODES label lookup. For a SINGLE-code
    request `status_label` is constant and `(person_id, sequence)` is
    a stable proper prefix; multi-code requests sort by
    `(status_label, person_id, sequence)` after looking each row's
    label up.
    """
    _ensure_cbdb_replay_on_path(access_tests_repo)
    import pyodbc
    from cbdb_replay.lookatstatus import run as replay_run

    inputs = _avalonia_request_to_replay_inputs(request)
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

    effective_limit = max(1, min(request.limit, 10000))

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
