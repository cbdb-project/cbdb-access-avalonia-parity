"""Tests for cbdb_parity.avalonia_query_sql — SQL extractor from .cs files."""

from __future__ import annotations

from pathlib import Path

import pytest

from cbdb_parity.avalonia_query_sql import extract_sql_blocks, find_sql_block


def _write(tmp_path: Path, contents: str) -> Path:
    p = tmp_path / "Test.cs"
    p.write_text(contents, encoding="utf-8")
    return p


def test_extract_single_block(tmp_path: Path) -> None:
    cs = _write(tmp_path, '''
public class Foo {
    public void Run() {
        var sql = """
SELECT * FROM BIOG_MAIN
WHERE c_personid = 1;
""";
    }
}
''')
    blocks = extract_sql_blocks(cs)
    assert len(blocks) == 1
    assert "SELECT * FROM BIOG_MAIN" in blocks[0]
    assert "c_personid = 1" in blocks[0]


def test_extract_multiple_blocks_preserves_order(tmp_path: Path) -> None:
    cs = _write(tmp_path, '''
public class Foo {
    void A() {
        var sql1 = """
SELECT 1;
""";
    }
    void B() {
        var sql2 = """
SELECT 2;
""";
    }
}
''')
    blocks = extract_sql_blocks(cs)
    assert len(blocks) == 2
    assert "SELECT 1" in blocks[0]
    assert "SELECT 2" in blocks[1]


def test_extract_handles_embedded_double_quotes(tmp_path: Path) -> None:
    """A raw-string block can contain regular `"` — those must NOT
    confuse the extractor's `\"\"\"` boundary detection."""
    cs = _write(tmp_path, '''
var sql = """
SELECT * FROM t WHERE c_name LIKE "%foo%";
""";
''')
    blocks = extract_sql_blocks(cs)
    assert len(blocks) == 1
    assert 'LIKE "%foo%"' in blocks[0]


def test_extract_ignores_string_literals_with_only_one_quote(tmp_path: Path) -> None:
    """A regular C# string `"some literal"` is NOT a raw block; only
    triple-quoted bodies match."""
    cs = _write(tmp_path, '''
var ordinary = "just a regular string";
var sql = """
SELECT 42;
""";
''')
    blocks = extract_sql_blocks(cs)
    assert len(blocks) == 1
    assert "SELECT 42" in blocks[0]


def test_extract_empty_when_no_blocks(tmp_path: Path) -> None:
    cs = _write(tmp_path, "public class Foo { void Bar() {} }\n")
    assert extract_sql_blocks(cs) == []


def test_extract_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="C# source not found"):
        extract_sql_blocks(tmp_path / "nope.cs")


def test_find_sql_block_unique_match(tmp_path: Path) -> None:
    cs = _write(tmp_path, '''
var picker = """
SELECT c_entry_code FROM ENTRY_CODES;
""";
var query = """
WITH matched_people AS (SELECT 1)
SELECT * FROM ENTRY_DATA;
""";
''')
    block = find_sql_block(cs, "WITH matched_people")
    assert "WITH matched_people" in block
    assert "ENTRY_DATA" in block


def test_find_sql_block_no_match_raises(tmp_path: Path) -> None:
    cs = _write(tmp_path, '''
var sql = """SELECT 1;""";
''')
    with pytest.raises(LookupError, match="no SQL block"):
        find_sql_block(cs, "nonexistent")


def test_find_sql_block_multiple_matches_raises(tmp_path: Path) -> None:
    cs = _write(tmp_path, '''
var a = """
SELECT c_personid FROM A;
""";
var b = """
SELECT c_personid FROM B;
""";
''')
    with pytest.raises(LookupError, match="more specific discriminator"):
        find_sql_block(cs, "c_personid")


# ---------- real-file smoke ----------


def _avalonia_data_dir() -> Path:
    """Best-effort resolution of cbdb-desktop-app/Cbdb.App.Data; tests
    that need this skip cleanly if the external repo isn't present."""
    candidate = Path(
        r"C:\Users\how612\Documents\GitHub\cbdb-desktop-app\Cbdb.App.Data"
    )
    if not candidate.is_dir():
        pytest.skip(f"Avalonia data dir not present at {candidate}")
    return candidate


def test_extract_real_entry_query_service() -> None:
    """Smoke against the actual SqliteEntryQueryService.cs: confirms
    the regex catches the multi-block real source as written."""
    cs = _avalonia_data_dir() / "SqliteEntryQueryService.cs"
    if not cs.is_file():
        pytest.skip(f"{cs} not present")
    blocks = extract_sql_blocks(cs)
    # As of the pinned cbdb-desktop-app commit there are multiple raw-string
    # blocks (picker data, entry-type tree, relation map, the main QueryAsync
    # SQL, and the trailing ORDER BY/LIMIT tail).
    assert len(blocks) >= 4
    # The main query joins ENTRY_DATA + BIOG_MAIN + ENTRY_CODES.
    main_query = next(
        (b for b in blocks if "FROM ENTRY_DATA" in b and "JOIN BIOG_MAIN" in b),
        None,
    )
    assert main_query is not None, "main entry query not extracted"
    assert "$personKeyword" in main_query


def test_find_main_query_in_real_office_service() -> None:
    cs = _avalonia_data_dir() / "SqliteOfficeQueryService.cs"
    if not cs.is_file():
        pytest.skip(f"{cs} not present")
    # Use a discriminator that uniquely identifies the main QueryAsync
    # block (vs the picker-data block, which also touches POSTED_TO_OFFICE_DATA).
    blocks = [b for b in extract_sql_blocks(cs) if "POSTED_TO_OFFICE_DATA" in b]
    assert len(blocks) >= 1
    assert any("$personKeyword" in b for b in blocks), (
        "expected at least one main-query block parameterised on $personKeyword"
    )
