"""Phase 5c-final batch 2 — thin wrapper around SqliteOfficeQueryService
via the ParityHost.

`OfficeQueryRequest` mirrors the upstream record shape. `office_query`
delegates to the host; the historical SQL-builder + SELECT-vs-record
column permutation (`_sql_row_to_record_row`) is no longer needed
because the host emits the C# record's positional shape verbatim.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cbdb_parity._person_accessor_host import resolve_avalonia_repo
from cbdb_parity.parity_host import invoke_parity_host


@dataclass(frozen=True, slots=True)
class OfficeQueryRequest:
    """Wire-compatible mirror of `Cbdb.App.Core.OfficeQueryRequest`."""

    person_keyword: str | None = None
    office_codes: Sequence[str] = ()
    person_place_ids: Sequence[int] = ()
    include_subordinate_person_units: bool = False
    office_place_ids: Sequence[int] = ()
    include_subordinate_office_units: bool = False
    use_index_year_range: bool = False
    index_year_from: int = 0
    index_year_to: int = 0
    use_office_year_range: bool = False
    office_year_from: int = 0
    office_year_to: int = 0
    dynasty_ids: Sequence[int] = ()
    limit: int = 5000


_OFFICE_RECORD_FIELDS: tuple[str, ...] = (
    "person_id", "name_chn", "name", "index_year", "index_year_type",
    "sex", "dynasty", "posting_dynasty", "index_address_id",
    "index_address", "index_address_type", "posting_id", "sequence",
    "office_code", "office", "appointment_code", "appointment_type",
    "assume_office_code", "assume_office", "office_category_id",
    "category", "first_year",
    "first_nianhao_code", "first_nianhao", "first_nianhao_pinyin",
    "first_nianhao_year",
    "first_range_code", "first_range_desc", "first_range",
    "first_month", "first_intercalary", "first_day",
    "first_ganzhi_code", "first_ganzhi", "first_ganzhi_pinyin",
    "last_year",
    "last_nianhao_code", "last_nianhao", "last_nianhao_pinyin",
    "last_nianhao_year",
    "last_range_code", "last_range_desc", "last_range",
    "last_month", "last_intercalary", "last_day",
    "last_ganzhi_code", "last_ganzhi", "last_ganzhi_pinyin",
    "institution_code", "institution_name_code", "institution",
    "office_address_id", "office_address",
    "office_x_coord", "office_y_coord", "office_xy_count",
    "source_id", "source", "pages", "notes",
    "person_place_match", "office_place_match", "place_workflow",
    "office_place_count",
)


def office_query(
    sqlite_path: Path,
    request: OfficeQueryRequest,
    *,
    avalonia_data_dir: Path | None = None,
    avalonia_repo: Path | None = None,
) -> list[dict[str, Any]]:
    repo = resolve_avalonia_repo(
        avalonia_repo=avalonia_repo,
        avalonia_data_dir=avalonia_data_dir,
    )
    response = invoke_parity_host(
        "office", sqlite_path, request, avalonia_repo=repo,
    )
    if not isinstance(response, dict):
        raise TypeError(
            f"office dispatch returned {type(response).__name__}; expected dict."
        )
    return list(response.get("records") or [])


# Phase 5b compatibility alias.
office_query_via_host = office_query


def office_query_field_names() -> tuple[str, ...]:
    return _OFFICE_RECORD_FIELDS


__all__ = [
    "OfficeQueryRequest",
    "office_query",
    "office_query_field_names",
    "office_query_via_host",
]
