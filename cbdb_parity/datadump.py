"""Datadump archive discovery, SHA hashing, and streaming reader.

The harness ingests `cbdb_data_YYYYMMDD.tar.gz` archives that each contain
a single `cbdb_data.sql` (~1.4 GB uncompressed mysqldump). We never extract
to disk — `open_dump_stream()` yields a streaming binary file-like opened
directly out of the `.tar.gz` so callers can chunk-parse without paying
the temporary-disk cost on every run.

The SHA256 of the *archive bytes* is the cache key for the generated
`cbdb_data.mdb` and `cbdb.sqlite`. Each `DatadumpInfo.sha256` access
re-hashes the file (no in-memory cache) — at ~1.2s per 109 MB on a
modern SSD the cost is negligible compared to the soundness risk of any
fingerprint short of the bytes themselves. Callers that need the digest
more than once within a single build should hold the returned string.
"""

from __future__ import annotations

import hashlib
import re
import tarfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO

# `cbdb_data_20260526.tar.gz`
_NAME_RE = re.compile(r"^cbdb_data_(\d{8})\.tar\.gz$")
_HASH_CHUNK = 1 << 20  # 1 MB


class DatadumpError(RuntimeError):
    """Raised when the Datadump folder is empty, missing, or malformed."""


@dataclass(frozen=True, slots=True)
class DatadumpInfo:
    """A located Datadump archive.

    `sha256` is computed lazily — call `.sha256` (a property below) only
    when needed for cache-keying. Each call re-hashes the file; if the
    caller needs the digest more than once, store it locally.
    """

    path: Path
    date_tag: str  # e.g. "20260526"

    @property
    def filename(self) -> str:
        return self.path.name

    @property
    def sha256(self) -> str:
        return _sha256_of(self.path)

    @property
    def sql_member(self) -> str:
        """Name of the SQL file inside the archive. Confirmed empirically
        across the 2025-2026 Datadumps; if a future archive ever uses a
        different layout, callers will see DatadumpError from
        open_dump_stream() rather than silent wrong behaviour."""
        return "cbdb_data.sql"


def _sha256_of(path: Path) -> str:
    """Stream-hash the archive bytes. No caching — at ~1.2s per 109 MB
    archive and only 2-3 calls per build run, the perf gain is dwarfed by
    the soundness risk of any cache key short of the bytes themselves
    (cp -p / rsync -t can preserve mtime+size while changing content).
    Callers that need to avoid the cost should hold the digest themselves.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(_HASH_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def find_latest_datadump(datadump_dir: Path) -> DatadumpInfo:
    """Return the newest `cbdb_data_YYYYMMDD.tar.gz` in `datadump_dir`.

    "Newest" is determined by the YYYYMMDD tag in the filename, not by
    mtime — this is deliberate, so a re-download with an old date doesn't
    silently become "the latest" by virtue of having a fresh mtime.
    """
    if not datadump_dir.is_dir():
        raise DatadumpError(f"DATADUMP_DIR is not a directory: {datadump_dir}")

    candidates: list[DatadumpInfo] = []
    for entry in datadump_dir.iterdir():
        if not entry.is_file():
            continue
        m = _NAME_RE.match(entry.name)
        if not m:
            continue
        candidates.append(DatadumpInfo(path=entry, date_tag=m.group(1)))

    if not candidates:
        raise DatadumpError(
            f"No cbdb_data_YYYYMMDD.tar.gz archives found in {datadump_dir}. "
            f"(non-matching files like *.rar / *.7z / subdirs are ignored.)"
        )

    # Two archives with the same date tag would race for "newest"; filesystem
    # iteration order is not guaranteed, so the cache key (sha of the picked
    # file) would silently drift between runs. The filename regex shape makes
    # legitimate duplicates impossible, so treat it as ingestion corruption
    # and fail loud.
    by_tag: dict[str, list[Path]] = {}
    for d in candidates:
        by_tag.setdefault(d.date_tag, []).append(d.path)
    dupes = [(tag, paths) for tag, paths in by_tag.items() if len(paths) > 1]
    if dupes:
        rendered = "\n".join(
            f"  {tag}: {', '.join(p.name for p in paths)}" for tag, paths in dupes
        )
        raise DatadumpError(
            f"Multiple archives share the same date tag in {datadump_dir}:\n"
            f"{rendered}\n"
            f"Remove the duplicates so the latest-by-tag selection is unambiguous."
        )

    # Sort by (date_tag, name) for stable secondary order, even though the
    # dupe check above guarantees the secondary is never load-bearing.
    candidates.sort(key=lambda d: (d.date_tag, d.path.name))
    return candidates[-1]


@contextmanager
def open_dump_stream(info: DatadumpInfo) -> Iterator[IO[bytes]]:
    """Open the SQL member of the archive as a streaming binary file.

    Uses tarfile's streaming mode ('r|gz') so the archive is processed
    forward without an upfront index scan. For our single-member 1.4 GB
    archives, this matters: the random-access mode ('r:gz') effectively
    decompresses past every member during member-table population, which
    on a 1.4 GB single-member archive means decompressing the whole thing
    just to locate it.

    The yielded stream is **forward-only**: `seek()`/`tell()` will fail,
    and wrapping it in a buffer that needs rewind will misbehave. The
    Phase 1.1 mysqldump parser consumes the stream chunk-by-chunk from
    front to back, so this is fine; document explicitly so downstream
    consumers don't assume random access.

    The underlying tarfile is held open for the duration of the context —
    don't move the yielded handle outside the `with` block.
    """
    # Streaming mode: tarfile reads forward only. We iterate members as
    # their headers come in and grab `extractfile()` for the first match.
    tf = tarfile.open(info.path, mode="r|gz")
    try:
        for member in tf:
            if member.name != info.sql_member:
                continue
            stream = tf.extractfile(member)
            if stream is None:
                # extractfile returns None for non-regular members (dirs,
                # symlinks). Our member is regular so this shouldn't happen,
                # but fail loud instead of silently None'ing downstream.
                raise DatadumpError(
                    f"{info.filename}: member '{info.sql_member}' is not a regular file"
                )
            yield stream
            return
        # Iteration finished without finding the expected member.
        raise DatadumpError(
            f"{info.filename}: expected member '{info.sql_member}' not in archive"
        )
    finally:
        tf.close()
