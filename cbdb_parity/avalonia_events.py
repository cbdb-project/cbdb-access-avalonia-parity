"""Phase 5c-final — thin wrapper around the real Avalonia
GetEventsAsync via the ParityHost.

`event_code` is spliced from EVENTS_DATA because upstream
PersonEventItem doesn't expose it but Phase 4 pair tests key on
it. The splice ORDER BY mirrors
SqlitePersonBrowserService.GetEventsAsync line 1232.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity._person_accessor_host import (
    fetch_via_host_with_id_splice,
    resolve_avalonia_repo,
)

_EVENT_RECORD_FIELDS: tuple[str, ...] = (
    "sequence", "event_name", "role", "year", "nianhao",
    "nianhao_year", "month", "intercalary", "day", "ganzhi",
    "range", "address_name_chn", "address_name", "source",
    "pages", "event_text", "notes",
)
_EVENT_ID_FIELDS: tuple[str, ...] = ("event_code",)

_SPLICE_SQL = (
    "SELECT ed.c_event_code FROM EVENTS_DATA ed "
    "WHERE ed.c_personid = :pid "
    "ORDER BY ed.c_year, ed.c_sequence, ed.c_event_code"
)


def events_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path | None = None,
    avalonia_repo: Path | None = None,
) -> list[dict[str, Any]]:
    return fetch_via_host_with_id_splice(
        "events", sqlite_path, person_id,
        avalonia_repo=resolve_avalonia_repo(
            avalonia_repo=avalonia_repo,
            avalonia_data_dir=avalonia_data_dir,
        ),
        splice_sql=_SPLICE_SQL,
        splice_field_names=_EVENT_ID_FIELDS,
    )


def events_field_names() -> tuple[str, ...]:
    return _EVENT_RECORD_FIELDS


def events_id_field_names() -> tuple[str, ...]:
    return _EVENT_ID_FIELDS


__all__ = ["events_field_names", "events_id_field_names", "events_query"]
