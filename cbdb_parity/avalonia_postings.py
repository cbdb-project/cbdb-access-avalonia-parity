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


def _to_bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _row_to_dict(r: tuple[Any, ...]) -> dict[str, Any]:
    """Map a raw POSTED_TO_OFFICE_DATA-join row (50 columns, in the
    historical SELECT order documented in Phase 4) to the postings
    record dict. Still used by the Phase 4 Access bridge
    (`cbdb_parity.access_postings`) to produce its raw-row output.
    The Avalonia side no longer calls this — see `postings_query`.
    """
    return {
        "posting_id":             r[0],
        "office_id":              r[1],
        "sequence":               r[2],
        "office_name_chn":        r[3],
        "office_name":            r[4],
        "appt_desc_chn":          r[5],
        "appt_desc":              r[6],
        "assume_office_desc_chn": r[7],
        "assume_office_desc":     r[8],
        "category_desc_chn":      r[9],
        "category_desc":          r[10],
        "first_year":             r[11],
        "fy_nianhao_chn":         r[12],
        "fy_nianhao_pin":         r[13],
        "fy_nh_year":             r[14],
        "fy_range_chn":           r[15],
        "fy_range":               r[16],
        "fy_month":               r[17],
        "fy_intercalary":         _to_bool_or_none(r[18]),
        "fy_day":                 r[19],
        "fy_ganzhi_chn":          r[20],
        "fy_ganzhi_py":           r[21],
        "last_year":              r[22],
        "ly_nianhao_chn":         r[23],
        "ly_nianhao_pin":         r[24],
        "ly_nh_year":             r[25],
        "ly_range_chn":           r[26],
        "ly_range":               r[27],
        "ly_month":               r[28],
        "ly_intercalary":         _to_bool_or_none(r[29]),
        "ly_day":                 r[30],
        "ly_ganzhi_chn":          r[31],
        "ly_ganzhi_py":           r[32],
        "dynasty_chn":            r[33],
        "dynasty":                r[34],
        "source_title_chn":       r[35],
        "source_title":           r[36],
        "pages":                  r[37],
        "notes":                  r[38],
        "created_by":             r[39],
        "created_date":           r[40],
        "modified_by":            r[41],
        "modified_date":          r[42],
        "addr_id":                r[43],
        "addr_name_chn":          r[44],
        "addr_name":              r[45],
        "addr_created_by":        r[46],
        "addr_created_date":      r[47],
        "addr_modified_by":       r[48],
        "addr_modified_date":     r[49],
    }


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
    "_row_to_dict",
    "postings_field_names",
    "postings_id_field_names",
    "postings_query",
]
