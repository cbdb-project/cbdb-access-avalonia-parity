"""Access-side bridge for the Phase 4 kinships pair test.

Phase 6a — rewritten to call `cbdb_replay.lookatkinship.run` directly,
in line with WORK_PLAN §0.b ("no transcription"). The previous
hand-written `_ACCESS_SQL` block that recreated Avalonia's joins is
gone; we now drive the same VBA-historical replay script that
`cbdb-user-mdb-tests` validates against the Access UI.

Template: `cbdb_parity/access_office_query.py` (Phase 3d).

Scope: cbdb_replay's `LookAtKinship` is the DIRECT-relationship
subset only (1-hop). Multi-hop traversal would raise
`NotImplementedError` upstream, so this bridge never asks for it —
the matching Avalonia call is also `expandNetwork=false`.

Known row-set contract gap (see
`reports/known_issues.md#kinships_basic_person`):
cbdb_replay's INNER JOIN on `BIOG_MAIN_1` drops orphan kin (KIN_DATA
rows whose `c_kin_id` has no BIOG_MAIN match). Avalonia uses LEFT
JOIN and surfaces them with NULL kin names. We do NOT paper over
this with a transcribed LEFT JOIN inside the bridge — that would
violate §0.b. The current canonical fixture (Su Shi / 1762) has no
orphan kin so the pair test passes; a dump with orphan kin would
fail row-count.

Cross-section: the comparable columns are limited to what BOTH
backends emit RAW (no transcription of upstream formatting). That
excludes the `kinship` joined label (Avalonia's
`JoinDisplay(c_kinrel_chn, c_kinrel)`), as well as `source` /
`pages` / `notes` which cbdb_replay doesn't fetch. The Avalonia
side still emits those fields; we just don't compare them here.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def _ensure_cbdb_replay_on_path(access_tests_repo: Path) -> None:
    """Mirror of `cbdb_parity.access_query._ensure_cbdb_replay_on_path`."""
    tests_dir = access_tests_repo / "tests"
    tests_dir_str = str(tests_dir)
    if tests_dir_str not in sys.path:
        sys.path.insert(0, tests_dir_str)


# Avalonia PersonKinshipItem snake_case field → cbdb_replay/lookatkinship
# SELECT column. Limited to the columns BOTH sides emit raw — no
# JoinDisplay, no TEXT_CODES title lookup. The Avalonia side still
# emits source/pages/notes/kinship; they just don't participate in
# this cross-section.
#
# `kin_code` is here because Avalonia's mirror splices it back onto
# each row (see `cbdb_parity.avalonia_kinships._SPLICE_SQL`); it is a
# stable diff key.
_COMMON_FIELDS_AVALONIA_TO_REPLAY: dict[str, str] = {
    "kin_person_id":   "c_kin_id",
    "kin_name_chn":    "c_kin_chn",
    "kin_name":        "c_kin_name",
    "up_step":         "c_upstep",
    "down_step":       "c_dwnstep",
    "marriage_step":   "c_marstep",
    "collateral_step": "c_colstep",
    "kin_code":        "c_kin_code",
}


def kinships_common_fields() -> tuple[str, ...]:
    """Avalonia field names of the columns this bridge can compare."""
    return tuple(_COMMON_FIELDS_AVALONIA_TO_REPLAY.keys())


def _replay_row_to_avalonia_shape(replay_row: dict[str, Any]) -> dict[str, Any]:
    """Project a cbdb_replay/lookatkinship row dict onto Avalonia field
    names. Pure pass-through except for pandas-NaN → Python-None
    normalisation (the office bridge needs the same coercion — pandas
    `to_dict('records')` surfaces SQL NULL as float NaN, which would
    diverge from the sqlite3 None that Avalonia rows carry).
    """
    import math

    out: dict[str, Any] = {}
    for av_field, replay_col in _COMMON_FIELDS_AVALONIA_TO_REPLAY.items():
        value = replay_row.get(replay_col)
        if isinstance(value, float) and math.isnan(value):
            value = None
        # kin_person_id is `int NOT NULL` in upstream PersonKinshipItem
        # (Avalonia's reader coerces NULL → 0). cbdb_replay's INNER JOIN
        # on BIOG_MAIN_1 means a NULL kin_id can't reach this code path,
        # so a pass-through int is correct; no `or 0` fallback needed.
        out[av_field] = value
    return out


def kinships_query_access(
    mdb_path: Path,
    person_id: int,
    *,
    access_tests_repo: Path,
) -> list[dict[str, Any]]:
    """Run `cbdb_replay.lookatkinship.run` and project to Avalonia shape."""
    _ensure_cbdb_replay_on_path(access_tests_repo)
    import pyodbc
    from cbdb_replay.lookatkinship import KinshipQueryInputs, run as replay_run

    conn_str = (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        rf"DBQ={mdb_path};"
    )
    inputs = KinshipQueryInputs(person_id=person_id)
    # pyodbc context exit commits but does not close — explicit close
    # to avoid leaking ODBC handles (codex round-13 P2 on office_query).
    conn = pyodbc.connect(conn_str)
    try:
        df = replay_run(conn, inputs)
    finally:
        conn.close()

    rows = df.to_dict("records") if not df.empty else []
    return [_replay_row_to_avalonia_shape(r) for r in rows]


__all__ = [
    "kinships_common_fields",
    "kinships_query_access",
]
