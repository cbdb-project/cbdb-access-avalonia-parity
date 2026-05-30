"""Phase 5c-final — thin wrapper around GetEntriesAsync via the
ParityHost. `entry_code` spliced from ENTRY_DATA for Phase 4 diff
keying. Splice ORDER BY mirrors
SqlitePersonBrowserService.GetEntriesAsync line 1004.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity._person_accessor_host import (
    fetch_via_host_with_id_splice,
    resolve_avalonia_repo,
)

_ENTRY_RECORD_FIELDS: tuple[str, ...] = (
    "sequence", "entry_method", "exam_rank", "year", "nianhao", "nianhao_year",
    "dynasty", "range", "age", "kinship", "kin_name_chn", "kin_name",
    "association", "associate_name_chn", "associate_name",
    "institution_name_chn", "institution_name",
    "entry_address_chn", "entry_address", "parental_status",
    "source", "pages", "notes", "posting_notes",
)
_ENTRY_ID_FIELDS: tuple[str, ...] = ("entry_code",)

_SPLICE_SQL = (
    "SELECT ed.c_entry_code FROM ENTRY_DATA ed "
    "WHERE ed.c_personid = :pid "
    "ORDER BY ed.c_year, ed.c_sequence, ed.c_entry_code"
)


def entries_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path | None = None,
    avalonia_repo: Path | None = None,
) -> list[dict[str, Any]]:
    return fetch_via_host_with_id_splice(
        "entries", sqlite_path, person_id,
        avalonia_repo=resolve_avalonia_repo(
            avalonia_repo=avalonia_repo,
            avalonia_data_dir=avalonia_data_dir,
        ),
        splice_sql=_SPLICE_SQL,
        splice_field_names=_ENTRY_ID_FIELDS,
    )


def entries_field_names() -> tuple[str, ...]:
    return _ENTRY_RECORD_FIELDS


def entries_id_field_names() -> tuple[str, ...]:
    return _ENTRY_ID_FIELDS


__all__ = ["entries_field_names", "entries_id_field_names", "entries_query"]
