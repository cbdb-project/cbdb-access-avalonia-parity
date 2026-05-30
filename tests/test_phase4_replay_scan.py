"""Phase 4+ — replay-scan: run every cbdb-user-mdb-tests input case
that has an Avalonia analogue through the pair harness.

Scope (per user direction 2026-05-28): the three Tier 1 paired
categories (entry / status / office). Avalonia-gap categories
(texts / place / networks / assocpairs / kinship-recursive /
groupdata) are documented in `reports/known_issues.md` and not
scanned here.

For each case:
  - load the original cbdb-user-mdb-tests input dataclass
  - try to translate it into the matching Avalonia request
  - if the translation requires a feature Avalonia doesn't support
    (e.g. entry-query `addr_field='person'`), skip with a reason
    that the summary harness can pick up
  - otherwise: run both sides, diff_rows on the common-field
    cross-section, write a per-case report under
    `reports/replay_scan/<case_id>/`

The test asserts the diff matches (matches==True). Skipped cases
are recorded as "Avalonia gap" in the scan summary.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest


def _skip_if_missing(*paths: Path) -> None:
    for p in paths:
        if not p.exists():
            pytest.skip(f"required path missing: {p}")


def _load_config_or_skip():
    try:
        from cbdb_parity.config import load_config
        return load_config()
    except Exception as exc:
        pytest.skip(f"config load failed: {exc}")


def _both_products_match_datadump(
    manifest_path: Path,
    sqlite_path: Path,
    mdb_path: Path,
) -> tuple[bool, str | None]:
    if not manifest_path.exists():
        return False, None
    try:
        payload: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False, None
    if not isinstance(payload.get("datadump"), dict):
        return False, None
    sha = payload["datadump"].get("sha256")
    products = payload.get("products", {})
    if not (isinstance(products, dict) and "sqlite" in products and "mdb" in products):
        return False, sha

    def _path_matches(entry: object, target: Path) -> bool:
        if not isinstance(entry, dict):
            return False
        recorded = entry.get("path")
        if not isinstance(recorded, str):
            return False
        try:
            return Path(recorded).resolve() == target.resolve()
        except OSError:
            return False

    if not _path_matches(products.get("sqlite"), sqlite_path):
        return False, sha
    if not _path_matches(products.get("mdb"), mdb_path):
        return False, sha
    return True, sha


def _load_user_mdb_tests_cases(cfg):
    """Import the entry/status/office CASES lists from
    cbdb-user-mdb-tests. Returns a list of `(category, case_id, raw_input,
    expected)` tuples."""
    tests_root = cfg.access_tests_repo / "tests"
    if str(tests_root) not in sys.path:
        sys.path.insert(0, str(tests_root))

    cases: list[tuple[str, str, Any, Any]] = []

    # Entry: explicit CASES list.
    from test_lookatentry import CASES as ENTRY_CASES
    for case_id, inputs, expected in ENTRY_CASES:
        cases.append(("entry", case_id, inputs, expected))

    # Status / Office: defined as individual functions in test_other_lookat_forms.
    # Re-declare the inputs inline so the scan stays self-contained.
    from cbdb_replay.lookatstatus import StatusQueryInputs
    from cbdb_replay.lookatoffice import OfficeQueryInputs
    from cbdb_replay.lookatentry import EntryQueryInputs as _EntryQI  # noqa: F401
    from cbdb_replay.common import YearFilter

    cases.append((
        "status", "empty_codes",
        StatusQueryInputs(), None,
    ))
    cases.append((
        "status", "basic_status40_song",
        StatusQueryInputs(
            status_codes=[40],
            year_mode="dynasty",
            from_dynasty=15, to_dynasty=15,
            from_dynasty_begin=960, to_dynasty_end=1279,
        ),
        None,
    ))
    cases.append((
        "status", "status40_kaifeng_900_1100",
        StatusQueryInputs(
            status_codes=[40],
            addr_ids=[100658],
            year_mode="index",
            from_year=900, to_year=1100,
        ),
        None,
    ))

    cases.append((
        "office", "empty_codes",
        OfficeQueryInputs(), None,
    ))
    cases.append((
        "office", "office1_song",
        OfficeQueryInputs(
            office_codes=[1],
            year_filter=YearFilter(
                mode="dynasty", from_dynasty=15, to_dynasty=15,
                from_dynasty_begin=960, to_dynasty_end=1279,
            ),
        ),
        None,
    ))

    # Phase 7f — kinship cases. cbdb_replay.lookatkinship is a
    # per-person query (1-hop direct), so the "inputs" here is
    # just a person_id dict; the translator below is a no-op
    # pass-through. Wang Anshi (1762) is already covered by
    # tests/test_phase4_kinships_pair.py + the orphan-kin proof
    # case there, so this scan adds three more seed persons
    # spanning Tang (Li Bai), Northern Song (Fan Zhongyan), and
    # Southern Song (Zhu Xi). All three were verified non-empty
    # at fixture-design time (5, 10, 23, 29 kin rows).
    cases.append(("kinship", "li_bai_32540", {"person_id": 32540}, None))
    cases.append(("kinship", "fan_zhongyan_8043", {"person_id": 8043}, None))
    cases.append(("kinship", "zhu_xi_3257", {"person_id": 3257}, None))
    return cases


def _translate_entry_to_avalonia(replay_inputs: Any):
    """Map cbdb_replay.lookatentry.EntryQueryInputs → Avalonia
    EntryQueryRequest. Returns (request, skip_reason)."""
    from cbdb_parity.avalonia_query import EntryQueryRequest

    # Avalonia's entry query filters by ENTRY addresses, not person
    # addresses; if the Access input uses addr_field='person', no
    # equivalent Avalonia call exists. This repo only DETECTS the
    # gap; adding `AddrField` belongs to the upstream Avalonia repo.
    if replay_inputs.addr_ids and getattr(replay_inputs, "addr_field", None) == "person":
        return None, (
            "Avalonia EntryQueryRequest only supports entry-address filtering "
            "(`place_ids` maps to `entry_addr_id`); the Access input uses "
            "`addr_field='person'` which has no Avalonia analogue."
        )

    use_index = replay_inputs.year_mode == "index"
    use_entry = replay_inputs.year_mode == "entry"
    dynasty_ids: tuple[int, ...] = ()
    if replay_inputs.year_mode == "dynasty":
        # Pack single-dynasty range as a one-element list (the Avalonia
        # side computes the year range internally from the dynasty IDs).
        from_d = getattr(replay_inputs, "from_dynasty", None) or 0
        to_d = getattr(replay_inputs, "to_dynasty", None) or from_d
        dynasty_ids = tuple(range(int(from_d), int(to_d) + 1)) if from_d else ()

    return (EntryQueryRequest(
        entry_codes=tuple(str(c) for c in (replay_inputs.entry_codes or ())),
        place_ids=tuple(replay_inputs.addr_ids or ()),
        include_subordinate_units=bool(getattr(replay_inputs, "include_subunits", False)),
        use_index_year_range=use_index,
        index_year_from=int(replay_inputs.from_year or 0) if use_index else 0,
        index_year_to=int(replay_inputs.to_year or 0) if use_index else 0,
        use_entry_year_range=use_entry,
        entry_year_from=int(replay_inputs.from_year or 0) if use_entry else 0,
        entry_year_to=int(replay_inputs.to_year or 0) if use_entry else 0,
        dynasty_ids=dynasty_ids,
        limit=5000,
    ), None)


def _translate_status_to_avalonia(replay_inputs: Any):
    from cbdb_parity.avalonia_status_query import StatusQueryRequest

    use_index = replay_inputs.year_mode == "index"
    dynasty_ids: tuple[int, ...] = ()
    if replay_inputs.year_mode == "dynasty":
        from_d = getattr(replay_inputs, "from_dynasty", None) or 0
        to_d = getattr(replay_inputs, "to_dynasty", None) or from_d
        dynasty_ids = tuple(range(int(from_d), int(to_d) + 1)) if from_d else ()

    return (StatusQueryRequest(
        status_codes=tuple(str(c) for c in (replay_inputs.status_codes or ())),
        place_ids=tuple(replay_inputs.addr_ids or ()),
        use_index_year_range=use_index,
        index_year_from=int(replay_inputs.from_year or 0) if use_index else 0,
        index_year_to=int(replay_inputs.to_year or 0) if use_index else 0,
        dynasty_ids=dynasty_ids,
        limit=5000,
    ), None)


def _translate_office_to_avalonia(replay_inputs: Any):
    """Map cbdb_replay.lookatoffice.OfficeQueryInputs → Avalonia
    OfficeQueryRequest. The previous upstream
    `pto.c_appt_type_code` bug has been fixed in cbdb-desktop-app;
    office cases now flow through the full pair-diff path.
    """
    from cbdb_parity.avalonia_office_query import OfficeQueryRequest
    yf = getattr(replay_inputs, "year_filter", None)
    use_index_year_range = False
    index_year_from = 0
    index_year_to = 0
    dynasty_ids: tuple[int, ...] = ()
    if yf is not None:
        if yf.mode == "index":
            use_index_year_range = True
            index_year_from = int(yf.from_year or 0)
            index_year_to = int(yf.to_year or 0)
        elif yf.mode == "dynasty":
            from_d = int(yf.from_dynasty or 0)
            to_d = int(yf.to_dynasty or from_d)
            dynasty_ids = tuple(range(from_d, to_d + 1)) if from_d else ()

    # cbdb_replay.lookatoffice has an INDEPENDENT use_office_years /
    # office_from_year / office_to_year channel that gates the
    # POSTED_TO_OFFICE_DATA year columns. Avalonia mirrors this with
    # use_office_year_range / office_year_from / office_year_to.
    # Dropping these silently makes the Access side filtered while
    # the Avalonia side runs without the office-year filter, which
    # surfaces as false parity failures. (codex final-round-2 P1.)
    use_office_year_range = bool(getattr(replay_inputs, "use_office_years", False))
    office_year_from = int(getattr(replay_inputs, "office_from_year", None) or 0)
    office_year_to = int(getattr(replay_inputs, "office_to_year", None) or 0)

    office_codes = tuple(
        str(c) for c in (getattr(replay_inputs, "office_codes", None) or ())
    )
    return (OfficeQueryRequest(
        office_codes=office_codes,
        use_index_year_range=use_index_year_range,
        index_year_from=index_year_from,
        index_year_to=index_year_to,
        use_office_year_range=use_office_year_range,
        office_year_from=office_year_from,
        office_year_to=office_year_to,
        dynasty_ids=dynasty_ids,
        limit=5000,
    ), None)


def _translate_kinship_to_avalonia(replay_inputs: Any):
    """No-op translator. cbdb_replay.lookatkinship runs per-person
    and our case payload is already `{"person_id": <int>}`. The
    "Avalonia request" for this scan branch is the same dict —
    the dispatch below reads `person_id` out of it directly.

    Codex 7f round flagged that the previous version accepted any
    truthy `person_id` value (str, bool, ...), letting corrupted
    payloads slip past the contract boundary. The check now
    enforces (a) dict shape, (b) `person_id` key present, (c) the
    value is a non-bool int. `bool` is rejected explicitly
    because `bool` is a subclass of `int` in Python — `True ==
    1`, but `{"person_id": True}` is almost certainly a data
    corruption, not "the harness wants kin of person 1".
    """
    if not isinstance(replay_inputs, dict):
        return None, (
            "kinship case payload must be a dict; got "
            f"{type(replay_inputs).__name__}"
        )
    if "person_id" not in replay_inputs:
        return None, (
            "kinship case payload missing 'person_id' key; got keys "
            f"{sorted(replay_inputs)}"
        )
    person_id = replay_inputs["person_id"]
    if isinstance(person_id, bool) or not isinstance(person_id, int):
        return None, (
            "kinship case payload 'person_id' must be int; got "
            f"{type(person_id).__name__} ({person_id!r})"
        )
    return replay_inputs, None


_CATEGORY_TRANSLATORS = {
    "entry":   _translate_entry_to_avalonia,
    "status":  _translate_status_to_avalonia,
    "office":  _translate_office_to_avalonia,
    "kinship": _translate_kinship_to_avalonia,
}


# Build the parametrize list lazily inside a fixture so test
# collection doesn't fail on machines without cbdb-user-mdb-tests.
def _safe_cases():
    try:
        from cbdb_parity.config import load_config
        cfg = load_config()
        return _load_user_mdb_tests_cases(cfg)
    except Exception:
        return []


# Cases that empirically do not fit a clean (≤10000 row) comparison
# window. The dynasty-filter probe established that all three Avalonia
# dynasty-filter variants align 100% with their cbdb_replay
# counterparts when the result set fits within Avalonia's hardcoded
# LIMIT cap of 10000. The all_jinshi case asks an unconstrained
# "Song dynasty entries" question that produces ~40k rows on
# cbdb_replay, so Avalonia's top-10k slice (sorted by entry_label,
# c_year, c_personid, c_sequence) and cbdb_replay's unsorted slice
# don't overlap. Marked xfail to record the finding without ringing
# the test red — see coverage/replay_scan_results.md for the
# probe table. This repo only DETECTS the issue; raising the cap
# is an upstream Avalonia change.
_XFAIL_LIMIT_TRUNCATION: set[tuple[str, str]] = {
    ("entry", "all_jinshi_general_song"),
}


@pytest.mark.parametrize(
    "category,case_id,replay_inputs,_expected",
    _safe_cases(),
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_replay_scan(
    category: str,
    case_id: str,
    replay_inputs: Any,
    _expected: Any,
    tmp_path: Path,
) -> None:
    cfg = _load_config_or_skip()
    sqlite_path = cfg.build_output_dir / "cbdb.sqlite"
    mdb_path = cfg.build_output_dir / "cbdb_data.mdb"
    manifest = Path.cwd() / "build_manifest.json"
    if not manifest.exists():
        try:
            from dotenv import find_dotenv
            found = find_dotenv(usecwd=True)
            if found:
                manifest = Path(found).parent / "build_manifest.json"
        except ImportError:
            pass

    _skip_if_missing(sqlite_path, mdb_path)

    same_sha, sha = _both_products_match_datadump(manifest, sqlite_path, mdb_path)
    if not same_sha:
        pytest.skip(
            f"strict-pipeline rule: sqlite and mdb must share a SHA AND the manifest's "
            f"recorded paths must resolve to {sqlite_path} / {mdb_path}; manifest={manifest} sha={sha!r}"
        )

    try:
        import pyodbc  # noqa: F401
    except ImportError:
        pytest.skip("pyodbc not installed")

    translator = _CATEGORY_TRANSLATORS[category]
    avalonia_request, skip_reason = translator(replay_inputs)
    if skip_reason:
        pytest.skip(f"[{category}/{case_id}] {skip_reason}")

    if (category, case_id) in _XFAIL_LIMIT_TRUNCATION:
        pytest.xfail(
            f"[{category}/{case_id}] cbdb_replay returns more rows than "
            f"Avalonia's hardcoded LIMIT cap (10000), and cbdb_replay has "
            f"no ORDER BY — the truncated row sets don't overlap. The "
            f"semantics ARE aligned (verified by the dynasty-filter probe; "
            f"see coverage/replay_scan_results.md). Narrow the question "
            f"upstream or raise Avalonia's LIMIT cap to clear."
        )

    # Dispatch to the right paired bridge.
    from cbdb_parity.diff_report import diff_rows, write_report

    avalonia_data = cfg.avalonia_repo / "Cbdb.App.Data"
    reports_dir = Path.cwd() / "reports" / "replay_scan"

    # Catch the documented upstream Avalonia bug at the scan level
    # too (office cases hit the same c_appt_type_code SQL as the
    # Phase 3d office pair).
    import sqlite3
    try:
        if category == "entry":
            from cbdb_parity.avalonia_query import entry_query
            from cbdb_parity.access_query import (
                entry_query_access, entry_query_common_fields,
                _ensure_cbdb_replay_on_path,
            )
            _ensure_cbdb_replay_on_path(cfg.access_tests_repo)
            avalonia_rows = entry_query(sqlite_path, avalonia_request, avalonia_data_dir=avalonia_data)
            access_rows = entry_query_access(mdb_path, avalonia_request, access_tests_repo=cfg.access_tests_repo)
            key_fields = ("person_id", "sequence")
            compare_fields = entry_query_common_fields()
        elif category == "status":
            from cbdb_parity.avalonia_status_query import status_query
            from cbdb_parity.access_status_query import (
                status_query_access, status_query_common_fields,
            )
            avalonia_rows = status_query(sqlite_path, avalonia_request, avalonia_data_dir=avalonia_data)
            access_rows = status_query_access(mdb_path, avalonia_request, access_tests_repo=cfg.access_tests_repo)
            key_fields = ("person_id", "sequence")
            compare_fields = status_query_common_fields()
        elif category == "office":
            from cbdb_parity.avalonia_office_query import office_query
            from cbdb_parity.access_office_query import (
                office_query_access, office_query_common_fields,
            )
            avalonia_rows = office_query(sqlite_path, avalonia_request, avalonia_data_dir=avalonia_data)
            access_rows = office_query_access(mdb_path, avalonia_request, access_tests_repo=cfg.access_tests_repo)
            # Office shape: same diff key as Phase 3d (see
            # test_phase3d_office_pair.py for rationale on the addr-id
            # tail).
            # Use the field names the bridges actually emit
            # (`office_code` / `office_address_id`, NOT the C# aliases
            # `office_id` / `office_addr_id`). The wrong names made
            # every office row key as (pid, posting_id, None, None) —
            # silently collapsing multi-address fan-outs before diff.
            # (codex final-round-1 P1.)
            key_fields = ("person_id", "posting_id", "office_code", "office_address_id")
            compare_fields = office_query_common_fields()
        elif category == "kinship":
            # Phase 7f — kinship per-person scan. Avalonia routes
            # through ParityHost (GetKinshipsAsync, expand_network=
            # false). Access routes through cbdb_replay.lookatkinship
            # (Phase 6a). Compare against the same raw cross-section
            # that test_phase4_kinships_pair.py uses; see
            # cbdb_parity/access_kinships.py for the §0.b rationale
            # behind dropping the joined `kinship` label from the
            # diff. Documented orphan-kin row-set gap (INNER vs LEFT
            # JOIN) is tracked in
            # reports/known_issues.md#kinships_basic_person — for
            # the canonical 2026-04-30 Datadump KIN_DATA has zero
            # orphans so the scan should pass exactly when the
            # dedicated pair test passes.
            from cbdb_parity.avalonia_kinships import kinships_query
            from cbdb_parity.access_kinships import (
                kinships_common_fields, kinships_query_access,
            )
            person_id = avalonia_request["person_id"]  # already int per translator check
            avalonia_rows = kinships_query(
                sqlite_path, person_id, avalonia_data_dir=avalonia_data,
            )
            access_rows = kinships_query_access(
                mdb_path, person_id, access_tests_repo=cfg.access_tests_repo,
            )
            # Codex 7f round: empty-vs-empty would trivially pass
            # without exercising either backend. Every kinship seed
            # in this scan was verified non-empty at fixture-design
            # time (10, 23, 29 rows for Li Bai / Fan Zhongyan /
            # Zhu Xi); fail loudly if a future dump no longer
            # populates them, so the regression surfaces rather
            # than being silently masked.
            assert len(avalonia_rows) > 0, (
                f"[kinship/{case_id}] Avalonia returned zero kin rows "
                f"for person_id={person_id}. The seed used to have "
                f"≥1 row on the canonical dataset; either the dump "
                f"stopped populating KIN_DATA for this person, or "
                f"the request shape is wrong."
            )
            assert len(access_rows) > 0, (
                f"[kinship/{case_id}] cbdb_replay returned zero kin rows "
                f"for person_id={person_id}. The seed used to have "
                f"≥1 row on the canonical dataset; either the dump "
                f"stopped populating KIN_DATA for this person, or "
                f"the cbdb_replay query shape changed."
            )
            key_fields = ("kin_person_id", "kin_code")
            compare_fields = kinships_common_fields()
        else:
            pytest.skip(f"unsupported category {category!r}")
    except NotImplementedError as exc:
        # The Access cbdb_replay bridge rejects request branches it
        # cannot faithfully replay (empty filter lists, dynasty mode,
        # unsupported fields). That's a bridge limitation, not a
        # parity bug — skip the scan case with the bridge's own error
        # message so the scan summary shows it as a documented gap.
        pytest.skip(f"[{category}/{case_id}] Access bridge gap: {exc}")
    except sqlite3.OperationalError as exc:
        # Defensive: legacy framing of the c_appt_type_code issue
        # before we understood it was a mirror-layer limitation, not
        # an Avalonia bug. Kept for older deployments that haven't
        # yet pulled the upstream runtime-schema-compat shim.
        if "c_appt_type_code" in str(exc):
            pytest.skip(
                f"[{category}/{case_id}] Avalonia upstream bug "
                f"(reports/known_issues.md office_basic): {exc}"
            )
        raise
    except LookupError as exc:
        # Documented mirror-layer limit (reports/known_issues.md
        # office_basic): interpolated `$@"…"` SQL the extractor
        # can't read. Re-arms once Phase 5 lands.
        pytest.skip(
            f"[{category}/{case_id}] Python mirror-layer limit "
            f"(reports/known_issues.md office_basic): {exc}"
        )

    diff = diff_rows(
        avalonia_rows, access_rows,
        key_fields=key_fields,
        compare_fields=compare_fields,
    )

    write_report(
        reports_dir,
        query_id=f"{category}__{case_id}",
        request={"category": category, "case_id": case_id, "replay_inputs": repr(replay_inputs)},
        avalonia_rows=avalonia_rows,
        access_rows=access_rows,
        diff=diff,
        datadump_sha=sha,
    )

    assert diff.stats.matches, (
        f"replay-scan [{category}/{case_id}] diff has mismatches: "
        f"avalonia={diff.stats.rows_avalonia}, access={diff.stats.rows_access}, "
        f"only_in_avalonia={diff.stats.rows_only_in_avalonia}, "
        f"only_in_access={diff.stats.rows_only_in_access}, "
        f"value_mismatches={diff.stats.rows_value_mismatch}. "
        f"See reports/replay_scan/{category}__{case_id}/ for detail."
    )
