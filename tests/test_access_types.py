"""Tests for cbdb_parity.access_types — MySQL → Access type rewriter."""

from __future__ import annotations

import pytest

from cbdb_parity.access_types import mysql_type_to_access


@pytest.mark.parametrize(
    "mysql_type, expected",
    [
        # Integer family
        ("int(11)", "INTEGER"),
        ("INT(11)", "INTEGER"),
        ("int", "INTEGER"),
        ("smallint(6)", "SMALLINT"),
        ("smallint", "SMALLINT"),
        ("mediumint(8)", "INTEGER"),
        ("bigint(20)", "INTEGER"),
        ("bigint", "INTEGER"),
        ("tinyint(4)", "SMALLINT"),
        ("tinyint", "SMALLINT"),
        # tinyint(1) is the MySQL bool convention; README §3 → SMALLINT
        ("tinyint(1)", "SMALLINT"),
        # Floats
        ("double", "DOUBLE"),
        ("float", "DOUBLE"),
        ("decimal(10,2)", "DOUBLE"),
        ("numeric(8,4)", "DOUBLE"),
        # Text
        ("varchar(255)", "VARCHAR(255)"),
        ("VARCHAR(10)", "VARCHAR(10)"),
        ("varchar(191)", "VARCHAR(191)"),
        ("char(10)", "VARCHAR(10)"),
        ("text", "LONGTEXT"),
        ("longtext", "LONGTEXT"),
        ("mediumtext", "LONGTEXT"),
        ("tinytext", "VARCHAR(255)"),
        # Date/time — all collapse to Access DATETIME
        ("date", "DATETIME"),
        ("datetime", "DATETIME"),
        ("timestamp", "DATETIME"),
        ("time", "DATETIME"),
        # Enum/Set
        ("enum('a','b')", "LONGTEXT"),
        ("set('x','y','z')", "LONGTEXT"),
        # Binary
        ("varbinary(100)", "LONGBINARY"),
        ("binary(16)", "LONGBINARY"),
        ("blob", "LONGBINARY"),
        ("longblob", "LONGBINARY"),
        ("mediumblob", "LONGBINARY"),
        ("tinyblob", "LONGBINARY"),
        # BIT — README §3 quirk
        ("bit", "SMALLINT"),
        ("bit(1)", "SMALLINT"),
    ],
)
def test_mysql_type_to_access_known_types(mysql_type: str, expected: str) -> None:
    assert mysql_type_to_access(mysql_type) == expected


@pytest.mark.parametrize(
    "access_type",
    ["INTEGER", "SMALLINT", "DOUBLE", "VARCHAR(255)", "LONGTEXT", "DATETIME", "LONGBINARY"],
)
def test_mysql_type_to_access_idempotent_on_already_translated_types(
    access_type: str,
) -> None:
    """Running the mapper on its own output must equal running it once —
    the Access-side type tokens shouldn't accidentally match any of the
    source-side patterns."""
    once = mysql_type_to_access(access_type)
    twice = mysql_type_to_access(once)
    assert once == twice == access_type


def test_bit_is_not_misclassified_as_blob() -> None:
    """The README §3 caveat: if BIT were mishandled (e.g. matched by a
    BINARY pattern), Access turns every value into 1. SMALLINT is the
    safe choice."""
    assert mysql_type_to_access("bit") == "SMALLINT"
    assert mysql_type_to_access("BIT(1)") == "SMALLINT"
    # Not LONGBINARY.
    assert "BINARY" not in mysql_type_to_access("bit")


def test_int_does_not_match_bigint() -> None:
    """`\\bINT\\b` must not eat the INT inside BIGINT during normalisation."""
    assert mysql_type_to_access("bigint(20)") == "INTEGER"
    assert mysql_type_to_access("bigint") == "INTEGER"


def test_varchar_size_preserved() -> None:
    """VARCHAR(N) keeps its width — important because README §1 says we
    may need to downsize 255→191 manually for utf8mb4 row-size issues."""
    assert mysql_type_to_access("varchar(255)") == "VARCHAR(255)"
    assert mysql_type_to_access("varchar(191)") == "VARCHAR(191)"
    assert mysql_type_to_access("varchar(50)") == "VARCHAR(50)"
    assert mysql_type_to_access("varchar(1)") == "VARCHAR(1)"


def test_char_translates_to_varchar() -> None:
    """Access has no fixed-length CHAR; everything becomes VARCHAR(N)."""
    assert mysql_type_to_access("char(10)") == "VARCHAR(10)"
    assert mysql_type_to_access("CHAR(1)") == "VARCHAR(1)"


def test_unknown_type_passed_through_stripped() -> None:
    """A token we don't recognise round-trips unchanged (after strip).
    The mdb builder will then fail at CREATE TABLE if Access can't
    accept it — fail-loud, not silent fallback."""
    assert mysql_type_to_access("WEIRD_TYPE") == "WEIRD_TYPE"
    assert mysql_type_to_access("  WEIRD_TYPE  ") == "WEIRD_TYPE"


def test_text_variant_priority() -> None:
    """LONGTEXT/MEDIUMTEXT/TEXT should ALL map to Access LONGTEXT; the
    specific MySQL flavour is collapsed."""
    assert mysql_type_to_access("longtext") == "LONGTEXT"
    assert mysql_type_to_access("mediumtext") == "LONGTEXT"
    assert mysql_type_to_access("text") == "LONGTEXT"
    # TINYTEXT is small enough to fit in VARCHAR — kept distinct.
    assert mysql_type_to_access("tinytext") == "VARCHAR(255)"
