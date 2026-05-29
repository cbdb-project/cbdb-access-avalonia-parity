"""Phase 5c-final — thin wrapper around GetInstitutionsAsync via the
ParityHost. `inst_name_code` and `inst_code` spliced from
BIOG_INST_DATA for Phase 4 diff keying. Splice ORDER BY mirrors
SqlitePersonBrowserService.GetInstitutionsAsync line 2041.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity._person_accessor_host import (
    fetch_via_host_with_id_splice,
    resolve_avalonia_repo,
)


_INSTITUTION_RECORD_FIELDS: tuple[str, ...] = (
    "institution_name_chn", "institution_name", "role",
    "begin_year", "begin_nianhao", "begin_nianhao_year", "begin_range",
    "end_year", "end_nianhao", "end_nianhao_year", "end_range",
    "place_name_chn", "place_name", "place_type",
    "source", "pages", "notes", "x_coord", "y_coord",
)
_INSTITUTION_ID_FIELDS: tuple[str, ...] = ("inst_name_code", "inst_code")

_SPLICE_SQL = (
    "SELECT bid.c_inst_name_code, bid.c_inst_code FROM BIOG_INST_DATA bid "
    "WHERE bid.c_personid = :pid "
    "ORDER BY bid.c_bi_begin_year, bid.c_inst_name_code, bid.c_inst_code"
)


def institutions_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path | None = None,
    avalonia_repo: Path | None = None,
) -> list[dict[str, Any]]:
    return fetch_via_host_with_id_splice(
        "institutions", sqlite_path, person_id,
        avalonia_repo=resolve_avalonia_repo(
            avalonia_repo=avalonia_repo,
            avalonia_data_dir=avalonia_data_dir,
        ),
        splice_sql=_SPLICE_SQL,
        splice_field_names=_INSTITUTION_ID_FIELDS,
    )


def institutions_field_names() -> tuple[str, ...]:
    return _INSTITUTION_RECORD_FIELDS


def institutions_id_field_names() -> tuple[str, ...]:
    return _INSTITUTION_ID_FIELDS


__all__ = [
    "institutions_field_names",
    "institutions_id_field_names",
    "institutions_query",
]
