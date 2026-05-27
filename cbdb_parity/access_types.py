"""MySQL → Microsoft Access type-token rewriter (Phase 1.3b helper).

Parallel structure to `cbdb_parity.sqlite_builder.mysql_type_to_sqlite`.
The mapping table is the starting point captured from:
  - $ACCESS_MYSQL_TRANSFER_REPO/mysql2access.ipynb cell 0 `field_type`
    dict (covers int/smallint/double/timestamp/bit/longtext/varchar)
  - $ACCESS_MYSQL_TRANSFER_REPO/README.md gotchas:
      §1 utf8mb4 incompatibility — varchar(255) must drop to varchar(191)
         if Access INSERT complains about row size
      §3 BIT (and BYTE) coerced to SMALLINT to avoid the Access
         "all booleans become 1" bug
  - Empirical CBDB Datadump column types observed during 1.2 sqlite
    build (decimal/double/varchar(N)/text/longtext/datetime/date/time)

What "Access type" means here is whatever string we splice into a
`CREATE TABLE "T" ("col" <type>, ...)` issued through the Microsoft
Access ODBC driver. The driver accepts both the ODBC standard names
(INTEGER, VARCHAR(N), LONGTEXT, DOUBLE, DATETIME, SMALLINT, LONGBINARY)
and the Access-native names (Long, Memo, etc.); we use the ODBC names
because they round-trip cleanly through `cursor.execute`.
"""

from __future__ import annotations

import re

# Pattern → replacement, applied in declaration order. Same architecture
# as `_TYPE_MAP` in `sqlite_builder.py`. Note: no trailing `\b` after
# `(N)` patterns because Python re (and PCRE) don't match `\b` after `)`.
_TYPE_MAP: tuple[tuple[re.Pattern[str], str], ...] = (
    # Integer family — all map to ODBC INTEGER (Access Long).
    (re.compile(r"\bTINYINT\(1\)", re.I), "SMALLINT"),    # tinyint(1) = bool; per README §3 → SMALLINT not BIT
    (re.compile(r"\bTINYINT\(\d+\)", re.I), "SMALLINT"),  # other tinyint widths stay in SMALLINT's range
    (re.compile(r"\bTINYINT\b", re.I), "SMALLINT"),
    (re.compile(r"\bSMALLINT\(\d+\)", re.I), "SMALLINT"),
    (re.compile(r"\bSMALLINT\b", re.I), "SMALLINT"),
    (re.compile(r"\bMEDIUMINT\(\d+\)", re.I), "INTEGER"),
    (re.compile(r"\bMEDIUMINT\b", re.I), "INTEGER"),
    (re.compile(r"\bBIGINT\(\d+\)", re.I), "INTEGER"),    # Access has no 64-bit; widen at risk of overflow
    (re.compile(r"\bBIGINT\b", re.I), "INTEGER"),
    (re.compile(r"\bINT\(\d+\)", re.I), "INTEGER"),
    (re.compile(r"\bINT\b", re.I), "INTEGER"),
    # Floats. NUMERIC/DECIMAL also folded to DOUBLE — Access NUMERIC
    # is fixed-precision, but mysql2access.ipynb has historically used
    # DOUBLE for CBDB rows and we mirror that until a real schema
    # forces otherwise.
    (re.compile(r"\bDOUBLE\b", re.I), "DOUBLE"),
    (re.compile(r"\bFLOAT\b", re.I), "DOUBLE"),
    (re.compile(r"\bDECIMAL\([^)]*\)", re.I), "DOUBLE"),
    (re.compile(r"\bNUMERIC\([^)]*\)", re.I), "DOUBLE"),
    # Text variants. LONGTEXT == Access Memo (effectively unlimited).
    # VARCHAR(N) stays explicit so we can downsize if utf8mb4 row-size
    # complaints come back (README §1).
    (re.compile(r"\bLONGTEXT\b", re.I), "LONGTEXT"),
    (re.compile(r"\bMEDIUMTEXT\b", re.I), "LONGTEXT"),
    (re.compile(r"\bTINYTEXT\b", re.I), "VARCHAR(255)"),
    (re.compile(r"\bTEXT\b", re.I), "LONGTEXT"),
    (re.compile(r"\bVARCHAR\((\d+)\)", re.I), r"VARCHAR(\1)"),
    (re.compile(r"\bCHAR\((\d+)\)", re.I), r"VARCHAR(\1)"),  # Access has no fixed CHAR
    # Date/time. Access DATETIME covers DATE / TIME / TIMESTAMP too.
    (re.compile(r"\bDATETIME\b", re.I), "DATETIME"),
    (re.compile(r"\bTIMESTAMP\b", re.I), "DATETIME"),
    (re.compile(r"\bDATE\b", re.I), "DATETIME"),
    (re.compile(r"\bTIME\b", re.I), "DATETIME"),
    # Enum/Set — both stringy in MySQL; widest Access text bucket.
    (re.compile(r"\bENUM\([^)]+\)", re.I), "LONGTEXT"),
    (re.compile(r"\bSET\([^)]+\)", re.I), "LONGTEXT"),
    # Binary. BIT explicitly excluded (per README §3, SMALLINT instead).
    (re.compile(r"\bVARBINARY\(\d+\)", re.I), "LONGBINARY"),
    (re.compile(r"\bBINARY\(\d+\)", re.I), "LONGBINARY"),
    (re.compile(r"\bBLOB\b", re.I), "LONGBINARY"),
    (re.compile(r"\bMEDIUMBLOB\b", re.I), "LONGBINARY"),
    (re.compile(r"\bLONGBLOB\b", re.I), "LONGBINARY"),
    (re.compile(r"\bTINYBLOB\b", re.I), "LONGBINARY"),
    # BIT must follow the integer family so `\bBIT\b` only fires when
    # nothing else matched. README §3 fix: coerce to SMALLINT.
    (re.compile(r"\bBIT\(\d+\)", re.I), "SMALLINT"),
    (re.compile(r"\bBIT\b", re.I), "SMALLINT"),
)


def mysql_type_to_access(mysql_type: str) -> str:
    """Translate a single MySQL column type string to its Access equivalent.

    Public for unit-testing the mapping in isolation; the mdb builder
    calls this for every column it sees.
    """
    out = mysql_type
    for pat, repl in _TYPE_MAP:
        out = pat.sub(repl, out)
    return out.strip()
