"""Phase 5c-final — thin wrapper around GetStatusesAsync via the
ParityHost. `status_code` spliced from STATUS_DATA for Phase 4 diff
keying. Splice ORDER BY mirrors
SqlitePersonBrowserService.GetStatusesAsync line 1085.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity._person_accessor_host import (
    fetch_via_host_with_id_splice,
    resolve_avalonia_repo,
)


_STATUS_RECORD_FIELDS: tuple[str, ...] = (
    "sequence", "status",
    "first_year", "first_nianhao", "first_nianhao_year", "first_range",
    "last_year", "last_nianhao", "last_nianhao_year", "last_range",
    "source", "pages", "notes",
)
_STATUS_ID_FIELDS: tuple[str, ...] = ("status_code",)

_SPLICE_SQL = (
    "SELECT sd.c_status_code FROM STATUS_DATA sd "
    "WHERE sd.c_personid = :pid "
    "ORDER BY sd.c_sequence, sd.c_status_code"
)


def statuses_person_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path | None = None,
    avalonia_repo: Path | None = None,
) -> list[dict[str, Any]]:
    return fetch_via_host_with_id_splice(
        "statuses", sqlite_path, person_id,
        avalonia_repo=resolve_avalonia_repo(
            avalonia_repo=avalonia_repo,
            avalonia_data_dir=avalonia_data_dir,
        ),
        splice_sql=_SPLICE_SQL,
        splice_field_names=_STATUS_ID_FIELDS,
    )


def statuses_person_field_names() -> tuple[str, ...]:
    return _STATUS_RECORD_FIELDS


def statuses_person_id_field_names() -> tuple[str, ...]:
    return _STATUS_ID_FIELDS


__all__ = [
    "statuses_person_field_names",
    "statuses_person_id_field_names",
    "statuses_person_query",
]
