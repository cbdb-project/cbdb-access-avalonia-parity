"""Tests for cbdb_parity.diff_report — diff + per-query report writer."""

from __future__ import annotations

import json
from pathlib import Path

from cbdb_parity.diff_report import DiffStats, diff_rows, write_report

# ---------- diff_rows ----------

def test_diff_rows_identical_sets() -> None:
    rows = [{"id": 1, "x": "a"}, {"id": 2, "x": "b"}]
    diff = diff_rows(rows, rows, key_fields=("id",))
    assert diff.stats.matches
    assert diff.stats.rows_matching == 2
    assert diff.stats.rows_only_in_avalonia == 0
    assert diff.stats.rows_only_in_access == 0
    assert diff.stats.rows_value_mismatch == 0


def test_diff_rows_only_in_avalonia() -> None:
    av = [{"id": 1, "x": "a"}, {"id": 2, "x": "b"}]
    ac = [{"id": 1, "x": "a"}]
    diff = diff_rows(av, ac, key_fields=("id",))
    assert not diff.stats.matches
    assert diff.stats.rows_only_in_avalonia == 1
    assert diff.only_in_avalonia == [{"id": 2, "x": "b"}]


def test_diff_rows_only_in_access() -> None:
    av = [{"id": 1, "x": "a"}]
    ac = [{"id": 1, "x": "a"}, {"id": 99, "x": "z"}]
    diff = diff_rows(av, ac, key_fields=("id",))
    assert diff.stats.rows_only_in_access == 1
    assert diff.only_in_access == [{"id": 99, "x": "z"}]


def test_diff_rows_value_mismatch_same_key() -> None:
    av = [{"id": 1, "x": "a"}]
    ac = [{"id": 1, "x": "DIFFERENT"}]
    diff = diff_rows(av, ac, key_fields=("id",))
    assert diff.stats.rows_value_mismatch == 1
    mm = diff.value_mismatches[0]
    assert mm["key"] == [1]
    assert mm["differing_fields"] == {"x": {"avalonia": "a", "access": "DIFFERENT"}}


def test_diff_rows_composite_key() -> None:
    av = [
        {"person_id": 1, "sequence": 1, "v": "a"},
        {"person_id": 1, "sequence": 2, "v": "b"},
    ]
    ac = [
        {"person_id": 1, "sequence": 1, "v": "a"},
        {"person_id": 1, "sequence": 2, "v": "DIFF"},
    ]
    diff = diff_rows(av, ac, key_fields=("person_id", "sequence"))
    assert diff.stats.rows_matching == 1
    assert diff.stats.rows_value_mismatch == 1


def test_diff_rows_compare_fields_subset() -> None:
    """If `compare_fields` is restricted, fields outside it must not
    affect mismatch counts — useful when some columns are known to
    differ (e.g. computed labels) and we only want to compare IDs."""
    av = [{"id": 1, "id_field": 100, "label": "AvalonLabel"}]
    ac = [{"id": 1, "id_field": 100, "label": "AccessLabel"}]
    diff = diff_rows(av, ac, key_fields=("id",), compare_fields=("id_field",))
    assert diff.stats.matches  # label differs but isn't compared
    assert diff.stats.rows_matching == 1


def test_diff_rows_empty_inputs() -> None:
    diff = diff_rows([], [], key_fields=("id",))
    assert diff.stats.matches
    assert diff.stats.rows_avalonia == 0
    assert diff.stats.rows_access == 0


def test_diff_stats_matches_property_requires_zero_failures() -> None:
    s = DiffStats(rows_matching=10)
    assert s.matches
    s.rows_value_mismatch = 1
    assert not s.matches
    s.rows_value_mismatch = 0
    s.rows_only_in_avalonia = 1
    assert not s.matches


# ---------- write_report ----------

