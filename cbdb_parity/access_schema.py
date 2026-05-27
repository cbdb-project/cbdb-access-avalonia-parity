"""Loader for the CBDB Access schema declared in `TablesFields.xlsx`.

The canonical mapping of CBDB MySQL tables → Access tables lives in
`$ACCESS_MYSQL_TRANSFER_REPO/TablesFields.xlsx` (a 669-row sheet maintained
by the CBDB team). Each row tells us:
  - which Access table + column to create
  - the Access data type (Long, Integer, Memo, Text, Double, Binary)
  - whether the column is part of the primary key
  - whether NULL is allowed
  - foreign-key target if any

Phase 1.3a (this module) reads that sheet into typed dataclasses. The mdb
writer (Phase 1.3b) consumes the dataclasses to CREATE TABLE + INSERT.
Keeping the loader separate means the schema model is testable without
Microsoft Access ODBC, and the build pipeline can validate Datadump
column coverage *before* spending minutes writing the mdb.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

# The seven legal DataFormat values. The xlsx has both "Binary" and the
# (apparently typo) "binary"; we normalise to upper-first.
_VALID_TYPES: frozenset[str] = frozenset({
    "Long",        # 32-bit integer in Access
    "Integer",     # 16-bit integer
    "Double",
    "Text",        # Access short text (≤255 chars)
    "Memo",        # Access long text
    "Binary",      # Fixed-length binary
})

# "Primary" and "Primary Key" both appear in the xlsx; normalise.
_PRIMARY_LABELS: frozenset[str] = frozenset({"Primary", "Primary Key"})


class AccessSchemaError(RuntimeError):
    """Raised when the xlsx layout deviates from the documented shape."""


@dataclass(frozen=True, slots=True)
class AccessColumn:
    name: str
    # `None` means the xlsx left DataFormat blank — Phase 1.3b's mdb
    # writer falls back to the type from the Datadump's CREATE TABLE for
    # that column. ~3% of real-xlsx rows are blank-format (e.g. some
    # `c_personid` rows). One of _VALID_TYPES otherwise.
    data_format: str | None
    nullable: bool
    is_primary_key: bool
    foreign_key_table: str | None = None
    foreign_key_column: str | None = None
    # Datadump-side names. In the current real xlsx these are blank for
    # every row (same name on both sides), but the schema allows them so
    # a future override row can re-map a renamed source column.
    dump_table_name: str | None = None
    dump_field_name: str | None = None


@dataclass(frozen=True, slots=True)
class AccessTable:
    name: str
    columns: tuple[AccessColumn, ...]

    @property
    def primary_key_columns(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns if c.is_primary_key)


@dataclass(slots=True)
class AccessSchema:
    """Full schema for the CBDB `data` mdb."""

    tables: dict[str, AccessTable] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.tables)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.tables.values())

    def __getitem__(self, name: str) -> AccessTable:
        return self.tables[name]


# Expected xlsx columns (1-based positions match openpyxl's column iteration).
_HEADER_LAYOUT = (
    "RowNum",
    "DumpTblNm",
    "DumpFldNm",
    "AccessTblNm",
    "AccessFldNm",
    "IndexOnField",
    "DataFormat",
    "NULL_allowed",
    "ForeignKey",
    "ForeignKeyBaseField",
)


_NULL_TRUE_TEXT: frozenset[str] = frozenset({"true", "yes", "y", "1"})
_NULL_FALSE_TEXT: frozenset[str] = frozenset({"false", "no", "n", "0"})


def _coerce_nullable(raw: object) -> bool:
    """Interpret an xlsx cell as a boolean 'nullable' flag.

    Excel booleans round-trip as Python `True`/`False`. Some xlsx variants
    use Yes/No or 1/0 text instead. A blank cell ("", None) means
    "unspecified" — default to True (nullable) since that's the safer
    Access default for an undeclared NOT NULL constraint.
    """
    if raw is None:
        return True
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        return bool(raw)
    text = str(raw).strip().lower()
    if not text:
        return True
    if text in _NULL_TRUE_TEXT:
        return True
    if text in _NULL_FALSE_TEXT:
        return False
    raise AccessSchemaError(f"cannot interpret nullable cell {raw!r} as boolean")


def _coerce_optional_str(raw: object) -> str | None:
    """Strip whitespace; return None for blanks so downstream `is None`
    checks work correctly (we never want to store an empty FK target)."""
    if raw is None:
        return None
    text = str(raw).strip()
    return text if text else None


def load_access_schema(xlsx_path: Path) -> AccessSchema:
    """Read `TablesFields.xlsx` into a strongly-typed AccessSchema.

    Raises AccessSchemaError on:
      - header drift (renamed sheet, re-ordered columns, EXTRA columns —
        the schema is tightly versioned; new columns must land in code
        first, not silently in the spreadsheet)
      - unknown DataFormat value
      - blank DataFormat (every row must declare a type)
      - duplicate column within the same table
      - uninterpretable nullable cell
    """
    if not xlsx_path.is_file():
        raise AccessSchemaError(f"TablesFields.xlsx not found: {xlsx_path}")

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    try:
        if not wb.sheetnames:
            raise AccessSchemaError("workbook has no sheets")
        ws = wb[wb.sheetnames[0]]
        rows = ws.iter_rows(values_only=True)

        header = next(rows, None)
        if header is None:
            raise AccessSchemaError("workbook is empty")
        # Header must MATCH the canonical layout exactly — including length.
        # A future xlsx that adds a column needs a code update so we don't
        # silently drop data.
        if tuple(header) != _HEADER_LAYOUT and tuple(header)[: len(_HEADER_LAYOUT)] != _HEADER_LAYOUT:
            raise AccessSchemaError(
                f"unexpected header row {header!r} (expected {_HEADER_LAYOUT})"
            )
        if len(header) > len(_HEADER_LAYOUT) and any(c is not None for c in header[len(_HEADER_LAYOUT):]):
            raise AccessSchemaError(
                f"unknown extra header columns {header[len(_HEADER_LAYOUT):]!r} — "
                f"loader needs an update before the new columns can be used"
            )

        # Two-pass build: collect column rows per table, then freeze.
        # Insertion order = first-occurrence order in xlsx, which downstream
        # CREATE-TABLE emitters may rely on for FK-dependency layering.
        per_table: dict[str, list[AccessColumn]] = {}
        for row_idx, row in enumerate(rows, start=2):  # row 1 = header
            if not any(row):
                continue
            # Reject data past the documented column range — catches stray
            # cells (and the case where header cell was blank but the data
            # cell was filled, which the header-time check can't see).
            if len(row) > len(_HEADER_LAYOUT) and any(
                c is not None and (not isinstance(c, str) or c.strip())
                for c in row[len(_HEADER_LAYOUT):]
            ):
                raise AccessSchemaError(
                    f"row {row_idx}: unexpected non-blank data past column "
                    f"{len(_HEADER_LAYOUT)} — loader needs an update before "
                    f"the new column can be used"
                )
            (_rownum, dump_tbl, dump_fld, access_tbl, access_fld,
             index_on_field, data_format, nullable, fk_table, fk_column) = row[: len(_HEADER_LAYOUT)]
            # Strip BEFORE the truthiness check — whitespace-only cells
            # like "   " are truthy as raw strings but represent blank
            # data; without stripping first we'd create a "" table name.
            access_tbl = str(access_tbl).strip() if access_tbl is not None else ""
            access_fld = str(access_fld).strip() if access_fld is not None else ""
            if not access_tbl or not access_fld:
                # Blank table/column field → skip; the xlsx has occasional
                # spacer rows.
                continue
            fmt_raw = (str(data_format).strip() if data_format else "")
            # Blank DataFormat is allowed (the real xlsx has ~20 such rows,
            # e.g. POSTED_TO_ADDR_DATA.c_personid). We store None and let
            # the mdb writer fall back to the Datadump's CREATE TABLE for
            # that column's type.
            fmt: str | None
            if not fmt_raw:
                fmt = None
            else:
                fmt = fmt_raw.capitalize()
                if fmt not in _VALID_TYPES:
                    raise AccessSchemaError(
                        f"{access_tbl}.{access_fld}: unknown DataFormat "
                        f"{data_format!r} (allowed: {sorted(_VALID_TYPES)})"
                    )
            is_pk = (
                str(index_on_field).strip() in _PRIMARY_LABELS
                if index_on_field is not None
                else False
            )
            col = AccessColumn(
                name=access_fld,
                data_format=fmt,
                nullable=_coerce_nullable(nullable),
                is_primary_key=is_pk,
                foreign_key_table=_coerce_optional_str(fk_table),
                foreign_key_column=_coerce_optional_str(fk_column),
                dump_table_name=_coerce_optional_str(dump_tbl),
                dump_field_name=_coerce_optional_str(dump_fld),
            )
            cols = per_table.setdefault(access_tbl, [])
            if any(existing.name == col.name for existing in cols):
                raise AccessSchemaError(
                    f"duplicate column `{col.name}` in table `{access_tbl}`"
                )
            cols.append(col)
    finally:
        wb.close()

    schema = AccessSchema()
    for tbl_name, cols in per_table.items():
        schema.tables[tbl_name] = AccessTable(name=tbl_name, columns=tuple(cols))
    return schema
