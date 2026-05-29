"""Phase 5c-final — thin wrapper around GetAltNamesAsync via the
ParityHost. `name_type_code` and `source_id` spliced from
ALTNAME_DATA for Phase 4 diff keying. Splice ORDER BY mirrors
SqlitePersonBrowserService.GetAltNamesAsync line 577.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity._person_accessor_host import (
    fetch_via_host_with_id_splice,
    resolve_avalonia_repo,
)


_ALTNAME_RECORD_FIELDS: tuple[str, ...] = (
    "sequence", "alt_name_chn", "alt_name", "name_type",
    "source", "pages", "notes",
)
_ALTNAME_ID_FIELDS: tuple[str, ...] = ("name_type_code", "source_id")

_SPLICE_SQL = (
    "SELECT a.c_alt_name_type_code, a.c_source FROM ALTNAME_DATA a "
    "WHERE a.c_personid = :pid "
    "ORDER BY a.c_sequence, a.c_alt_name_type_code, a.c_alt_name_chn"
)


def altnames_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path | None = None,
    avalonia_repo: Path | None = None,
) -> list[dict[str, Any]]:
    return fetch_via_host_with_id_splice(
        "altnames", sqlite_path, person_id,
        avalonia_repo=resolve_avalonia_repo(
            avalonia_repo=avalonia_repo,
            avalonia_data_dir=avalonia_data_dir,
        ),
        splice_sql=_SPLICE_SQL,
        splice_field_names=_ALTNAME_ID_FIELDS,
    )


def altnames_field_names() -> tuple[str, ...]:
    return _ALTNAME_RECORD_FIELDS


def altnames_id_field_names() -> tuple[str, ...]:
    return _ALTNAME_ID_FIELDS


def _join_display(
    primary: str | None,
    secondary: str | None,
    secondary_pattern: str = " / {0}",
) -> str | None:
    """Exact port of
    `Cbdb.App.Data.SqlitePersonBrowserService.JoinDisplay`.
    Used by the Phase 4 Access-side bridges to match what the C#
    host emits for `source`/`event_name`/etc. fields.

    Logic mirrors upstream verbatim:
      - blank primary → return secondary as-is
      - blank secondary OR case-insensitive equal → return primary
      - otherwise → primary + secondary_pattern.format(secondary)
    """
    def _blank(s: str | None) -> bool:
        return s is None or not s.strip()

    if _blank(primary):
        return secondary
    if _blank(secondary) or primary.casefold() == (secondary or "").casefold():
        return primary
    return primary + secondary_pattern.format(secondary)


__all__ = [
    "_join_display",
    "altnames_field_names",
    "altnames_id_field_names",
    "altnames_query",
]
