"""Tests for cbdb_parity.datadump — archive discovery, SHA, streaming."""

from __future__ import annotations

import hashlib
import io
import os
import tarfile
import time
from pathlib import Path

import pytest

from cbdb_parity.datadump import (
    DatadumpError,
    find_latest_datadump,
    open_dump_stream,
)


def _make_archive(dest: Path, sql_bytes: bytes = b"-- tiny dump\n") -> None:
    """Build a minimal cbdb_data_*.tar.gz containing one cbdb_data.sql member."""
    with tarfile.open(dest, "w:gz") as tf:
        info = tarfile.TarInfo(name="cbdb_data.sql")
        info.size = len(sql_bytes)
        tf.addfile(info, io.BytesIO(sql_bytes))


def test_find_latest_picks_newest_by_date_tag(tmp_path: Path) -> None:
    for day in ("20260101", "20260615", "20260512"):
        _make_archive(tmp_path / f"cbdb_data_{day}.tar.gz")

    info = find_latest_datadump(tmp_path)
    assert info.date_tag == "20260615"
    assert info.filename == "cbdb_data_20260615.tar.gz"


def test_find_latest_ignores_non_matching_files(tmp_path: Path) -> None:
    _make_archive(tmp_path / "cbdb_data_20260101.tar.gz")
    # Decoys that must be ignored:
    (tmp_path / "data_cbdb_20190120.rar").write_bytes(b"x")
    (tmp_path / "gazetteer_20220104.7z").write_bytes(b"x")
    (tmp_path / "cbdb_data_20260201.tar").write_bytes(b"x")  # wrong ext
    (tmp_path / "cbdb_data_2026.tar.gz").write_bytes(b"x")  # bad date pattern
    (tmp_path / "TTS").mkdir()  # subdir

    info = find_latest_datadump(tmp_path)
    assert info.date_tag == "20260101"


def test_find_latest_uses_filename_not_mtime(tmp_path: Path) -> None:
    """An older-named file with a fresher mtime must still lose to a
    newer-named file with an older mtime — date-tag ordering, not OS time."""
    older_named = tmp_path / "cbdb_data_20251001.tar.gz"
    newer_named = tmp_path / "cbdb_data_20260601.tar.gz"
    _make_archive(newer_named)
    _make_archive(older_named)
    # Touch older-named to look newest by mtime; newer-named must still win.
    os.utime(older_named, (time.time() + 1000, time.time() + 1000))

    info = find_latest_datadump(tmp_path)
    assert info.date_tag == "20260601"


def test_find_latest_empty_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(DatadumpError, match="No cbdb_data_YYYYMMDD"):
        find_latest_datadump(tmp_path)


def test_find_latest_nonexistent_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(DatadumpError, match="not a directory"):
        find_latest_datadump(tmp_path / "nope")


def test_sha256_matches_hashlib(tmp_path: Path) -> None:
    archive = tmp_path / "cbdb_data_20260101.tar.gz"
    _make_archive(archive)
    info = find_latest_datadump(tmp_path)

    expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert info.sha256 == expected


def test_sha256_rehashes_on_every_call(tmp_path: Path) -> None:
    """No caching — every `.sha256` access re-reads the bytes. This is the
    intentional contract: cache keys for build artefacts must reflect the
    file's actual content right now, not a possibly-stale memoized value
    from a previous `find_latest_datadump` call within the same process.
    """
    archive = tmp_path / "cbdb_data_20260101.tar.gz"
    _make_archive(archive, sql_bytes=b"-- payload v1\n")
    info = find_latest_datadump(tmp_path)
    sha_v1 = info.sha256

    # Mutate the file behind the info object's back. Since DatadumpInfo
    # doesn't cache, the next .sha256 call must reflect the new content.
    archive.unlink()
    _make_archive(archive, sql_bytes=b"-- payload v2 (different bytes)\n")
    sha_v2 = info.sha256

    assert sha_v1 != sha_v2
    assert sha_v2 == hashlib.sha256(archive.read_bytes()).hexdigest()


def test_open_dump_stream_yields_full_sql_bytes(tmp_path: Path) -> None:
    payload = b"INSERT INTO `t` VALUES (1, 'hi');\n" * 5000
    archive = tmp_path / "cbdb_data_20260101.tar.gz"
    _make_archive(archive, payload)
    info = find_latest_datadump(tmp_path)

    with open_dump_stream(info) as f:
        got = f.read()
    assert got == payload


def test_open_dump_stream_supports_chunked_reading(tmp_path: Path) -> None:
    payload = b"x" * 1_000_000  # 1 MB
    archive = tmp_path / "cbdb_data_20260101.tar.gz"
    _make_archive(archive, payload)
    info = find_latest_datadump(tmp_path)

    collected = bytearray()
    with open_dump_stream(info) as f:
        while True:
            chunk = f.read(64 * 1024)
            if not chunk:
                break
            collected.extend(chunk)
    assert bytes(collected) == payload


def test_open_dump_stream_missing_member_raises(tmp_path: Path) -> None:
    archive = tmp_path / "cbdb_data_20260101.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        info = tarfile.TarInfo(name="WRONG_NAME.sql")
        data = b"-- nope\n"
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))

    found = find_latest_datadump(tmp_path)
    with pytest.raises(DatadumpError, match=r"cbdb_data\.sql"):
        with open_dump_stream(found) as _:
            pass


def test_datadump_info_is_frozen(tmp_path: Path) -> None:
    _make_archive(tmp_path / "cbdb_data_20260101.tar.gz")
    info = find_latest_datadump(tmp_path)
    with pytest.raises((AttributeError, TypeError)):
        info.date_tag = "20260102"  # type: ignore[misc]


def test_duplicate_date_tag_raises(tmp_path: Path) -> None:
    """Two archives sharing a date tag (impossible with the documented
    naming, but possible via ingestion error) must fail loud rather than
    silently pick whichever happens to win filesystem iteration order."""
    # Identical filenames on disk are impossible, so to exercise the
    # duplicate-detection branch we narrow _NAME_RE to capture only the
    # year — both YYYY are equal, so two real archives collide on date_tag.
    from cbdb_parity import datadump as dd_mod

    _make_archive(tmp_path / "cbdb_data_20260101.tar.gz")
    _make_archive(tmp_path / "cbdb_data_20260615.tar.gz")
    import re
    original = dd_mod._NAME_RE
    dd_mod._NAME_RE = re.compile(r"^cbdb_data_(\d{4})\d{4}\.tar\.gz$")
    try:
        with pytest.raises(DatadumpError, match="same date tag"):
            find_latest_datadump(tmp_path)
    finally:
        dd_mod._NAME_RE = original

    # Sanity: original regex → no duplicates → normal selection works
    info = find_latest_datadump(tmp_path)
    assert info.date_tag == "20260615"
