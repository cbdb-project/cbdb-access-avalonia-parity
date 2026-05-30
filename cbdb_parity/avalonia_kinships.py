"""Phase 5c-final batch 2 — thin wrapper around GetKinshipsAsync
(expandNetwork=false direct branch) via the ParityHost.

`kin_code` spliced from KIN_DATA for Phase 4 diff keying. Splice
ORDER BY mirrors SqlitePersonBrowserService.GetKinshipsAsync line
1304: `ORDER BY kd.c_kin_id, kd.c_kin_code`.

The dispatch service is `kinships` (same as 5d's expandNetwork=true
case); we send `expand_network: false` so the host runs the direct
branch.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from cbdb_parity._person_accessor_host import resolve_avalonia_repo
from cbdb_parity.parity_host import invoke_parity_host

_KINSHIP_RECORD_FIELDS: tuple[str, ...] = (
    "kin_person_id", "kinship", "kin_name_chn", "kin_name",
    # `is_derived` is on the upstream PersonKinshipItem record but
    # is always False for the direct branch (no derivation in
    # expandNetwork=false). Access has no analogue, so it stays
    # out of the Phase 4 compare tuple.
    "up_step", "down_step", "marriage_step", "collateral_step",
    "source", "pages", "notes",
)
_KINSHIP_ID_FIELDS: tuple[str, ...] = ("kin_code",)


_SPLICE_SQL = (
    "SELECT kd.c_kin_code FROM KIN_DATA kd "
    "WHERE kd.c_personid = :pid "
    "ORDER BY kd.c_kin_id, kd.c_kin_code"
)


def kinships_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path | None = None,
    avalonia_repo: Path | None = None,
) -> list[dict[str, Any]]:
    repo = resolve_avalonia_repo(
        avalonia_repo=avalonia_repo,
        avalonia_data_dir=avalonia_data_dir,
    )
    rows = invoke_parity_host(
        "kinships", sqlite_path,
        {"person_id": person_id, "expand_network": False},
        avalonia_repo=repo,
    )
    if not isinstance(rows, list):
        raise TypeError(
            f"kinships dispatch returned {type(rows).__name__}; expected list."
        )
    with sqlite3.connect(sqlite_path) as conn:
        codes = [r[0] for r in conn.execute(
            _SPLICE_SQL, {"pid": person_id},
        ).fetchall()]
    if len(codes) != len(rows):
        raise RuntimeError(
            f"kinships ID splice row-count mismatch — "
            f"host={len(rows)} sqlite={len(codes)}."
        )
    for row, code in zip(rows, codes, strict=True):
        row["kin_code"] = code
    return rows


def kinships_field_names() -> tuple[str, ...]:
    return _KINSHIP_RECORD_FIELDS


def kinships_id_field_names() -> tuple[str, ...]:
    return _KINSHIP_ID_FIELDS


__all__ = [
    "kinships_field_names",
    "kinships_id_field_names",
    "kinships_query",
]
