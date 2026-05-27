"""Streaming parser for CBDB Datadump SQL files.

A CBDB Datadump is a standard mysqldump output (~1.4 GB uncompressed):
DROP/CREATE TABLE statements followed by extended INSERT VALUES lines.
This parser reads the dump forward-only, yielding two event kinds:

    TableSchema(name, columns, create_sql)
    Row(table, values)

`columns` is the ordered list of `Column(name, sql_type)` extracted from
the CREATE TABLE definition; everything else (KEY, CONSTRAINT, ENGINE=…)
is preserved verbatim in `create_sql` so downstream emitters can re-issue
the schema or transform it for SQLite/Access.

Values come out as Python primitives:
    NULL         → None
    numbers      → int or float
    quoted text  → str (with MySQL escapes decoded: \\', \\\\, \\n, \\r, \\t, \\0)

Everything else (SET, comments, /*! ... */ blocks, USE, LOCK TABLES) is
silently skipped — those statements are mysqldump bookkeeping and never
appear as event kinds.

The parser is designed for the CBDB dump specifically. It does NOT aim to
handle every legal MySQL dialect; in particular it does not handle
hex-literal blobs (`0x…`), `_binary 'bytes'`, geometry types, or stored
procedures, because CBDB never emits them. If a future dump introduces a
shape the parser doesn't recognise, the test suite or the row-count
parity check (Phase 1.5) will catch it before silent data corruption
reaches the harness.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import IO

_CHUNK = 1 << 22  # 4 MB read window


def _has_unfinished_content(buf: bytes | bytearray) -> bool:
    """Return True if `buf` contains something other than comments,
    whitespace, and trailing semicolons.

    Used to decide whether an EOF with leftover bytes is a truncation
    error (real content) or harmless (only mysqldump trailer comments).
    """
    i = 0
    n = len(buf)
    while i < n:
        c = buf[i]
        if c in (0x20, 0x09, 0x0A, 0x0D, 0x3B):  # space, tab, LF, CR, ';'
            i += 1
            continue
        if c == 0x2D and i + 1 < n and buf[i + 1] == 0x2D:  # `--`
            nl = buf.find(b"\n", i + 2)
            if nl == -1:
                return False  # comment runs to EOF, harmless
            i = nl + 1
            continue
        if c == 0x2F and i + 1 < n and buf[i + 1] == 0x2A:  # `/*`
            end = buf.find(b"*/", i + 2)
            if end == -1:
                return True  # unterminated block comment is itself trash
            i = end + 2
            continue
        return True
    return False

_INSERT_HEAD = re.compile(rb"^\s*INSERT\s+INTO\s+`([^`]+)`\s+VALUES\s*", re.IGNORECASE)
_CREATE_HEAD = re.compile(rb"^\s*CREATE\s+TABLE\s+`([^`]+)`\s*\(", re.IGNORECASE)
_COLUMN_LINE = re.compile(
    rb"^\s*`([^`]+)`\s+([A-Za-z][A-Za-z0-9_]*(?:\([^)]*\))?)",
    re.MULTILINE,
)


class MysqlDumpError(RuntimeError):
    """Raised on a parse failure that indicates a real schema/value
    deviation from what CBDB's mysqldump output is supposed to look like.
    A bare error message during normal parsing should fail loud — the
    parity check downstream cannot recover from a silently-skipped row.
    """


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    sql_type: str  # e.g. "int(11)", "varchar(255)", "smallint(6)", "double"


@dataclass(frozen=True, slots=True)
class TableSchema:
    name: str
    columns: tuple[Column, ...]
    # Full CREATE TABLE body (between the outer parens, inclusive) so
    # downstream re-emitters can keep KEYs, COLLATION, etc.
    create_sql: bytes


@dataclass(frozen=True, slots=True)
class Row:
    table: str
    values: tuple[int | float | str | None, ...]


@dataclass(slots=True)
class _StatementBuffer:
    """Reads `stream` chunk by chunk and yields complete top-level
    statements (bytes), splitting on `;` that isn't inside a string
    literal or a parenthesised expression.

    Single-quoted strings honour MySQL backslash escapes: `\\'` is an
    escaped quote, not the end of the string.
    """

    stream: IO[bytes]
    _buf: bytearray = field(default_factory=bytearray)
    _eof: bool = False

    def __iter__(self) -> Iterator[bytes]:
        return self

    def __next__(self) -> bytes:
        while True:
            end = self._find_statement_end()
            if end is not None:
                stmt = bytes(self._buf[:end])
                del self._buf[: end + 1]  # drop trailing ';'
                return stmt
            if self._eof:
                # Anything left in the buffer that isn't blank means the
                # dump ended mid-statement (unterminated string / unbalanced
                # parens). Fail loud — silently swallowing is the worst
                # possible outcome for a 50M-row parser.
                if _has_unfinished_content(self._buf):
                    raise MysqlDumpError(
                        f"truncated dump: trailing bytes never terminated "
                        f"({len(self._buf)} chars left, starts with "
                        f"{bytes(self._buf[:60])!r})"
                    )
                raise StopIteration
            chunk = self.stream.read(_CHUNK)
            if not chunk:
                self._eof = True
            else:
                self._buf.extend(chunk)

    def _find_statement_end(self) -> int | None:
        """Return the index of the next top-level `;` in `self._buf`, or
        None if more bytes are needed.
        """
        buf = self._buf
        i = 0
        n = len(buf)
        depth = 0
        in_string = False
        while i < n:
            c = buf[i]
            if in_string:
                if c == 0x5C:  # backslash → consume next byte (escape)
                    i += 2
                    continue
                if c == 0x27:  # ' end of string
                    in_string = False
                i += 1
                continue
            if c == 0x27:  # ' begin string
                in_string = True
            elif c == 0x28:  # (
                depth += 1
            elif c == 0x29:  # )
                if depth > 0:
                    depth -= 1
            elif c == 0x3B and depth == 0:  # ;
                return i
            elif c == 0x2D and i + 1 < n and buf[i + 1] == 0x2D:
                # `-- comment` extends to end of line
                nl = buf.find(b"\n", i + 2)
                if nl == -1:
                    return None  # need more bytes
                i = nl + 1
                continue
            elif c == 0x2F and i + 1 < n and buf[i + 1] == 0x2A:
                # /* … */ block comment
                end = buf.find(b"*/", i + 2)
                if end == -1:
                    return None
                i = end + 2
                continue
            i += 1
        return None


def parse_dump(stream: IO[bytes]) -> Iterator[TableSchema | Row]:
    """Yield TableSchema and Row events from a CBDB Datadump stream.

    Streams forward-only; safe to consume bytes from a tarfile.r|gz handle.
    """
    schemas: dict[str, TableSchema] = {}
    for raw_stmt in _StatementBuffer(stream):
        # Strip leading comments + whitespace so a statement like
        #   `-- header\n/*!40101 ... */ CREATE TABLE ...`
        # still matches the CREATE/INSERT regexes (which anchor at start).
        # Without this, dump variants that omit DROP / SET separators
        # between a comment block and the next real statement would have
        # their schemas / rows silently swallowed.
        stmt = _strip_leading_noise(raw_stmt)
        if not stmt:
            continue
        m = _CREATE_HEAD.match(stmt)
        if m is not None:
            schema = _parse_create_table(stmt, m.group(1).decode("utf-8"))
            schemas[schema.name] = schema
            yield schema
            continue
        m = _INSERT_HEAD.match(stmt)
        if m is not None:
            table = m.group(1).decode("utf-8")
            tail = stmt[m.end() :]
            yield from _iter_insert_rows(table, tail)
            continue
        # If a statement *looks* like an INSERT but doesn't match the head
        # regex (e.g. `INSERT IGNORE INTO`, `INSERT INTO t (cols) VALUES`),
        # fail loud rather than silently drop rows — silent dropping is the
        # exact failure mode the parity harness is built to avoid.
        head = stmt[:6].upper()
        if head == b"INSERT":
            raise MysqlDumpError(
                f"INSERT-shaped statement did not match parser; refusing to "
                f"drop possible rows. statement starts: {stmt[:120]!r}"
            )
        # Anything else (SET, LOCK TABLES, USE, comments-only, etc.) is
        # mysqldump bookkeeping or out-of-scope for the parity harness.
        continue


def _strip_leading_noise(stmt: bytes) -> bytes:
    """Return `stmt` with any leading whitespace / `--` comment lines /
    `/* … */` block comments / executable-comment `/*! … */` blocks
    removed. The remainder is the first real SQL token onward, suitable
    for the anchored CREATE/INSERT head regexes.
    """
    i = 0
    n = len(stmt)
    while i < n:
        c = stmt[i]
        if c in (0x20, 0x09, 0x0A, 0x0D):  # whitespace
            i += 1
            continue
        if c == 0x2D and i + 1 < n and stmt[i + 1] == 0x2D:  # `--`
            nl = stmt.find(b"\n", i + 2)
            if nl == -1:
                return b""
            i = nl + 1
            continue
        if c == 0x2F and i + 1 < n and stmt[i + 1] == 0x2A:  # `/*` or `/*!`
            end = stmt.find(b"*/", i + 2)
            if end == -1:
                return b""
            i = end + 2
            continue
        break
    return stmt[i:]


def _parse_create_table(stmt: bytes, name: str) -> TableSchema:
    """Pull `Column(name, sql_type)` out of a CREATE TABLE statement.

    Strategy: locate the outer parens, then regex-scan each line that
    starts with a backticked identifier. Skip KEY/CONSTRAINT/UNIQUE/etc.
    by virtue of not matching the column regex.
    """
    open_paren = stmt.find(b"(")
    close_paren = stmt.rfind(b")")
    if open_paren == -1 or close_paren == -1 or close_paren <= open_paren:
        raise MysqlDumpError(f"CREATE TABLE `{name}`: cannot locate column block")
    body = stmt[open_paren + 1 : close_paren]
    columns: list[Column] = []
    for col_m in _COLUMN_LINE.finditer(body):
        col_name = col_m.group(1).decode("utf-8")
        col_type = col_m.group(2).decode("utf-8")
        columns.append(Column(name=col_name, sql_type=col_type))
    if not columns:
        raise MysqlDumpError(f"CREATE TABLE `{name}`: no columns found")
    return TableSchema(name=name, columns=tuple(columns), create_sql=stmt)


def _iter_insert_rows(table: str, tail: bytes) -> Iterator[Row]:
    """Yield Row objects from the VALUES portion of an INSERT statement.

    `tail` is everything after `INSERT INTO \\`TABLE\\` VALUES`, including
    the `(…),(…),(…)` row tuples. We split at `,` that's outside both
    parens AND strings, then tokenise each row.
    """
    i = 0
    n = len(tail)
    while i < n:
        # Skip whitespace and commas between row tuples.
        while i < n and tail[i] in (0x20, 0x09, 0x0A, 0x0D, 0x2C):
            i += 1
        if i >= n:
            break
        if tail[i] != 0x28:  # '('
            # Unexpected non-tuple content after the last parsed row —
            # could be `INSERT INTO t VALUES (1) BAD;` or a future variant
            # we don't recognise. Fail loud rather than emit a partial row
            # stream.
            raise MysqlDumpError(
                f"INSERT INTO `{table}`: unexpected trailing content after "
                f"VALUES tuples (starts at: {tail[i:i+60]!r})"
            )
        # Find the matching ')' at depth 1, honouring string escapes.
        j = i + 1
        depth = 1
        in_string = False
        while j < n:
            c = tail[j]
            if in_string:
                if c == 0x5C:
                    j += 2
                    continue
                if c == 0x27:
                    in_string = False
                j += 1
                continue
            if c == 0x27:
                in_string = True
            elif c == 0x28:
                depth += 1
            elif c == 0x29:
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if j >= n or depth != 0:
            raise MysqlDumpError(
                f"INSERT INTO `{table}`: unbalanced parens in VALUES tuple"
            )
        row_bytes = tail[i + 1 : j]
        values = _split_row(table, row_bytes)
        yield Row(table=table, values=tuple(values))
        i = j + 1


def _split_row(table: str, row: bytes) -> list[object]:
    """Tokenise the contents of a single (…) row tuple into Python values."""
    values: list[object] = []
    i = 0
    n = len(row)
    while i <= n:
        # Skip leading whitespace.
        while i < n and row[i] in (0x20, 0x09):
            i += 1
        if i >= n:
            # Trailing comma case: produce one empty token (rare but
            # legal in some dumps). Treat as NULL for safety.
            break
        # Determine the value's extent.
        if row[i] == 0x27:  # quoted string
            j = i + 1
            while j < n:
                c = row[j]
                if c == 0x5C:
                    j += 2
                    continue
                if c == 0x27:
                    break
                j += 1
            if j >= n:
                raise MysqlDumpError(
                    f"INSERT INTO `{table}`: unterminated string in row"
                )
            values.append(_decode_string(row[i + 1 : j]))
            i = j + 1
        else:
            j = i
            while j < n and row[j] != 0x2C:
                j += 1
            tok = row[i:j].strip()
            values.append(_decode_scalar(tok))
            i = j
        # Skip past the comma separator if present.
        while i < n and row[i] in (0x20, 0x09):
            i += 1
        if i < n and row[i] == 0x2C:
            i += 1
    return values


# MySQL string escape sequences emitted by mysqldump (--hex-blob disabled).
# `%` and `_` are NOT in this set: mysqldump never emits `\%` or `\_` — those
# are LIKE-pattern escapes used in hand-authored SQL, not in dumped data.
_ESCAPE = {
    ord("0"): b"\x00",
    ord("'"): b"'",
    ord('"'): b'"',
    ord("b"): b"\x08",
    ord("n"): b"\n",
    ord("r"): b"\r",
    ord("t"): b"\t",
    ord("Z"): b"\x1a",
    ord("\\"): b"\\",
}


def _decode_string(raw: bytes) -> str:
    """Decode a MySQL-escaped UTF-8 byte run back into a Python string.

    Strict UTF-8: any byte sequence that isn't valid UTF-8 raises
    MysqlDumpError. CBDB is exclusively UTF-8 so this should never fire;
    if it does, that's a sign the dump itself is corrupt and the parity
    harness must not silently truck on with replaced characters.
    """
    out = bytearray()
    i = 0
    n = len(raw)
    while i < n:
        c = raw[i]
        if c == 0x5C and i + 1 < n:
            nxt = raw[i + 1]
            mapped = _ESCAPE.get(nxt)
            if mapped is not None:
                out.extend(mapped)
            else:
                # Unknown escape: MySQL would emit the byte as-is.
                out.append(nxt)
            i += 2
            continue
        out.append(c)
        i += 1
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MysqlDumpError(
            f"non-UTF-8 bytes in string value: {bytes(out[:80])!r}"
        ) from exc


def _decode_scalar(tok: bytes) -> int | float | None:
    """Decode a bare (unquoted) value: NULL, int, or float.

    Any unquoted token that isn't NULL/int/float raises — mysqldump never
    emits bare identifiers as VALUES, and silently smuggling such a token
    through as text would push the wrong type into the destination DBs.
    """
    if not tok:
        return None
    if tok == b"NULL" or tok == b"null":
        return None
    try:
        return int(tok)
    except ValueError:
        pass
    try:
        return float(tok)
    except ValueError:
        pass
    raise MysqlDumpError(
        f"unexpected unquoted token in VALUES: {tok!r} "
        f"(expected NULL / integer / float)"
    )
