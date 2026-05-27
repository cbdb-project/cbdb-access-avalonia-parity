"""Tests for cbdb_parity.mysqldump — the streaming dump parser."""

from __future__ import annotations

import io

import pytest

from cbdb_parity.mysqldump import (
    Column,
    MysqlDumpError,
    Row,
    TableSchema,
    parse_dump,
)


def _stream(s: str | bytes) -> io.BytesIO:
    if isinstance(s, str):
        s = s.encode("utf-8")
    return io.BytesIO(s)


# ---------- CREATE TABLE ----------

def test_parse_create_table_minimal() -> None:
    sql = b"""CREATE TABLE `t` (
  `id` int(11) NOT NULL,
  `name` varchar(255) DEFAULT NULL
);"""
    events = list(parse_dump(_stream(sql)))
    assert len(events) == 1
    sch = events[0]
    assert isinstance(sch, TableSchema)
    assert sch.name == "t"
    assert sch.columns == (
        Column("id", "int(11)"),
        Column("name", "varchar(255)"),
    )


def test_parse_create_table_skips_key_constraint_lines() -> None:
    sql = b"""CREATE TABLE `t` (
  `id` int(11) NOT NULL,
  `name` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `name_idx` (`name`),
  CONSTRAINT `fk` FOREIGN KEY (`id`) REFERENCES `u`(`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"""
    events = list(parse_dump(_stream(sql)))
    assert len(events) == 1
    sch = events[0]
    assert [c.name for c in sch.columns] == ["id", "name"]


def test_parse_create_table_with_chinese_comments_and_collations() -> None:
    # Modelled on real CBDB CREATE TABLE rows.
    sql = b"""CREATE TABLE `ADDRESSES` (
  `c_addr_id` int(11) DEFAULT NULL COMMENT 'Address ID',
  `c_name_chn` varchar(255) DEFAULT NULL COMMENT 'Chinese address name',
  `c_admin_type` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  KEY `idx` (`c_addr_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci ROW_FORMAT=DYNAMIC;"""
    events = list(parse_dump(_stream(sql)))
    sch = events[0]
    assert isinstance(sch, TableSchema)
    assert sch.name == "ADDRESSES"
    names = [c.name for c in sch.columns]
    assert names == ["c_addr_id", "c_name_chn", "c_admin_type"]


def test_create_table_with_no_columns_raises() -> None:
    sql = b"""CREATE TABLE `t` (
  PRIMARY KEY (`id`)
);"""
    with pytest.raises(MysqlDumpError, match="no columns found"):
        list(parse_dump(_stream(sql)))


# ---------- INSERT ROWS ----------

def test_parse_insert_basic_row() -> None:
    sql = b"INSERT INTO `t` VALUES (1, 'hello', NULL, 3.14);"
    events = list(parse_dump(_stream(sql)))
    assert events == [Row(table="t", values=(1, "hello", None, 3.14))]


def test_parse_insert_multi_row_extended() -> None:
    sql = (
        b"INSERT INTO `t` VALUES "
        b"(1,'a',NULL),"
        b"(2,'b',NULL),"
        b"(3,'c',42);"
    )
    rows = list(parse_dump(_stream(sql)))
    assert rows == [
        Row("t", (1, "a", None)),
        Row("t", (2, "b", None)),
        Row("t", (3, "c", 42)),
    ]


def test_parse_insert_escape_sequences() -> None:
    # \' \\ \n \t \0 — all need to round-trip
    sql = b"INSERT INTO `t` VALUES (1, 'O\\'Hara\\nNext\\tTab\\\\back\\0');"
    rows = list(parse_dump(_stream(sql)))
    assert len(rows) == 1
    assert rows[0].values[1] == "O'Hara\nNext\tTab\\back\x00"


def test_parse_insert_chinese_string() -> None:
    sql = "INSERT INTO `t` VALUES (1,'中華人民共和國','北京省市');".encode()
    rows = list(parse_dump(_stream(sql)))
    assert rows[0].values == (1, "中華人民共和國", "北京省市")


def test_parse_insert_string_containing_paren_and_semicolon() -> None:
    """Don't terminate the statement on `;` or `)` inside a string."""
    sql = b"INSERT INTO `t` VALUES (1, 'a; b', '(paren)', 'end);'),(2,'x','y','z');"
    rows = list(parse_dump(_stream(sql)))
    assert rows == [
        Row("t", (1, "a; b", "(paren)", "end);")),
        Row("t", (2, "x", "y", "z")),
    ]


