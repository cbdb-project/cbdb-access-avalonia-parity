"""Phase 5c-final batch 2 — thin wrapper around GetDetailAsync
via the ParityHost.

GetDetailAsync returns a single `PersonDetail` (not a list).
Phase 4 detail_pair compares as `[detail_dict]` so we wrap the
result into a list. `Fields` (the dynamic `IReadOnlyList<PersonFieldValue>`)
is now surfaced verbatim — no longer a known mirror gap.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity._person_accessor_host import resolve_avalonia_repo
from cbdb_parity.parity_host import invoke_parity_host

# Phase 4 access bridge still uses these — count queries match the
# upstream COUNT(*) suffixes appended to GetDetailAsync. Kept here
# rather than duplicated in access_detail.py so a future schema
# change updates both halves at once.
_COUNT_QUERIES: dict[str, str] = {
    "address_count":     "SELECT COUNT(*) FROM BIOG_ADDR_DATA WHERE c_personid = ?",
    "alt_name_count":    "SELECT COUNT(*) FROM ALTNAME_DATA WHERE c_personid = ?",
    "kin_count":         "SELECT COUNT(*) FROM KIN_DATA WHERE c_personid = ?",
    "assoc_count":       "SELECT COUNT(*) FROM ASSOC_DATA WHERE c_personid = ?",
    "office_count":      "SELECT COUNT(*) FROM POSTED_TO_OFFICE_DATA WHERE c_personid = ?",
    "entry_count":       "SELECT COUNT(*) FROM ENTRY_DATA WHERE c_personid = ?",
    "event_count":       "SELECT COUNT(*) FROM EVENTS_DATA WHERE c_personid = ?",
    "status_count":      "SELECT COUNT(*) FROM STATUS_DATA WHERE c_personid = ?",
    "text_count":        "SELECT COUNT(*) FROM BIOG_TEXT_DATA WHERE c_personid = ?",
    "possession_count":  "SELECT COUNT(*) FROM POSSESSION_DATA WHERE c_personid = ?",
    "source_count":      "SELECT COUNT(*) FROM BIOG_SOURCE_DATA WHERE c_personid = ?",
    "institution_count": "SELECT COUNT(*) FROM BIOG_INST_DATA WHERE c_personid = ?",
}


def _gender_label(value: Any) -> str:
    if value is None:
        return "Unknown"
    return "F" if value == 1 else "M"


_DETAIL_FIELDS: tuple[str, ...] = (
    "person_id", "surname_chn", "mingzi_chn", "surname", "mingzi",
    "surname_proper", "mingzi_proper", "surname_rm", "mingzi_rm",
    "name", "name_chn",
    "index_year", "index_year_type", "index_year_source",
    "dynasty", "dynasty_chn", "birth_year", "death_year", "gender",
    "index_address", "index_address_chn", "index_address_type",
    "address_count", "alt_name_count", "kin_count", "assoc_count",
    "office_count", "entry_count", "event_count", "status_count",
    "text_count", "possession_count", "source_count",
    "institution_count",
    # `fields` (PersonFieldValue[]) is dynamic PersonExtra2024
    # metadata that Access has no analogue for. The host still
    # surfaces it on the wire so the Phase 5c mirror-vs-host check
    # sees it; we just don't include it in the Phase 4 compare
    # tuple because there's no Access ground truth to diff against.
)


def detail_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path | None = None,
    avalonia_repo: Path | None = None,
) -> list[dict[str, Any]]:
    repo = resolve_avalonia_repo(
        avalonia_repo=avalonia_repo,
        avalonia_data_dir=avalonia_data_dir,
    )
    detail = invoke_parity_host(
        "detail", sqlite_path, {"person_id": person_id},
        avalonia_repo=repo,
    )
    if detail is None:
        return []
    if not isinstance(detail, dict):
        raise TypeError(
            f"detail dispatch returned {type(detail).__name__}; "
            f"expected dict."
        )
    return [detail]


def detail_field_names() -> tuple[str, ...]:
    return _DETAIL_FIELDS


__all__ = [
    "_COUNT_QUERIES",
    "_gender_label",
    "detail_field_names",
    "detail_query",
]
