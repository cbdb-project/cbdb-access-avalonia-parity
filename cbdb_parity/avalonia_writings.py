"""Phase 5c-final — thin wrapper around GetWritingsAsync via the
ParityHost. `role_id` spliced from BIOG_TEXT_DATA for Phase 4 diff
keying. Splice ORDER BY mirrors
SqlitePersonBrowserService.GetWritingsAsync line 642.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity._person_accessor_host import (
    fetch_via_host_with_id_splice,
    resolve_avalonia_repo,
)

_WRITING_RECORD_FIELDS: tuple[str, ...] = (
    "text_id", "title_chn", "title", "role", "year",
    "nianhao", "nianhao_year", "range", "source", "pages", "notes",
)
_WRITING_ID_FIELDS: tuple[str, ...] = ("role_id",)

_SPLICE_SQL = (
    "SELECT btd.c_role_id FROM BIOG_TEXT_DATA btd "
    "WHERE btd.c_personid = :pid "
    "ORDER BY btd.c_year, btd.c_textid, btd.c_role_id"
)


def writings_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path | None = None,
    avalonia_repo: Path | None = None,
) -> list[dict[str, Any]]:
    return fetch_via_host_with_id_splice(
        "writings", sqlite_path, person_id,
        avalonia_repo=resolve_avalonia_repo(
            avalonia_repo=avalonia_repo,
            avalonia_data_dir=avalonia_data_dir,
        ),
        splice_sql=_SPLICE_SQL,
        splice_field_names=_WRITING_ID_FIELDS,
    )


def writings_field_names() -> tuple[str, ...]:
    return _WRITING_RECORD_FIELDS


def writings_id_field_names() -> tuple[str, ...]:
    return _WRITING_ID_FIELDS


__all__ = ["writings_field_names", "writings_id_field_names", "writings_query"]