def test_parse_insert_negative_numbers_and_floats() -> None:
    sql = b"INSERT INTO `t` VALUES (-1, -3.14, 1e9, 0.5, NULL);"
    rows = list(parse_dump(_stream(sql)))
    assert rows[0].values == (-1, -3.14, 1_000_000_000.0, 0.5, None)


def test_parse_insert_quoted_dates() -> None:
    # mysqldump emits dates as quoted strings.
    sql = b"INSERT INTO `t` VALUES ('2024-01-15', '2024-01-15 12:30:00');"
    rows = list(parse_dump(_stream(sql)))
    assert rows[0].values == ("2024-01-15", "2024-01-15 12:30:00")


def test_unterminated_string_raises() -> None:
    """Unterminated string at EOF surfaces as a 'truncated dump' error
    at the statement-buffer level — that's the first place we can detect
    the deviation, and the message names the offending byte run."""
    sql = b"INSERT INTO `t` VALUES (1, 'oops);"
    with pytest.raises(MysqlDumpError, match="truncated dump"):
        list(parse_dump(_stream(sql)))


def test_unbalanced_parens_raises() -> None:
    """Unbalanced row-tuple parens leave the statement-buffer waiting for
    the outer `;`, which never comes; same 'truncated dump' signal."""
    sql = b"INSERT INTO `t` VALUES (1, 'a' "  # no `;`, no closing `)`
    with pytest.raises(MysqlDumpError, match="truncated dump"):
        list(parse_dump(_stream(sql)))


# ---------- mysqldump bookkeeping ----------

def test_parser_skips_set_use_lock_and_comments() -> None:
    sql = b"""-- header comment
/*!40101 SET NAMES utf8mb4 */;
USE `cbdb_data`;
LOCK TABLES `t` WRITE;
CREATE TABLE `t` (
  `id` int(11) NOT NULL
);
INSERT INTO `t` VALUES (1),(2);
UNLOCK TABLES;
/* trailing block */
"""
    events = list(parse_dump(_stream(sql)))
    assert len(events) == 3  # 1 schema + 2 rows
    assert isinstance(events[0], TableSchema)
    assert events[1] == Row("t", (1,))
    assert events[2] == Row("t", (2,))


def test_parser_handles_multi_table_mixed_stream() -> None:
    sql = b"""CREATE TABLE `a` (`id` int(11));
INSERT INTO `a` VALUES (1),(2);
CREATE TABLE `b` (`x` varchar(10));
INSERT INTO `b` VALUES ('hi'),('there');
INSERT INTO `a` VALUES (3);"""
    events = list(parse_dump(_stream(sql)))
    schemas = [e for e in events if isinstance(e, TableSchema)]
    rows = [e for e in events if isinstance(e, Row)]
    assert [s.name for s in schemas] == ["a", "b"]
    assert rows == [
        Row("a", (1,)),
        Row("a", (2,)),
        Row("b", ("hi",)),
        Row("b", ("there",)),
        Row("a", (3,)),
    ]


# ---------- chunk-boundary robustness ----------

def test_parse_works_with_tiny_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the buffer to refill many times; statement boundaries must
    still be detected correctly when a chunk lands mid-string or
    mid-statement."""
    import cbdb_parity.mysqldump as mod
    monkeypatch.setattr(mod, "_CHUNK", 7)  # absurdly small

    # mysqldump escapes embedded quotes as `\'`, not the SQL-standard `''`.
    sql = (
        b"CREATE TABLE `t` (`id` int(11), `s` varchar(50));\n"
        b"INSERT INTO `t` VALUES (1,'a; b'),(2,'c,d'),(3,'e\\'f');"
    )
    events = list(parse_dump(_stream(sql)))
    rows = [e for e in events if isinstance(e, Row)]
    assert rows == [
        Row("t", (1, "a; b")),
        Row("t", (2, "c,d")),
        Row("t", (3, "e'f")),
    ]


def test_parse_empty_stream() -> None:
    assert list(parse_dump(_stream(b""))) == []


def test_parse_only_comments_and_whitespace() -> None:
    sql = b"""
-- nothing here
/* still nothing */
   ;
