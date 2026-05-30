"""Phase 5c-final batch 2 — postings stub.

Unlike the other PersonBrowser accessors, `GetPostingsAsync`
returns a *nested* `PersonPostingItem` (postings → offices →
addresses), not a flat row list. The Phase 4 postings pair test
was designed to diff the *raw SQL row* output (so the Access and
Avalonia sides could agree column-for-column on the underlying
POSTED_TO_OFFICE_DATA join).

With the SQL extractor gone, this module no longer has a path to
build that raw-row mirror without either (a) re-implementing the
upstream JOIN here by hand, or (b) renormalising the host's
nested response back into the row shape. Both are real work and
not load-bearing for the rest of Phase 5; postings is therefore
left as a `NotImplementedError` and the Phase 4 pair test remains
skipped with an updated rationale.

A follow-up can pick this up by:
  1. host-call into the `postings` dispatch (nested output);
  2. unfold (posting × office × address) into flat dict rows
     matching `_POSTING_RECORD_FIELDS`; OR
  3. add a hand-written sqlite query that mirrors the C# JOIN
     shape directly (the appointment-code expression now lives
     in `SqliteSchemaCompatibility`, so we can call the same
     helper through the ParityHost rather than re-extracting
     interpolated SQL).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

_POSTING_RECORD_FIELDS: tuple[str, ...] = (
    "posting_id", "office_id", "sequence",
    "office_name_chn", "office_name",
    "appt_desc_chn", "appt_desc",
    "assume_office_desc_chn", "assume_office_desc",
    "category_desc_chn", "category_desc",
    "first_year",
    "fy_nianhao_chn", "fy_nianhao_pin",
    "fy_nh_year",
    "fy_range_chn", "fy_range",
    "fy_month", "fy_intercalary", "fy_day",
    "fy_ganzhi_chn", "fy_ganzhi_py",
    "last_year",
    "ly_nianhao_chn", "ly_nianhao_pin",
    "ly_nh_year",
    "ly_range_chn", "ly_range",
    "ly_month", "ly_intercalary", "ly_day",
    "ly_ganzhi_chn", "ly_ganzhi_py",
    "dynasty_chn", "dynasty",
    "source_title_chn", "source_title",
    "pages", "notes",
    "created_by", "created_date",
    "modified_by", "modified_date",
    "addr_id",
    "addr_name_chn", "addr_name",
    "addr_created_by", "addr_created_date",
    "addr_modified_by", "addr_modified_date",
)
_POSTING_ID_FIELDS: tuple[str, ...] = ()


def postings_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path | None = None,
    avalonia_repo: Path | None = None,
) -> list[dict[str, Any]]:
    raise NotImplementedError(
        "Phase 5c-final retired the SQL-extractor mirror but the "
        "host's GetPostingsAsync returns a nested PersonPostingItem "
        "wire format incompatible with the Phase 4 raw-row diff. "
        "See module docstring for unblock options."
    )


def postings_field_names() -> tuple[str, ...]:
    return _POSTING_RECORD_FIELDS


def postings_id_field_names() -> tuple[str, ...]:
    return _POSTING_ID_FIELDS


__all__ = [
    "postings_field_names",
    "postings_id_field_names",
    "postings_query",
]
