"""Extract raw SQL templates from Cbdb.App.Data/Sqlite*QueryService.cs.

Phase 3a (reduced scope vs the originally-planned .NET test host —
which would have needed `dotnet build`, but the user's machine only has
the .NET runtime, no SDK).

Strategy: each `Sqlite*QueryService.cs` file in
`$AVALONIA_REPO/Cbdb.App.Data/` contains its core queries as C# raw
string literals (delimited by three double-quotes). Those literals are the SAME bytes the
Avalonia desktop app sends to SQLite at runtime. We can therefore read
them straight from the .cs file and execute them against `cbdb.sqlite`
via Python's `sqlite3` and get bitwise-identical results — no .NET
process needed.

Limitations:
  - SQL fragments that the C# code concatenates dynamically (e.g. the
    `IN ($entryCode0, $entryCode1, ...)` clauses generated based on
    request list lengths) need a Python-side equivalent. The
    higher-level functions in `cbdb_parity.avalonia_query` handle that.
  - C# `$parameter` syntax maps to Python's named-parameter style
    (`:parameter`); the higher-level functions also do that rewrite.

This module ONLY pulls the raw triple-double-quote-delimited blocks;
it does not parse them as SQL or rewrite parameter syntax.
"""

from __future__ import annotations

import re
from pathlib import Path

# C# raw string literal delimiter is three double-quotes. We match the
# OPENING triple-quote at end-of-line (per the codebase's style) and
# the CLOSING triple-quote at start-of-line; that handles the multi-line
# SQL blocks in Sqlite*QueryService.cs without false positives on
# inline double-quotes.
_RAW_BLOCK = re.compile(
    r'"""\s*\n'             # opening """ followed by a newline
    r"(.*?)"                # SQL body (lazy, multiline)
    r'\n\s*"""',            # closing """ on its own line, any leading ws
    re.DOTALL,
)

# C# verbatim-string literal `@"..."` (NON-interpolated). Used by
# SqlitePersonBrowserService and other older `Cbdb.App.Data` files
# instead of triple-quoted raw strings. We DELIBERATELY exclude the
# interpolated variants `$@"..."` / `@$"..."` because those contain
# `{placeholder}` substitutions whose values are known only at
# runtime — returning them as if they were executable SQL would
# break callers that feed the result straight to sqlite3 / pyodbc.
# Interpolated raw strings `$"""..."""` ARE matched by `_RAW_BLOCK`,
# but their callers in Phase 3 (entry/office/status) substitute
# `{...}` placeholders explicitly before executing; the verbatim
# path has no such per-caller hook, so silently passing through
# templates would yield wrong results.
_VERBATIM_BLOCK = re.compile(
    r'(?<![\$@])@"\s*\n'    # opening @" NOT preceded by $ or @
    r"(.*?)"                # SQL body (lazy, multiline)
    r'"(?!")',              # closing " NOT followed by another "
    re.DOTALL,
)


def extract_sql_blocks(cs_path: Path) -> list[str]:
    """Return every C# string-literal SQL block in `cs_path`, in
    SOURCE-ORDER (top-to-bottom of file).

    Handles the two literal styles whose source text is GUARANTEED
    to be executable SQL:
      - Triple-quoted raw strings `\"\"\"...\"\"\"` (newer
        `Sqlite*QueryService.cs` files).
      - Verbatim strings `@"..."` (older
        `SqlitePersonBrowserService.cs` and friends).

    INTERPOLATED variants (`$@"..."`, `@$"..."`) are EXCLUDED because
    they contain `{placeholder}` substitutions whose values are
    determined at C# runtime; silently returning their templates
    would feed bogus SQL to sqlite3 / pyodbc. Callers that need
    one of those must extract the SQL by another means (typically
    by hand-mirroring the C# logic in Python and applying the
    substitutions there).

    Callers can pick by index OR by keyword search; the source-order
    invariant matters for index-based picks against files that mix
    both styles, because raw-then-verbatim concatenation would
    misalign positional indices vs the actual file layout.

    Raises `FileNotFoundError` if `cs_path` doesn't exist.
    """
    if not cs_path.is_file():
        raise FileNotFoundError(f"C# source not found: {cs_path}")
    text = cs_path.read_text(encoding="utf-8")
    matches = list(_RAW_BLOCK.finditer(text)) + list(_VERBATIM_BLOCK.finditer(text))
    matches.sort(key=lambda m: m.start())
    return [m.group(1) for m in matches]


def find_sql_block(cs_path: Path, must_contain: str) -> str:
    """Return the unique SQL block in `cs_path` whose body contains the
    substring `must_contain` (case-sensitive). Used to pick a specific
    query out of a service with multiple SQL blocks.

    Raises `LookupError` if zero or more than one block matches — the
    caller is expected to provide a discriminating substring that
    isolates exactly one query.
    """
    matches = [b for b in extract_sql_blocks(cs_path) if must_contain in b]
    if not matches:
        raise LookupError(
            f"no SQL block in {cs_path} contains {must_contain!r}"
        )
    if len(matches) > 1:
        raise LookupError(
            f"{len(matches)} SQL blocks in {cs_path} contain {must_contain!r}; "
            f"pick a more specific discriminator"
        )
    return matches[0]
