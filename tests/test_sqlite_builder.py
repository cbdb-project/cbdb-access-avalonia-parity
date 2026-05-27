"""Tests for cbdb_parity.sqlite_builder — Datadump → cbdb.sqlite."""

from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pytest

from cbdb_parity.mysqldump import Column, TableSchema
from cbdb_parity.sqlite_builder import (
    _create_table_sql,
    build_sqlite,
    mysql_type_to_sqlite,
)

# ---------- type mapping ----------

@pytest.mark.parametrize(
    "mysql_type, expected",
    [
        ("int(11)", "INTEGER"),
        ("smallint(6)", "INTEGER"),
        ("bigint(20)", "INTEGER"),
        ("BIGINT", "INTEGER"),
        ("varchar(255)", "TEXT"),
        ("VARCHAR(10)", "TEXT"),
        ("text", "TEXT"),
        ("longtext", "TEXT"),
        ("mediumtext", "TEXT"),
        ("tinytext", "TEXT"),
        ("char(10)", "TEXT"),
        ("double", "REAL"),
        ("float", "REAL"),
        ("decimal(10,2)", "NUMERIC"),
        ("decimal(8,4)", "NUMERIC"),
        ("date", "TEXT"),
        ("datetime", "TEXT"),
        ("timestamp", "TEXT"),
        ("time", "TEXT"),
        ("enum('a','b')", "TEXT"),
        ("set('x','y')", "TEXT"),
        ("varbinary(100)", "BLOB"),
        ("binary(16)", "BLOB"),
    ],
)
def test_mysql_type_to_sqlite_known_types(mysql_type: str, expected: str) -> None:
    assert mysql_type_to_sqlite(mysql_type) == expected


@pytest.mark.parametrize("sqlite_type", ["INTEGER", "TEXT", "REAL", "NUMERIC", "BLOB"])
def test_mysql_type_to_sqlite_is_idempotent(sqlite_type: str) -> None:
    """Running the mapper twice on the same input must equal running it
    once — a fix-point property the type tokens already satisfy by virtue
    of not appearing in any source pattern."""
    once = mysql_type_to_sqlite(sqlite_type)
    twice = mysql_type_to_sqlite(once)
    assert once == twice == sqlite_type


def test_create_table_sql_quotes_identifiers() -> None:
    sch = TableSchema(
        name="ADDRESSES",
        columns=(Column("c_addr_id", "int(11)"), Column("c_name", "varchar(255)")),
        create_sql=b"",
    )
    sql = _create_table_sql(sch)
    assert '"ADDRESSES"' in sql
    assert '"c_addr_id" INTEGER' in sql
    assert '"c_name" TEXT' in sql
    # SQLite should accept it.
    conn = sqlite3.connect(":memory:")
    conn.execute(sql)
    conn.close()


# ---------- end-to-end build ----------

def _build(sql_bytes: bytes, tmp_path: Path, **kwargs: object) -> tuple[Path, object]:
    out = tmp_path / "out.sqlite"
    stats = build_sqlite(io.BytesIO(sql_bytes), out, **kwargs)  # type: ignore[arg-type]
    return out, stats


def test_build_creates_table_and_inserts_rows(tmp_path: Path) -> None:
    dump = (
        b"CREATE TABLE `t` (`id` int(11), `name` varchar(50), `score` double);"
        b"INSERT INTO `t` VALUES (1,'a',3.14),(2,'b',NULL),(3,'c',2.5);"
    )
    out, stats = _build(dump, tmp_path)
    assert stats.tables_created == 1
    assert stats.rows_inserted == 3

    conn = sqlite3.connect(out)
    rows = conn.execute('SELECT id, name, score FROM "t" ORDER BY id').fetchall()
    conn.close()
    assert rows == [(1, "a", 3.14), (2, "b", None), (3, "c", 2.5)]