def test_write_report_creates_all_files(tmp_path: Path) -> None:
    av_rows = [{"id": 1, "x": "a"}]
    ac_rows = [{"id": 1, "x": "a"}]
    diff = diff_rows(av_rows, ac_rows, key_fields=("id",))
    out_dir = write_report(
        tmp_path / "reports",
        query_id="entry_basic",
        request={"limit": 100, "person_keyword": "Wang"},
        avalonia_rows=av_rows,
        access_rows=ac_rows,
        diff=diff,
        datadump_sha="deadbeef" * 8,
    )

    assert out_dir == tmp_path / "reports" / "entry_basic"
    assert (out_dir / "avalonia.json").exists()
    assert (out_dir / "access.json").exists()
    assert (out_dir / "diff.json").exists()
    assert (out_dir / "summary.md").exists()
    assert (out_dir / "hypothesis.md").exists()


def test_write_report_diff_payload_shape(tmp_path: Path) -> None:
    av = [{"id": 1, "x": "a"}]
    ac = [{"id": 1, "x": "b"}]
    diff = diff_rows(av, ac, key_fields=("id",))
    out = write_report(
        tmp_path / "r",
        query_id="q1",
        request={"limit": 5},
        avalonia_rows=av,
        access_rows=ac,
        diff=diff,
    )
    payload = json.loads((out / "diff.json").read_text(encoding="utf-8"))
    assert payload["query_id"] == "q1"
    assert payload["stats"]["rows_value_mismatch"] == 1
    assert payload["stats"]["matches"] is False
    assert payload["request"] == {"limit": 5}
    assert len(payload["value_mismatches"]) == 1


def test_write_report_summary_includes_verdict(tmp_path: Path) -> None:
    diff = diff_rows([], [], key_fields=("id",))
    out = write_report(
        tmp_path / "r",
        query_id="empty",
        request={},
        avalonia_rows=[],
        access_rows=[],
        diff=diff,
    )
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "**Verdict**: PASS" in summary
    assert "`empty`" in summary


def test_write_report_summary_marks_fail_on_mismatch(tmp_path: Path) -> None:
    av = [{"id": 1, "x": "a"}]
    ac = [{"id": 2, "x": "b"}]
    diff = diff_rows(av, ac, key_fields=("id",))
    out = write_report(
        tmp_path / "r",
        query_id="failing",
        request={},
        avalonia_rows=av,
        access_rows=ac,
        diff=diff,
    )
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "**Verdict**: FAIL" in summary


def test_write_report_preserves_existing_hypothesis(tmp_path: Path) -> None:
    """Re-running the harness must NOT overwrite hand-written hypothesis
    notes. The seed content (or any later edits) must survive."""
    diff = diff_rows([], [], key_fields=("id",))
    out_dir = tmp_path / "reports" / "q1"
    out_dir.mkdir(parents=True)
    hyp = out_dir / "hypothesis.md"
    hyp.write_text("# Hand-edited analysis — must not be clobbered\n", encoding="utf-8")

    write_report(
        tmp_path / "reports",
        query_id="q1",
        request={},
        avalonia_rows=[],
        access_rows=[],
        diff=diff,
    )
    assert "Hand-edited analysis" in hyp.read_text(encoding="utf-8")


def test_write_report_handles_non_json_default_types(tmp_path: Path) -> None:
    """A datetime sneaking into a row dict shouldn't crash the report writer."""
    from datetime import UTC, datetime
    av = [{"id": 1, "when": datetime(2024, 1, 1, tzinfo=UTC)}]
    ac = av
    diff = diff_rows(av, ac, key_fields=("id",))
    out = write_report(
        tmp_path / "r",
        query_id="dt",
        request={},
        avalonia_rows=av,
        access_rows=ac,
        diff=diff,
    )
    # JSON round-trips with the datetime as an isoformat string.
    av_payload = json.loads((out / "avalonia.json").read_text(encoding="utf-8"))
    assert av_payload["rows"][0]["when"] == "2024-01-01T00:00:00+00:00"
