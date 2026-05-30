"""Phase 5c-final — thin wrapper around GetAssociationsAsync via the
ParityHost. `assoc_code` spliced from ASSOC_DATA for Phase 4 diff
keying. Splice ORDER BY mirrors
SqlitePersonBrowserService.GetAssociationsAsync line 1881.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity._person_accessor_host import (
    fetch_via_host_with_id_splice,
    resolve_avalonia_repo,
)

_ASSOC_RECORD_FIELDS: tuple[str, ...] = (
    "sequence", "count", "associate_person_id",
    "associate_name_chn", "associate_name", "association",
    "kinship", "kin_person_id", "kin_name_chn", "kin_name",
    "associate_kinship", "associate_kin_person_id",
    "associate_kin_name_chn", "associate_kin_name",
    "claimer_person_id", "claimer_name_chn", "claimer_name",
    "address_name_chn", "address_name",
    "year", "nianhao", "nianhao_year",
    "month", "intercalary", "day", "ganzhi", "range",
    "topic_chn", "topic",
    "institution_name_chn", "institution_name",
    "occasion_chn", "occasion",
    "literary_genre_chn", "literary_genre",
    "text_title", "source_title_chn", "source_title",
    "pages", "notes",
)
_ASSOC_ID_FIELDS: tuple[str, ...] = ("assoc_code",)

_SPLICE_SQL = (
    "SELECT ad.c_assoc_code FROM ASSOC_DATA ad "
    "WHERE ad.c_personid = :pid "
    "ORDER BY ad.c_assoc_first_year, ad.c_sequence, "
    "         ad.c_assoc_code, ad.c_assoc_id"
)


def associations_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path | None = None,
    avalonia_repo: Path | None = None,
) -> list[dict[str, Any]]:
    return fetch_via_host_with_id_splice(
        "associations", sqlite_path, person_id,
        avalonia_repo=resolve_avalonia_repo(
            avalonia_repo=avalonia_repo,
            avalonia_data_dir=avalonia_data_dir,
        ),
        splice_sql=_SPLICE_SQL,
        splice_field_names=_ASSOC_ID_FIELDS,
    )


def associations_field_names() -> tuple[str, ...]:
    return _ASSOC_RECORD_FIELDS


def associations_id_field_names() -> tuple[str, ...]:
    return _ASSOC_ID_FIELDS


__all__ = [
    "associations_field_names",
    "associations_id_field_names",
    "associations_query",
]
