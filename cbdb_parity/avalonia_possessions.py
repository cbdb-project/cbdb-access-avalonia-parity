"""Phase 5c-final — thin wrapper around GetPossessionsAsync via the
ParityHost. No spliced ID columns: upstream PersonPossessionItem
exposes `RecordId` on the wire.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity._person_accessor_host import (
    fetch_via_host_with_id_splice,
    resolve_avalonia_repo,
)

_POSSESSION_RECORD_FIELDS: tuple[str, ...] = (
    "record_id", "sequence", "possession", "possession_action",
    "quantity", "measure", "year", "nianhao", "nianhao_year",
    "range", "address_name_chn", "address_name",
    "source", "pages", "notes",
)
_POSSESSION_ID_FIELDS: tuple[str, ...] = ()


def possessions_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path | None = None,
    avalonia_repo: Path | None = None,
) -> list[dict[str, Any]]:
    return fetch_via_host_with_id_splice(
        "possessions", sqlite_path, person_id,
        avalonia_repo=resolve_avalonia_repo(
            avalonia_repo=avalonia_repo,
            avalonia_data_dir=avalonia_data_dir,
        ),
    )


def possessions_field_names() -> tuple[str, ...]:
    return _POSSESSION_RECORD_FIELDS


def possessions_id_field_names() -> tuple[str, ...]:
    return _POSSESSION_ID_FIELDS


__all__ = [
    "possessions_field_names",
    "possessions_id_field_names",
    "possessions_query",
]
