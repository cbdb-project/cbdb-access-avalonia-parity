"""Phase 5c-final — thin wrapper around GetAddressesAsync via the
ParityHost. `addr_type_code` and `addr_id` spliced from
BIOG_ADDR_DATA for Phase 4 diff keying. Splice ORDER BY mirrors
SqlitePersonBrowserService.GetAddressesAsync line 482.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity._person_accessor_host import (
    fetch_via_host_with_id_splice,
    resolve_avalonia_repo,
)


_ADDRESS_RECORD_FIELDS: tuple[str, ...] = (
    "sequence", "natal", "address_type", "address_name_chn", "address_name",
    "first_year", "first_nianhao", "first_nianhao_year", "first_month",
    "first_intercalary", "first_day", "first_ganzhi", "first_range",
    "last_year", "last_nianhao", "last_nianhao_year", "last_month",
    "last_intercalary", "last_day", "last_ganzhi", "last_range",
    "source", "pages", "notes",
)
_ADDRESS_ID_FIELDS: tuple[str, ...] = ("addr_type_code", "addr_id")

_SPLICE_SQL = (
    "SELECT bad.c_addr_type, bad.c_addr_id FROM BIOG_ADDR_DATA bad "
    "WHERE bad.c_personid = :pid "
    "ORDER BY bad.c_sequence, bad.c_addr_type, bad.c_addr_id"
)


def addresses_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path | None = None,
    avalonia_repo: Path | None = None,
) -> list[dict[str, Any]]:
    return fetch_via_host_with_id_splice(
        "addresses", sqlite_path, person_id,
        avalonia_repo=resolve_avalonia_repo(
            avalonia_repo=avalonia_repo,
            avalonia_data_dir=avalonia_data_dir,
        ),
        splice_sql=_SPLICE_SQL,
        splice_field_names=_ADDRESS_ID_FIELDS,
    )


def addresses_field_names() -> tuple[str, ...]:
    return _ADDRESS_RECORD_FIELDS


def addresses_id_field_names() -> tuple[str, ...]:
    return _ADDRESS_ID_FIELDS


__all__ = [
    "addresses_field_names",
    "addresses_id_field_names",
    "addresses_query",
]
