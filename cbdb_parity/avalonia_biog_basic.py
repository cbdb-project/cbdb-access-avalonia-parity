"""Phase 5c-final batch 2 — thin wrapper around SearchAsync
(no-keyword branch) via the ParityHost.

The mirror only ports the no-keyword path today (Phase 4 partial-
paired surface). SearchAsync upstream supports keyword search too;
when a follow-up wants to cover that, just pass `keyword` through.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity._person_accessor_host import resolve_avalonia_repo
from cbdb_parity.parity_host import invoke_parity_host


_BIOG_BASIC_FIELDS: tuple[str, ...] = (
    "person_id",     # PersonListItem.PersonId
    "name_chn",      # PersonListItem.NameChn
    "name_rm",       # PersonListItem.NameRm
    "index_year",    # PersonListItem.IndexYear
    "index_address", # PersonListItem.IndexAddress
)


def biog_basic_query(
    sqlite_path: Path,
    *,
    limit: int = 200,
    offset: int = 0,
    keyword: str | None = None,
    avalonia_data_dir: Path | None = None,
    avalonia_repo: Path | None = None,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))
    repo = resolve_avalonia_repo(
        avalonia_repo=avalonia_repo,
        avalonia_data_dir=avalonia_data_dir,
    )
    response = invoke_parity_host(
        "biog_basic", sqlite_path,
        {"keyword": keyword, "limit": limit, "offset": offset},
        avalonia_repo=repo,
    )
    if not isinstance(response, list):
        raise TypeError(
            f"biog_basic dispatch returned {type(response).__name__}; "
            f"expected list."
        )
    return response


def biog_basic_field_names() -> tuple[str, ...]:
    return _BIOG_BASIC_FIELDS


__all__ = ["biog_basic_field_names", "biog_basic_query"]
