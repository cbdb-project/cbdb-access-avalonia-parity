"""Phase 5c-final batch 2 — thin wrapper around SqliteEntryQueryService
via the ParityHost.

`EntryQueryRequest` mirrors the upstream record shape used by Phase 3a
and Phase 5b. `entry_query` now delegates to the host, eliminating the
hand-extracted SQL builder; the host runs the real C# `QueryAsync`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cbdb_parity._person_accessor_host import resolve_avalonia_repo
from cbdb_parity.parity_host import invoke_parity_host


@dataclass(frozen=True, slots=True)
class EntryQueryRequest:
    """Wire-compatible mirror of `Cbdb.App.Core.EntryQueryRequest`.
    Serialised via dataclass `asdict()` → snake_case JSON by the
    `_to_jsonable` helper in `cbdb_parity.parity_host`.
    """

    person_keyword: str | None = None
    entry_codes: Sequence[str] = ()
    place_ids: Sequence[int] = ()
    include_subordinate_units: bool = False
    use_index_year_range: bool = False
    index_year_from: int = 0
    index_year_to: int = 0
    use_entry_year_range: bool = False
    entry_year_from: int = 0
    entry_year_to: int = 0
    dynasty_ids: Sequence[int] = ()
    limit: int = 5000


# The 35 columns (in order) of `Cbdb.App.Core.EntryQueryRecord`.
_ENTRY_RECORD_FIELDS: tuple[str, ...] = (
    "person_id", "name_chn", "name", "index_year", "index_year_type",
    "sex", "dynasty", "index_address_id", "index_address", "index_address_type",
    "sequence", "entry_code", "entry_method", "entry_year",
    "nianhao", "nianhao_year", "range", "exam_rank", "age",
    "kinship", "kin_person", "association", "associate_person", "institution",
    "exam_field", "entry_address_id", "entry_address", "entry_x_coord", "entry_y_coord",
    "entry_xy_count", "parental_status", "attempt_count",
    "source", "pages", "notes", "posting_notes",
)


def entry_query(
    sqlite_path: Path,
    request: EntryQueryRequest,
    *,
    avalonia_data_dir: Path | None = None,
    avalonia_repo: Path | None = None,
) -> list[dict[str, Any]]:
    """Run `SqliteEntryQueryService.QueryAsync` via the ParityHost
    and return the snake_case record list.
    """
    repo = resolve_avalonia_repo(
        avalonia_repo=avalonia_repo,
        avalonia_data_dir=avalonia_data_dir,
    )
    response = invoke_parity_host(
        "entry", sqlite_path, request, avalonia_repo=repo,
    )
    if not isinstance(response, dict):
        raise TypeError(
            f"entry dispatch returned {type(response).__name__}; expected dict."
        )
    return list(response.get("records") or [])


# Phase 5b compatibility alias — `entry_query_via_host` was the
# explicit host-call helper before mirror retirement.
entry_query_via_host = entry_query


def entry_query_field_names() -> tuple[str, ...]:
    return _ENTRY_RECORD_FIELDS


__all__ = [
    "EntryQueryRequest",
    "entry_query",
    "entry_query_field_names",
    "entry_query_via_host",
]
