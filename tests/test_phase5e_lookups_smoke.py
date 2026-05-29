"""Phase 5e — smoke tests for the lookup / group surfaces wired up
via the ParityHost.

There's no Access-side analogue for these read-only options
builders, so we don't do pair diffs. We verify:
  - DynastyLookup returns >0 rows with the documented record shape;
  - PlaceLookup returns >0 rows;
  - GroupPeople round-trips a small fixture (Su Shi only) and
    produces a result dict with the documented top-level shape.

Per WORK_PLAN.md §5e: each new surface costs three distinct
integrations (upstream service + host dispatch + Python wrapper).
The first two were available pre-5e; this commit closes the loop
by adding the wrapper + smoke gate.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest


def _load_config_or_skip():
    try:
        from cbdb_parity.config import load_config
    except ImportError:
        pytest.skip("cbdb_parity.config not importable")
    try:
        return load_config()
    except FileNotFoundError as exc:
        pytest.skip(f"config not configured: {exc}")


def _prereqs_or_skip(avalonia_repo: Path) -> None:
    if not (shutil.which("dotnet") or Path(r"C:\Program Files\dotnet\dotnet.exe").is_file()):
        pytest.skip(".NET SDK not installed")
    repo_root = Path(__file__).resolve().parent.parent
    host_dll = (
        repo_root / "parity_host" / "Cbdb.App.ParityHost"
        / "bin" / "Debug" / "net8.0" / "cbdb-parity-host.dll"
    )
    if not host_dll.is_file():
        pytest.skip("ParityHost not built. Run cbdb_parity.parity_host.build_parity_host(...)")


def test_dynasty_lookup_smoke() -> None:
    cfg = _load_config_or_skip()
    _prereqs_or_skip(cfg.avalonia_repo)
    sqlite_path = cfg.build_output_dir / "cbdb.sqlite"
    if not sqlite_path.is_file():
        pytest.skip(f"sqlite not built at {sqlite_path}")

    from cbdb_parity.avalonia_lookups import dynasty_lookup

    rows = dynasty_lookup(sqlite_path, avalonia_repo=cfg.avalonia_repo)
    assert len(rows) > 0, "dynasty_lookup returned no rows"
    # Sample the first row — schema must include the documented fields.
    expected = {"dynasty_id", "name", "name_chn", "start_year", "end_year"}
    assert expected.issubset(rows[0].keys()), (
        f"dynasty_lookup row missing fields {expected - rows[0].keys()}; "
        f"got {sorted(rows[0].keys())}"
    )


def test_place_lookup_smoke() -> None:
    cfg = _load_config_or_skip()
    _prereqs_or_skip(cfg.avalonia_repo)
    sqlite_path = cfg.build_output_dir / "cbdb.sqlite"
    if not sqlite_path.is_file():
        pytest.skip(f"sqlite not built at {sqlite_path}")

    from cbdb_parity.avalonia_lookups import place_lookup

    rows = place_lookup(sqlite_path, avalonia_repo=cfg.avalonia_repo)
    # CBDB has tens of thousands of places — any sensible build has
    # at least a few hundred. Treat <100 as a build smell.
    assert len(rows) >= 100, f"place_lookup returned {len(rows)} rows (suspicious)"


def test_group_people_smoke() -> None:
    cfg = _load_config_or_skip()
    _prereqs_or_skip(cfg.avalonia_repo)
    sqlite_path = cfg.build_output_dir / "cbdb.sqlite"
    if not sqlite_path.is_file():
        pytest.skip(f"sqlite not built at {sqlite_path}")

    from cbdb_parity.avalonia_lookups import (
        ADDRESS_MODE_ALL,
        GroupPeopleQueryOptions,
        group_people,
    )

    # Su Shi alone — keeps the test fast while exercising every
    # composite the options surface includes.
    options = GroupPeopleQueryOptions(
        include_status=True,
        include_office=True,
        include_entry=True,
        include_texts=True,
        include_addresses=True,
        address_mode=ADDRESS_MODE_ALL,
    )
    result = group_people(
        sqlite_path, [1762], options, avalonia_repo=cfg.avalonia_repo,
    )
    # GroupPeopleQueryResult exposes per-section IReadOnlyLists; the
    # exact keys come from the upstream record, but the result MUST be
    # a dict with at least one non-empty section for Su Shi (the
    # canonical fixture used throughout Phase 4/5).
    assert isinstance(result, dict)
    assert any(
        isinstance(v, list) and v for v in result.values()
    ), f"group_people for Su Shi returned no populated section: {result}"
