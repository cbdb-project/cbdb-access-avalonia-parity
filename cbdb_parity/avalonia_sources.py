"""Phase 5c-final — thin wrapper around GetSourcesAsync via the
ParityHost. `text_id` spliced from BIOG_SOURCE_DATA for Phase 4 diff
keying. Splice ORDER BY mirrors
SqlitePersonBrowserService.GetSourcesAsync line 1964.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity._person_accessor_host import (
    fetch_via_host_with_id_splice,
    resolve_avalonia_repo,
)

_SOURCE_RECORD_FIELDS: tuple[str, ...] = (
    "title_chn", "title", "pages", "notes",
    "main_source", "self_bio", "hyperlink",
)
_SOURCE_ID_FIELDS: tuple[str, ...] = ("text_id",)

_SPLICE_SQL = (
    "SELECT bsd.c_textid FROM BIOG_SOURCE_DATA bsd "
    "WHERE bsd.c_personid = :pid "
    "ORDER BY bsd.c_textid, bsd.c_pages"
)


def sources_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path | None = None,
    avalonia_repo: Path | None = None,
) -> list[dict[str, Any]]:
    return fetch_via_host_with_id_splice(
        "sources", sqlite_path, person_id,
        avalonia_repo=resolve_avalonia_repo(
            avalonia_repo=avalonia_repo,
            avalonia_data_dir=avalonia_data_dir,
        ),
        splice_sql=_SPLICE_SQL,
        splice_field_names=_SOURCE_ID_FIELDS,
    )


def sources_field_names() -> tuple[str, ...]:
    return _SOURCE_RECORD_FIELDS


def sources_id_field_names() -> tuple[str, ...]:
    return _SOURCE_ID_FIELDS


__all__ = ["sources_field_names", "sources_id_field_names", "sources_query"]