"""
    # The lone `;` is a no-op statement; should yield nothing.
    assert list(parse_dump(_stream(sql))) == []


# ---------- explicit fail-loud paths ----------

def test_insert_shaped_statement_that_doesnt_match_raises() -> None:
    """An INSERT-shaped statement that doesn't match `INSERT INTO \\`t\\` VALUES`
    must fail loud rather than silently drop the row. Silent dropping is
    the worst failure mode for parity testing."""
    sql = b"INSERT IGNORE INTO `t` VALUES (1, 'a');"
    with pytest.raises(MysqlDumpError, match=r"INSERT-shaped statement did not match"):
        list(parse_dump(_stream(sql)))


def test_create_table_with_decimal_and_enum_types() -> None:
    """Real MySQL column types include `decimal(10,2)` and `enum('a','b')`
    — both have characters inside the type that the regex must not stop
    on (comma in decimal, single quotes in enum)."""
    sql = b"""CREATE TABLE `t` (
  `price` decimal(10,2) DEFAULT NULL,
  `kind` enum('small','large') DEFAULT NULL,
  `note` text
);"""
    events = list(parse_dump(_stream(sql)))
    assert len(events) == 1
    sch = events[0]
    assert isinstance(sch, TableSchema)
    names = [c.name for c in sch.columns]
    types = [c.sql_type for c in sch.columns]
    assert names == ["price", "kind", "note"]
    # The regex captures the type-head + first parens; both are acceptable
    # so long as the column NAMES round-trip and we don't drop the column.
    assert types[0].startswith("decimal")
    assert types[1].startswith("enum")
    assert types[2] == "text"


def test_parse_scientific_notation_floats() -> None:
    """mysqldump may emit 1.5e-7, 1.0E+10, etc. for floating point columns."""
    sql = b"INSERT INTO `t` VALUES (1.5e-7, 1.0E+10, -2.5e3);"
    rows = list(parse_dump(_stream(sql)))
    assert rows[0].values == (1.5e-7, 1.0e10, -2500.0)


def test_decode_scalar_rejects_garbage_token() -> None:
    """Bare identifiers in VALUES (`FOO`, `BAR`) aren't valid mysqldump
    output; smuggling them through as strings would push the wrong type
    into Phase 1.2/1.3 destinations."""
    sql = b"INSERT INTO `t` VALUES (1, NOTAVALUE);"
    with pytest.raises(MysqlDumpError, match=r"unexpected unquoted token"):
        list(parse_dump(_stream(sql)))


def test_leading_comments_before_create_table_still_yields_schema() -> None:
    """A CREATE TABLE preceded by `--` line comments + a `/*! ... */`
    executable comment block, with NO `;` between the comment and the
    CREATE, must still yield a TableSchema. Otherwise certain mysqldump
    variants would silently drop schemas / rows."""
    sql = (
        b"-- Table structure for `t`\n"
        b"-- Another header line\n"
        b"/*!40101 SET character_set_client = utf8mb4 */ "
        b"CREATE TABLE `t` (\n"
        b"  `id` int(11) NOT NULL\n"
        b");"
    )
    events = list(parse_dump(_stream(sql)))
    assert len(events) == 1
    assert isinstance(events[0], TableSchema)
    assert events[0].name == "t"


def test_leading_comments_before_insert_still_yields_rows() -> None:
    """Same as above but for an INSERT with attached leading comments."""
    sql = (
        b"-- Dumping data for `t`\n"
        b"/*!40000 ALTER TABLE `t` DISABLE KEYS */ "
        b"INSERT INTO `t` VALUES (1, 'a'),(2, 'b');"
    )
    rows = [e for e in parse_dump(_stream(sql)) if isinstance(e, Row)]
    assert rows == [Row("t", (1, "a")), Row("t", (2, "b"))]


def test_trailing_garbage_after_values_raises() -> None:
    """`INSERT INTO t VALUES (1) BAD;` must fail rather than silently
    yielding row (1,) and dropping the BAD trailer."""
    sql = b"INSERT INTO `t` VALUES (1) BAD;"
    with pytest.raises(MysqlDumpError, match=r"unexpected trailing content"):
        list(parse_dump(_stream(sql)))


def test_non_utf8_bytes_in_string_raises() -> None:
    """A non-UTF8 byte sequence inside a quoted string is treated as a
    real signal of dump corruption — fail loud, don't replace silently."""
    # 0xFF 0xFE is not valid UTF-8 leading byte sequence in this context.
    sql = b"INSERT INTO `t` VALUES (1, '\xff\xfe\xfd');"
    with pytest.raises(MysqlDumpError, match=r"non-UTF-8 bytes"):
        list(parse_dump(_stream(sql)))
