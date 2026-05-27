"""Tests for cbdb_parity.access_query — bridge to cbdb_replay/lookatentry.

The real Access ODBC path can't run in non-Windows CI; the unit tests
here cover request-mapping + row-projection logic via fake imports.
The pyodbc-driven end-to-end test sits in
`tests/test_phase3c_entry_pair.py` (Phase 3c, gated on the bg mdb
build completing).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from cbdb_parity.access_query import (
    _avalonia_request_to_replay_inputs,
    _ensure_cbdb_replay_on_path,
    _replay_row_to_avalonia_shape,
    entry_query_common_fields,
)
from cbdb_parity.avalonia_query import EntryQueryRequest

# ---------- sys.path insertion ----------

def test_ensure_cbdb_replay_on_path_idempotent(tmp_path: Path) -> None:
    fake_tests = tmp_path / "fake-tests-repo" / "tests"
    fake_tests.mkdir(parents=True)
    _ensure_cbdb_replay_on_path(tmp_path / "fake-tests-repo")
    inserted = str(fake_tests)
    assert inserted in sys.path
    # Second call: still only one entry.
    _ensure_cbdb_replay_on_path(tmp_path / "fake-tests-repo")
    assert sys.path.count(inserted) == 1
    # Clean up.
    sys.path.remove(inserted)


# ---------- request mapping ----------

@pytest.fixture
def fake_replay_module(monkeypatch: pytest.MonkeyPatch):
    """Inject a minimal `cbdb_replay.lookatentry` module so the request
    mapper can be tested without the real cbdb-user-mdb-tests checkout."""
    from dataclasses import dataclass, field
    from typing import Literal

    @dataclass
    class FakeInputs:
        entry_codes: list[int] | None = None
        addr_ids: list[int] | None = None
        addr_field: Literal["person", "entry"] = "person"
        include_subunits: bool = False
        use_xy_radius: bool = False
        year_mode: str = "none"
        from_year: int | None = None
        to_year: int | None = None
        from_dynasty: int = -1
        to_dynasty: int = -1
        from_dynasty_begin: int | None = field(default=None)
        to_dynasty_end: int | None = field(default=None)

    fake_mod = types.ModuleType("cbdb_replay.lookatentry")
    fake_mod.EntryQueryInputs = FakeInputs  # type: ignore[attr-defined]
    fake_pkg = types.ModuleType("cbdb_replay")
    monkeypatch.setitem(sys.modules, "cbdb_replay", fake_pkg)
    monkeypatch.setitem(sys.modules, "cbdb_replay.lookatentry", fake_mod)
    return FakeInputs


def test_request_mapping_basic(fake_replay_module) -> None:
    req = EntryQueryRequest(
        entry_codes=("197", "198"),
        place_ids=(100, 200),
        include_subordinate_units=True,
    )
    out = _avalonia_request_to_replay_inputs(req)
    assert out.entry_codes == [197, 198]
    assert out.addr_ids == [100, 200]
    assert out.include_subunits is True
    assert out.addr_field == "entry"
    assert out.year_mode == "none"


def test_request_mapping_index_year_range(fake_replay_module) -> None:
    req = EntryQueryRequest(use_index_year_range=True, index_year_from=1500, index_year_to=1200)
    out = _avalonia_request_to_replay_inputs(req)
    assert out.year_mode == "index"
    # Year swap clamped via min/max.
    assert out.from_year == 1200
    assert out.to_year == 1500


def test_request_mapping_entry_year_range(fake_replay_module) -> None:
    req = EntryQueryRequest(use_entry_year_range=True, entry_year_from=1600, entry_year_to=1700)
    out = _avalonia_request_to_replay_inputs(req)
    assert out.year_mode == "entry"
    assert out.from_year == 1600
    assert out.to_year == 1700


def test_request_mapping_empty_request_yields_none_filters(fake_replay_module) -> None:
    out = _avalonia_request_to_replay_inputs(EntryQueryRequest())
    assert out.entry_codes is None
    assert out.addr_ids is None
    assert out.year_mode == "none"


def test_request_mapping_rejects_non_integer_entry_code(fake_replay_module) -> None:
    """Avalonia request uses str entry_codes; cbdb_replay wants ints.
    Non-numeric strings (which shouldn't appear in CBDB data) raise."""
    with pytest.raises(ValueError, match="non-integer entry_code"):
        _avalonia_request_to_replay_inputs(EntryQueryRequest(entry_codes=("not_an_int",)))


# ---------- row projection ----------

def test_replay_row_projection_extracts_common_fields() -> None:
    replay_row = {
        "c_personid": 1234,
        "c_name": "Wang Bo",
        "c_name_chn": "王勃",
        "c_index_year": 670,
        "c_dy": 7,
        "c_entry_code": 197,  # int — Avalonia returns str
        "c_year": 666,
        "c_sequence": 1,
        "c_exam_rank": "甲",
        "c_addr_id": 100,
        "c_entry_addr_id": 200,
        # Extra columns from cbdb_replay (ignored):
        "c_kin_id": None,
        "c_assoc_id": None,
    }
    out = _replay_row_to_avalonia_shape(replay_row)
    assert out == {
        "person_id": 1234,
        "name": "Wang Bo",
        "name_chn": "王勃",
        "index_year": 670,
        "entry_code": "197",  # int → str
        "entry_year": 666,
        "sequence": 1,
        "exam_rank": "甲",
        "entry_address_id": 200,
    }


def test_replay_row_projection_handles_none_entry_code() -> None:
    """entry_code = None must NOT be coerced via str(None)."""
    row = {"c_personid": 1, "c_entry_code": None}
    out = _replay_row_to_avalonia_shape(row)
    assert out["entry_code"] is None


def test_replay_row_projection_missing_fields_default_to_none() -> None:
    """A cbdb_replay row missing some columns yields None for those
    Avalonia fields rather than KeyError."""
    out = _replay_row_to_avalonia_shape({"c_personid": 42})
    assert out["person_id"] == 42
    assert out["name"] is None
    assert out["name_chn"] is None


# ---------- field-name accessor ----------

def test_common_fields_match_replay_mapping() -> None:
    """Sanity that the public accessor returns the same field set used
    by the row-projection helper. Used by Phase 3c's `diff_rows` call."""
    expected = (
        "person_id", "name", "name_chn", "index_year",
        "entry_code", "entry_year", "sequence", "exam_rank",
        "entry_address_id",
    )
    assert entry_query_common_fields() == expected
