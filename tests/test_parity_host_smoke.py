"""Smoke test for `cbdb_parity.parity_host` — the Python wrapper
around the Cbdb.App.ParityHost .NET console.

Verifies the one-shot CLI path end-to-end:
  - Python dataclass-ish request → JSON snake_case → STDIN
  - C# upstream service runs → JSON snake_case → STDOUT
  - Python wrapper parses → dict with `records` key

Skips cleanly when prerequisites aren't met (no SDK, no built
host, no sqlite). NEVER runs `dotnet build` in the test path —
that's the caller's responsibility (see WORK_PLAN.md Phase 5a).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest


def _load_config_or_skip():
    try:
        from cbdb_parity.config import load_config
        return load_config()
    except Exception as exc:
        pytest.skip(f"config load failed: {exc}")


def _dotnet_available_or_skip() -> None:
    if shutil.which("dotnet"):
        return
    if Path(r"C:\Program Files\dotnet\dotnet.exe").is_file():
        return
    pytest.skip(".NET SDK not installed (no dotnet CLI)")


def _host_built_or_skip(avalonia_repo: Path) -> None:
    """Skip if the C# host is unbuilt OR stale relative to upstream.

    We check for the published DLL — `invoke_parity_host` uses
    `--no-build`, so without this DLL the test would fail with a
    cryptic dotnet error instead of a clean skip.

    Stale-DLL check (codex 5a-4 P2): after `scripts/refresh_external_
    repos.py` pulls a newer `$AVALONIA_REPO`, the DLL can still be
    present but no longer match the upstream contracts. We compare
    the DLL mtime against the newest upstream `.cs` / `.csproj`
    timestamp under the two referenced project dirs; if any
    upstream file is newer, skip with a "needs rebuild" message.
    Without this gate the test fails with a loader/type error for
    what is actually an expected "host needs rebuild" state.
    """
    repo_root = Path(__file__).resolve().parent.parent
    host_dll = (
        repo_root / "parity_host" / "Cbdb.App.ParityHost"
        / "bin" / "Debug" / "net8.0" / "cbdb-parity-host.dll"
    )
    if not host_dll.is_file():
        pytest.skip(
            f"ParityHost not built. Run `dotnet build {host_dll.parent.parent.parent}` "
            "with $AVALONIA_REPO set, or call cbdb_parity.parity_host.build_parity_host()."
        )
    dll_mtime = host_dll.stat().st_mtime
    # Walk the two referenced upstream project dirs — Cbdb.App.Core
    # and Cbdb.App.Data — for any .cs / .csproj newer than the DLL.
    # We bound the walk by extension to avoid stat'ing bin/obj output
    # (which gets touched by other Avalonia builds and would produce
    # spurious "stale" verdicts).
    for sub in ("Cbdb.App.Core", "Cbdb.App.Data"):
        upstream_dir = avalonia_repo / sub
        if not upstream_dir.is_dir():
            # Missing upstream tree is a separate concern handled by
            # the Directory.Build.props fail-fast; skip silently here.
            return
        for ext in ("*.cs", "*.csproj"):
            for src in upstream_dir.rglob(ext):
                if "bin" in src.parts or "obj" in src.parts:
                    continue
                if src.stat().st_mtime > dll_mtime:
                    pytest.skip(
                        f"ParityHost DLL ({host_dll}) is older than upstream "
                        f"{src.relative_to(avalonia_repo)}. Run "
                        f"`cbdb_parity.parity_host.build_parity_host({avalonia_repo!r})`."
                    )


def test_parity_host_entry_smoke() -> None:
    cfg = _load_config_or_skip()
    _dotnet_available_or_skip()
    _host_built_or_skip(cfg.avalonia_repo)

    sqlite_path = cfg.build_output_dir / "cbdb.sqlite"
    if not sqlite_path.is_file():
        pytest.skip(f"sqlite not built at {sqlite_path}")

    from cbdb_parity.parity_host import invoke_parity_host

    # Minimal request: code 36 (jinshi), small limit so the smoke
    # test is fast. Use snake_case as the wire contract requires.
    request = {
        "entry_codes": ["36"],
        "place_ids": [],
        "dynasty_ids": [],
        "limit": 5,
    }
    response = invoke_parity_host(
        "entry",
        sqlite_path,
        request,
        avalonia_repo=cfg.avalonia_repo,
    )

    # Structural invariants from the upstream EntryQueryResult
    # record shape.
    assert isinstance(response, dict), f"expected dict, got {type(response)}"
    assert "records" in response, f"missing 'records' in {list(response)}"
    assert "people" in response, f"missing 'people' in {list(response)}"
    assert isinstance(response["records"], list)
    assert len(response["records"]) <= 5, "limit=5 not honoured"

    if response["records"]:
        first = response["records"][0]
        # Wire format MUST be snake_case (see codex 5a-3 round 1).
        assert "person_id" in first, f"expected snake_case fields, got {list(first)[:5]}"
        assert "name_chn" in first, "missing CJK round-trip target"
        # CJK round-trip: name_chn from BIOG_MAIN must NOT mojibake.
        # First Song jinshi in the database is person 3 "安燾" (An Tao).
        # We assert the value contains at least one non-ASCII char,
        # which is the load-bearing UTF-8 contract.
        nm = first.get("name_chn")
        if nm is not None:
            assert any(ord(c) > 127 for c in nm), (
                f"name_chn={nm!r} has no non-ASCII chars — UTF-8 contract broken?"
            )


def test_parity_host_unknown_service_error() -> None:
    cfg = _load_config_or_skip()
    _dotnet_available_or_skip()
    _host_built_or_skip(cfg.avalonia_repo)

    from cbdb_parity.parity_host import ParityHostError, invoke_parity_host

    with pytest.raises(ParityHostError) as exc:
        invoke_parity_host(
            "definitely-not-a-service",
            cfg.build_output_dir / "cbdb.sqlite",
            {},
            avalonia_repo=cfg.avalonia_repo,
        )
    # The error path must surface the upstream message verbatim, not
    # an opaque "subprocess returned 1" wrapper.
    assert "definitely-not-a-service" in str(exc.value), str(exc.value)
