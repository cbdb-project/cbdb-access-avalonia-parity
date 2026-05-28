"""Python re-execution of Avalonia SqlitePersonBrowserService.GetAltNamesAsync
(Phase 4, Tier 2 per-person accessor #1).

Differs from the Phase 3c/3d/3e pattern in two ways:

1. The query is per-person (single-id filter), not a search across
   the corpus. There's no `Request` dataclass with many filters —
   just a `person_id: int`.

2. The C# reader applies a `JoinDisplay(chn, en)` post-fetch on two
   columns (`NameType`, `Source`) before returning the record. We
   mirror that here so the row dicts we return match what Avalonia
   actually surfaces to its UI.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_query_sql import find_sql_block

# Fields surfaced in the row dict. The first 7 mirror the C# record
# `PersonAltNameItem` exactly (what Avalonia ships to the UI). The
# last 2 are STABLE row-identifier helpers we add for diff-keying;
# they are NOT part of the C# record's user-visible payload, so they
# stay out of `compare_fields()` on the parity tests.
_ALTNAME_RECORD_FIELDS: tuple[str, ...] = (
    "sequence",         # 0  a.c_sequence (IsDBNull → 0 in C# reader)
    "alt_name_chn",     # 1  a.c_alt_name_chn
    "alt_name",         # 2  a.c_alt_name
    "name_type",        # 3  JoinDisplay(anc.c_name_type_desc_chn, anc.c_name_type_desc)
    "source",           # 4  JoinDisplay(src.c_title_chn, src.c_title)
    "pages",            # 5  a.c_pages
    "notes",            # 6  a.c_notes
)
# Stable row-identifier columns (raw codes, NOT post-processed):
# included in the row dict so the parity diff can key on them but
# excluded from the C#-record-equivalent `_ALTNAME_RECORD_FIELDS`
# that drives `compare_fields()`. ALTNAME_DATA has a natural unique
# key of (c_personid, c_sequence, c_alt_name_type_code, c_source,
# c_alt_name_chn); we expose the discriminating subset.
_ALTNAME_ID_FIELDS: tuple[str, ...] = (
    "name_type_code",   # raw a.c_alt_name_type_code
    "source_id",        # raw a.c_source
)


def _csharp_params_to_sqlite(sql: str) -> str:
    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", r":\1", sql)


def _load_get_altnames_sql(cs_path: Path) -> str:
    # `c_name_type_desc_chn` is unique to the GetAltNamesAsync SELECT
    # block; CountAsync's altname block doesn't reference the lookup
    # columns. Disambiguates the two `FROM ALTNAME_DATA a` blocks in
    # SqlitePersonBrowserService.cs.
    return find_sql_block(cs_path, "c_name_type_desc_chn")


def _join_display(primary: str | None, secondary: str | None) -> str | None:
    """Direct port of `SqlitePersonBrowserService.JoinDisplay` (which the
    C# reader applies before constructing `PersonAltNameItem`).

    - primary blank → return secondary as-is.
    - secondary blank OR == primary (case-insensitive) → return primary.
    - else → `"{primary} / {secondary}"`.
    """
    if primary is None or not primary.strip():
        return secondary
    if (
        secondary is None
        or not secondary.strip()
        or primary.casefold() == secondary.casefold()
    ):
        return primary
    return f"{primary} / {secondary}"


def altnames_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path,
) -> list[dict[str, Any]]:
    """Execute the Avalonia GetAltNamesAsync SQL against `sqlite_path`
    and return rows shaped like `PersonAltNameItem`. The C# reader's
    `IsDBNull → 0` coercion on `Sequence` is replicated; `JoinDisplay`
    on NameType / Source is replicated.

    NOTE: we augment the C# SELECT with two extra columns
    (`a.c_alt_name_type_code`, `a.c_source`) that ARE NOT in the
    `PersonAltNameItem` record. The parity diff needs them as a
    stable row-identifier key — keying on `name_type` / `source`
    alone is unstable because those are themselves post-processed
    display strings and any disagreement would produce
    `only_in_X / only_in_Y` instead of a single `value_mismatch`.
    """
    cs_path = avalonia_data_dir / "SqlitePersonBrowserService.cs"
    template = _load_get_altnames_sql(cs_path)
    # Splice `a.c_alt_name_type_code, a.c_source` into the SELECT
    # list. They sit between `a.c_notes` and the FROM clause so the
    # extracted SQL position-binds cleanly. Doing this here (rather
    # than maintaining a parallel hand-written SQL) keeps the C#
    # source as the canonical query shape.
    augmented = template.replace(
        "a.c_notes\nFROM",
        "a.c_notes,\n    a.c_alt_name_type_code,\n    a.c_source\nFROM",
    )
    if augmented == template:
        raise RuntimeError(
            "altnames SQL extracted from C# no longer matches the expected "
            "shape (missing `a.c_notes\\nFROM` anchor for ID-column splice). "
            "Inspect SqlitePersonBrowserService.cs for an upstream rewrite."
        )
    sql = _csharp_params_to_sqlite(augmented)
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(sqlite_path) as conn:
        cursor = conn.execute(sql, {"personId": person_id})
        for row in cursor.fetchall():
            (seq, alt_chn, alt, ntype_chn, ntype, src_chn, src, pages, notes,
             ntype_code, source_id) = row
            rows.append({
                "sequence":       seq if seq is not None else 0,
                "alt_name_chn":   alt_chn,
                "alt_name":       alt,
                "name_type":      _join_display(ntype_chn, ntype),
                "source":         _join_display(src_chn, src),
                "pages":          pages,
                "notes":          notes,
                "name_type_code": ntype_code,
                "source_id":      source_id,
            })
    return rows


def altnames_field_names() -> tuple[str, ...]:
    """User-visible field names that mirror `PersonAltNameItem`.
    Used by parity tests as `compare_fields=...`; this set
    EXCLUDES the diff-key-only `name_type_code` / `source_id`
    columns so we don't accidentally compare raw identifier
    surfaces as if they were content."""
    return _ALTNAME_RECORD_FIELDS


def altnames_id_field_names() -> tuple[str, ...]:
    """Stable row-identifier field names. Use these as
    `key_fields=(...)` in `diff_rows()` so duplicate-content rows
    (same sequence + alt_name_chn but different name_type / source)
    don't collapse into one entry in the diff dict."""
    return _ALTNAME_ID_FIELDS


__all__ = [
    "_join_display",
    "altnames_field_names",
    "altnames_id_field_names",
    "altnames_query",
]
_ = Sequence  # keep import live
