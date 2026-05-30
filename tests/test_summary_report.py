"""Tests for cbdb_parity.summary_report — top-level reports/SUMMARY.md."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from cbdb_parity.summary_report import (
    _load_diff,
    cli_main,
    render_summary,
    write_summary,
)


def _seed_query_dir(reports_dir: Path, query_id: str, payload: dict) -> None:
    qdir = reports_dir / query_id
    qdir.mkdir(parents=True)
    (qdir / "diff.json").write_text(json.dumps(payload), encoding="utf-8")


_PASSING = {
    "query_id": "q_pass",
    "generated_at": "2026-05-27T08:00:00+00:00",
    "datadump_sha": "deadbeef" * 8,
    "stats": {
        "matches": True,
        "rows_avalonia": 10,
        "rows_access": 10,
        "rows_matching": 10,
        "rows_only_in_avalonia": 0,
        "rows_only_in_access": 0,
        "rows_value_mismatch": 0,
    },
}

_FAILING = {
    "query_id": "q_fail",
    "generated_at": "2026-05-27T08:30:00+00:00",
    "datadump_sha": "feedcafe" * 8,
    "stats": {
        "matches": False,
        "rows_avalonia": 20,
        "rows_access": 18,
        "rows_matching": 15,
        "rows_only_in_avalonia": 3,
        "rows_only_in_access": 1,
        "rows_value_mismatch": 2,
    },
}


def test_render_empty_reports_dir(tmp_path: Path) -> None:
    """No per-query reports → SUMMARY explains that."""
    text = render_summary(tmp_path / "reports")
    assert "Total paired queries**: 0" in text
    assert "No per-query reports found" in text


def test_render_one_passing(tmp_path: Path) -> None:
    rdir = tmp_path / "reports"
    _seed_query_dir(rdir, "q_pass", _PASSING)
    text = render_summary(rdir)
    assert "Total paired queries**: 1" in text
    assert "Passing** (rows match): 1" in text
    assert "Failing** (mismatch present): 0" in text
    assert "`q_pass`" in text
    assert "✅ PASS" in text


def test_render_mixed_pass_and_fail(tmp_path: Path) -> None:
    rdir = tmp_path / "reports"
    _seed_query_dir(rdir, "q_pass", _PASSING)
    _seed_query_dir(rdir, "q_fail", _FAILING)
    text = render_summary(rdir)
    assert "Total paired queries**: 2" in text
    assert "Passing** (rows match): 1" in text
    assert "Failing** (mismatch present): 1" in text
    assert "❌ FAIL" in text
    assert "✅ PASS" in text


def test_render_tolerates_malformed_diff_json(tmp_path: Path) -> None:
    rdir = tmp_path / "reports"
    _seed_query_dir(rdir, "q_good", _PASSING)
    bad_dir = rdir / "q_bad"
    bad_dir.mkdir()
    (bad_dir / "diff.json").write_text("{ not even json", encoding="utf-8")
    # Should still render with just the good one — bad entry ignored.
    text = render_summary(rdir)
    assert "Total paired queries**: 1" in text
    # _PASSING has query_id="q_pass" inside the payload; the rendered
    # table uses that, not the directory name.
    assert "`q_pass`" in text


def test_load_diff_missing_file_returns_none(tmp_path: Path) -> None:
    assert _load_diff(tmp_path / "nope.json") is None


def test_load_diff_no_stats_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "diff.json"
    p.write_text(json.dumps({"query_id": "x"}), encoding="utf-8")
    assert _load_diff(p) is None


def test_write_summary_creates_file(tmp_path: Path) -> None:
    rdir = tmp_path / "reports"
    _seed_query_dir(rdir, "q_pass", _PASSING)
    out = write_summary(rdir)
    assert out == rdir / "SUMMARY.md"
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "Total paired queries**: 1" in text


def test_write_summary_handles_empty_reports_dir(tmp_path: Path) -> None:
    out = write_summary(tmp_path / "reports")
    assert out.exists()
    assert "Total paired queries**: 0" in out.read_text(encoding="utf-8")


def test_render_ignores_files_at_reports_root(tmp_path: Path) -> None:
    """A stray file directly under reports/ (e.g. SUMMARY.md itself or
    known_issues.md) must NOT be treated as a query report directory."""
    rdir = tmp_path / "reports"
    rdir.mkdir()
    (rdir / "SUMMARY.md").write_text("stale", encoding="utf-8")
    (rdir / "known_issues.md").write_text("notes", encoding="utf-8")
    _seed_query_dir(rdir, "q_pass", _PASSING)
    text = render_summary(rdir)
    assert "Total paired queries**: 1" in text  # just q_pass, not the .md files


def test_cli_main_rewrites_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Phase 7c — cbdb-parity-summary CLI must REWRITE
    reports/SUMMARY.md, not silently append/refuse. Codex round
    flagged that the original test would false-pass if the CLI
    only created new files; we now pre-seed a sentinel SUMMARY.md
    and assert the old content is gone after the rewrite."""
    rdir = tmp_path / "reports"
    _seed_query_dir(rdir, "q_pass", _PASSING)
    sentinel = "STALE-CONTENT-THAT-MUST-BE-REPLACED"
    (rdir / "SUMMARY.md").write_text(sentinel, encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["cbdb-parity-summary", "--reports-dir", str(rdir)])
    rc = cli_main()
    assert rc == 0

    captured = capsys.readouterr()
    out = rdir / "SUMMARY.md"
    assert out.exists()
    written = out.read_text(encoding="utf-8")
    assert sentinel not in written, (
        "Stale content survived; CLI did not actually rewrite "
        "the file."
    )
    assert "Total paired queries**: 1" in written
    assert str(out) in captured.out


def test_cli_main_reports_dir_is_a_file_exits_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Codex round flagged that --reports-dir accepted any Path
    that `exists()`. A file path should be rejected with the same
    exit code as a missing dir (2), not crash later in
    write_summary's iterdir."""
    f = tmp_path / "not_a_dir.txt"
    f.write_text("hi", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["cbdb-parity-summary", "--reports-dir", str(f)])
    rc = cli_main()
    assert rc == 2
    captured = capsys.readouterr()
    assert "must be a directory" in captured.out
    assert str(f) in captured.out


def test_cli_main_missing_reports_dir_exits_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Distinct exit code (2) for the case where the reports tree
    doesn't exist at all — distinguishes "harness hasn't run" from
    "harness ran but produced no reports" (the latter is a legitimate
    empty state that cli_main reports normally with exit 0)."""
    missing = tmp_path / "reports_does_not_exist"
    monkeypatch.setattr(sys, "argv", ["cbdb-parity-summary", "--reports-dir", str(missing)])
    rc = cli_main()
    assert rc == 2

    captured = capsys.readouterr()
    assert "not found" in captured.out
    assert str(missing) in captured.out


def test_cli_main_default_reports_dir_uses_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With no `--reports-dir` flag the CLI should resolve to
    `<cwd>/reports`, matching the convention every other
    cbdb-parity-* CLI uses."""
    rdir = tmp_path / "reports"
    _seed_query_dir(rdir, "q_pass", _PASSING)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["cbdb-parity-summary"])
    rc = cli_main()
    assert rc == 0
    assert (rdir / "SUMMARY.md").exists()
