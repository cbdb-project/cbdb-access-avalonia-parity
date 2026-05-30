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

# Upstream ORDER BY (`sd:577`) is `c_sequence, c_alt_name_type_code,
# c_alt_name_chn`. Ties on all three are possible in CBDB. To prevent
# positional misalignment, the splice SELECT prefixes the verify
# columns (`c_sequence`, `c_alt_name_chn`) — which the host already
# exposes as `sequence` / `alt_name_chn` — and the helper asserts
# those values match the host row before attaching the ID columns.
# COALESCE on c_sequence mirrors the upstream C# reader's
# `IsDBNull(0) ? 0 : GetInt32(0)` null-collapse so verify can compare
# with the host's already-coalesced `sequence` field.
_SPLICE_SQL = (
    "SELECT COALESCE(a.c_sequence, 0), a.c_alt_name_chn, "
    "       a.c_alt_name_type_code, a.c_source "
    "FROM ALTNAME_DATA a "
    "WHERE a.c_personid = :pid "
    "ORDER BY a.c_sequence, a.c_alt_name_type_code, a.c_alt_name_chn"
)
_ALTNAME_SPLICE_VERIFY: tuple[tuple[str, str], ...] = (
    ("sequence", "c_sequence"),
    ("alt_name_chn", "c_alt_name_chn"),
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
        splice_verify=_ALTNAME_SPLICE_VERIFY,
    )


def altnames_field_names() -> tuple[str, ...]:
    return _ALTNAME_RECORD_FIELDS


def altnames_id_field_names() -> tuple[str, ...]:
    return _ALTNAME_ID_FIELDS


__all__ = [
    "altnames_field_names",
    "altnames_id_field_names",
    "altnames_query",
]