def test_build_skips_internal_tables_by_default(tmp_path: Path) -> None:
    dump = (
        b"CREATE TABLE `BIOG_MAIN` (`id` int(11));"
        b"INSERT INTO `BIOG_MAIN` VALUES (1),(2);"
        b"CREATE TABLE `CBDB__internal_thing` (`x` int(11));"
        b"INSERT INTO `CBDB__internal_thing` VALUES (99);"
    )
    out, stats = _build(dump, tmp_path)
    assert stats.tables_created == 1
    assert stats.rows_inserted == 2
    assert stats.tables_skipped == ["CBDB__internal_thing"]
    conn = sqlite3.connect(out)
    names = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    ]
    conn.close()
    assert "BIOG_MAIN" in names
    assert "CBDB__internal_thing" not in names


def test_build_includes_internal_when_opted_in(tmp_path: Path) -> None:
    dump = (
        b"CREATE TABLE `CBDB__a` (`x` int(11));"
        b"INSERT INTO `CBDB__a` VALUES (42);"
    )
    out, stats = _build(dump, tmp_path, with_internal=True)
    assert stats.tables_created == 1
    assert stats.rows_inserted == 1
    conn = sqlite3.connect(out)
    val = conn.execute('SELECT x FROM "CBDB__a"').fetchone()[0]
    conn.close()
    assert val == 42


def test_build_preserves_unicode(tmp_path: Path) -> None:
    dump = "CREATE TABLE `t` (`name` varchar(255));INSERT INTO `t` VALUES ('中華人民共和國');".encode()
    out, _ = _build(dump, tmp_path)
    conn = sqlite3.connect(out)
    val = conn.execute('SELECT name FROM "t"').fetchone()[0]
    conn.close()
    assert val == "中華人民共和國"


def test_build_handles_multi_table_dump(tmp_path: Path) -> None:
    dump = (
        b"CREATE TABLE `a` (`x` int(11));"
        b"INSERT INTO `a` VALUES (1),(2);"
        b"CREATE TABLE `b` (`s` varchar(10));"
        b"INSERT INTO `b` VALUES ('hi'),('bye');"
    )
    out, stats = _build(dump, tmp_path)
    assert stats.tables_created == 2
    assert stats.rows_inserted == 4
    conn = sqlite3.connect(out)
    a = conn.execute('SELECT x FROM "a" ORDER BY x').fetchall()
    b = conn.execute('SELECT s FROM "b" ORDER BY s').fetchall()
    conn.close()
    assert a == [(1,), (2,)]
    assert b == [("bye",), ("hi",)]


def test_build_overwrites_existing_file(tmp_path: Path) -> None:
    out = tmp_path / "out.sqlite"
    out.write_bytes(b"\x00" * 100)  # garbage from a previous run
    dump = b"CREATE TABLE `t` (`x` int(11));INSERT INTO `t` VALUES (1);"
    build_sqlite(io.BytesIO(dump), out)
    conn = sqlite3.connect(out)
    val = conn.execute('SELECT x FROM "t"').fetchone()[0]
    conn.close()
    assert val == 1


def test_build_row_before_schema_raises(tmp_path: Path) -> None:
    """An INSERT for a table we never saw a CREATE for must NOT be
    silently dropped — it indicates dump-stream corruption."""
    dump = b"INSERT INTO `orphan` VALUES (1);"
    out = tmp_path / "out.sqlite"
    with pytest.raises(RuntimeError, match=r"before its CREATE TABLE"):
        build_sqlite(io.BytesIO(dump), out)


def test_manifest_written_with_datadump_provenance(tmp_path: Path) -> None:
    """Standalone `cbdb-parity-build-sqlite` runs must leave a
    build_manifest.json that pins cbdb.sqlite to a specific Datadump SHA."""
    import json

    from cbdb_parity.datadump import DatadumpInfo
    from cbdb_parity.sqlite_builder import BuildStats, _write_manifest

    manifest = tmp_path / "build_manifest.json"
    archive = tmp_path / "cbdb_data_20260101.tar.gz"
    archive.write_bytes(b"fake archive")  # SHA computed off-band
    info = DatadumpInfo(path=archive, date_tag="20260101")
    stats = BuildStats(tables_created=3, rows_inserted=42, tables_skipped=["CBDB__x"])
    _write_manifest(manifest, info, "deadbeef" * 8, tmp_path / "cbdb.sqlite", stats, 12.3)

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["datadump"]["filename"] == "cbdb_data_20260101.tar.gz"
    assert payload["datadump"]["sha256"] == "deadbeef" * 8
    assert payload["products"]["sqlite"]["tables_created"] == 3
    assert payload["products"]["sqlite"]["rows_inserted"] == 42
    assert payload["products"]["sqlite"]["tables_skipped"] == ["CBDB__x"]


