"""Phase 5c-final batch 2 — thin wrapper around SqliteStatusQueryService
via the ParityHost.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cbdb_parity._person_accessor_host import resolve_avalonia_repo
from cbdb_parity.parity_host import invoke_parity_host


@dataclass(frozen=True, slots=True)
class StatusQueryRequest:
    """Wire-compatible mirror of `Cbdb.App.Core.StatusQueryRequest`."""

    person_keyword: str | None = None
    status_codes: Sequence[str] = ()
    place_ids: Sequence[int] = ()
    include_subordinate_units: bool = False
    use_index_year_range: bool = False
    index_year_from: int = 0
    index_year_to: int = 0
    dynasty_ids: Sequence[int] = ()
    limit: int = 5000


_STATUS_RECORD_FIELDS: tuple[str, ...] = (
    "person_id", "name_chn", "name", "index_year", "index_year_type",
    "sex", "dynasty", "index_address_id", "index_address",
    "index_address_type", "x_coord", "y_coord",
    "sequence", "status", "status_code",
    "first_year", "first_nianhao_code", "first_nianhao",
    "first_nianhao_pinyin", "first_nianhao_year",
    "first_range_code", "first_range_desc", "first_range",
    "last_year", "last_nianhao_code", "last_nianhao",
    "last_nianhao_pinyin", "last_nianhao_year",
    "last_range_code", "last_range_desc", "last_range",
    "supplement", "source_id", "source", "pages", "notes",
)


def status_query(
    sqlite_path: Path,
    request: StatusQueryRequest,
    *,
    avalonia_data_dir: Path | None = None,
    avalonia_repo: Path | None = None,
) -> list[dict[str, Any]]:
    repo = resolve_avalonia_repo(
        avalonia_repo=avalonia_repo,
        avalonia_data_dir=avalonia_data_dir,
    )
    response = invoke_parity_host(
        "status", sqlite_path, request, avalonia_repo=repo,
    )
    if not isinstance(response, dict):
        raise TypeError(
            f"status dispatch returned {type(response).__name__}; expected dict."
        )
    return list(response.get("records") or [])


# Phase 5b compatibility alias.
status_query_via_host = status_query


def status_query_field_names() -> tuple[str, ...]:
    return _STATUS_RECORD_FIELDS


__all__ = [
    "StatusQueryRequest",
    "status_query",
    "status_query_field_names",
    "status_query_via_host",
]