def test_manifest_preserves_sibling_product_when_sha_matches(tmp_path: Path) -> None:
    """When the mdb was built from the SAME Datadump SHA, the sqlite
    builder must merge into the manifest alongside, not clobber the mdb."""
    import json

    from cbdb_parity.datadump import DatadumpInfo
    from cbdb_parity.sqlite_builder import BuildStats, _write_manifest

    SAME_SHA = "abc123" * 10
    manifest = tmp_path / "build_manifest.json"
    manifest.write_text(json.dumps({
        "version": 1,
        "datadump": {"filename": "X.tar.gz", "sha256": SAME_SHA, "date_tag": "20260101"},
        "products": {"mdb": {"path": "/x/cbdb_data.mdb", "rows": 100}},
    }), encoding="utf-8")

    archive = tmp_path / "cbdb_data_20260101.tar.gz"
    archive.write_bytes(b"fake")
    info = DatadumpInfo(path=archive, date_tag="20260101")
    stats = BuildStats(tables_created=1, rows_inserted=1, tables_skipped=[])
    _write_manifest(manifest, info, SAME_SHA, tmp_path / "cbdb.sqlite", stats, 1.0)

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert "mdb" in payload["products"]
    assert payload["products"]["mdb"]["rows"] == 100
    assert "sqlite" in payload["products"]


def test_manifest_clears_stale_sibling_when_sha_changes(tmp_path: Path) -> None:
    """Invariant: every `products` entry came from the manifest's top-level
    Datadump SHA. If the SHA changes, sibling products from the OLD dump
    are stale and must be discarded — otherwise downstream reports would
    falsely tie mdb to the new sqlite's data."""
    import json

    from cbdb_parity.datadump import DatadumpInfo
    from cbdb_parity.sqlite_builder import BuildStats, _write_manifest

    manifest = tmp_path / "build_manifest.json"
    manifest.write_text(json.dumps({
        "version": 1,
        "datadump": {"filename": "old.tar.gz", "sha256": "oldsha", "date_tag": "20260101"},
        "products": {"mdb": {"path": "/x/cbdb_data.mdb", "rows": 100}},
    }), encoding="utf-8")

    archive = tmp_path / "cbdb_data_20260601.tar.gz"
    archive.write_bytes(b"fake")
    info = DatadumpInfo(path=archive, date_tag="20260601")
    stats = BuildStats(tables_created=1, rows_inserted=1, tables_skipped=[])
    _write_manifest(manifest, info, "newsha", tmp_path / "cbdb.sqlite", stats, 1.0)

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    # mdb from the OLD dump must be gone; only sqlite from the new dump remains.
    assert "mdb" not in payload["products"]
    assert "sqlite" in payload["products"]
    assert payload["datadump"]["sha256"] == "newsha"


def test_build_handles_cross_table_interleaving(tmp_path: Path) -> None:
    """mysqldump can re-emit INSERT for an earlier table after another
    table appears. The builder must flush and re-aim, not drop rows."""
    dump = (
        b"CREATE TABLE `a` (`x` int(11));"
        b"INSERT INTO `a` VALUES (1);"
        b"CREATE TABLE `b` (`x` int(11));"
        b"INSERT INTO `b` VALUES (10);"
        b"INSERT INTO `a` VALUES (2);"  # back to table `a`
        b"INSERT INTO `b` VALUES (20);"
    )
    out, stats = _build(dump, tmp_path)
    assert stats.rows_inserted == 4
    conn = sqlite3.connect(out)
    a = sorted(r[0] for r in conn.execute('SELECT x FROM "a"'))
    b = sorted(r[0] for r in conn.execute('SELECT x FROM "b"'))
    conn.close()
    assert a == [1, 2]
    assert b == [10, 20]
