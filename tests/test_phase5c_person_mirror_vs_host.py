"""Phase 5c-2: mirror-vs-host coverage for every PersonBrowser
accessor (11 per-person list accessors + GetDetailAsync + BIOG
basic SearchAsync).

Same shape as test_phase5b_mirror_vs_host_rows.py but
parametrized — each accessor gets a (mirror_fn, host_service)
pair, the test invokes both on the same fixture person and
asserts schema + value equality.

This is the load-bearing prerequisite for Phase 5c-final's
mirror-layer deletion: every mirror module the tests still call
into is paired with its real-C# equivalent here. A green run
means "the Python mirror is byte-equivalent to upstream C# on
this fixture", which lets 5c-final delete the mirror with
confidence.

Per WORK_PLAN.md §0 + §5b: any divergence is mirror-side; fix in
THIS repo, never upstream. Drift gets an entry in the
`_KNOWN_MIRROR_GAPS_*` allow-list with a comment naming the
upstream C# null-coercion / serialization line that explains it.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

# Phase 8a — every test in this module routes its host calls
# through the session-scoped ParityHostDaemon. The fixture
# (defined in tests/conftest.py) binds the daemon via
# `bind_active_daemon` so the existing `invoke_parity_host` and
# `invoke_person_accessor_via_host` call sites automatically
# pick it up without per-call wiring. The fixture skips
# cleanly when the local prereqs are missing.
pytestmark = pytest.mark.usefixtures("parity_host_daemon")


def _load_config_or_skip():
    """Skip only on a *missing* config (env not set up); a config
    that loads but raises a real error must surface, not silently
    skip the whole suite.
    """
    try:
        from cbdb_parity.config import load_config
    except ImportError:
        pytest.skip("cbdb_parity.config not importable")
    try:
        return load_config()
    except FileNotFoundError as exc:
        # .env / avalonia_repo not configured — legitimate skip on a
        # dev machine without the harness wired up. Anything else
        # (ValueError, KeyError, ...) is a real bug we must see.
        pytest.skip(f"config not configured: {exc}")


# Upstream subtrees the ParityHost actually links against — Codex
# round 5c-2 flagged that the previous heuristic silently passed if
# a subtree disappeared (it `return`ed instead of failing). We now
# fail loudly if either subtree is missing AND a real config was
# loaded.
_UPSTREAM_SUBTREES: tuple[str, ...] = ("Cbdb.App.Core", "Cbdb.App.Data")


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
    dll_mtime = host_dll.stat().st_mtime
    missing = [s for s in _UPSTREAM_SUBTREES if not (avalonia_repo / s).is_dir()]
    if missing:
        # A configured AVALONIA_REPO that's missing a subtree the
        # host links against is a hard error, not a skip — the host
        # DLL we just loaded was built against THIS subtree layout.
        raise AssertionError(
            f"AVALONIA_REPO={avalonia_repo} is missing required "
            f"subtree(s) {missing}; the ParityHost DLL was built "
            f"against this layout and would crash."
        )
    for sub in _UPSTREAM_SUBTREES:
        upstream_dir = avalonia_repo / sub
        for ext in ("*.cs", "*.csproj"):
            for src in upstream_dir.rglob(ext):
                rel_parts = src.relative_to(upstream_dir).parts
                if any(p.lower() in ("bin", "obj") for p in rel_parts):
                    continue
                if src.stat().st_mtime > dll_mtime:
                    pytest.skip(
                        f"ParityHost DLL is older than upstream "
                        f"{src.relative_to(avalonia_repo)}; rebuild required."
                    )


def _strip_id_fields(rows: list[dict[str, Any]], id_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    """Some mirror functions splice raw ID columns into the row dict
    for diff-keying that the C# wire-format doesn't expose. Strip
    them before comparing.
    """
    if not id_fields:
        return rows
    keys_to_drop = set(id_fields)
    return [{k: v for k, v in r.items() if k not in keys_to_drop} for r in rows]


def _assert_rows_equal(
    label: str,
    mirror_rows: list[dict[str, Any]],
    host_rows: list[dict[str, Any]],
    *,
    ignore_fields: frozenset[str] = frozenset(),
) -> None:
    """Same three-class drift gate as Phase 5b
    (`test_phase5b_mirror_vs_host_rows._assert_rows_equal`).
    """
    assert len(mirror_rows) == len(host_rows), (
        f"{label}: row count differs — mirror={len(mirror_rows)} "
        f"host={len(host_rows)}."
    )
    for i, (m, h) in enumerate(zip(mirror_rows, host_rows, strict=True)):
        mirror_keys = set(m) - ignore_fields
        host_keys = set(h) - ignore_fields
        assert mirror_keys == host_keys, (
            f"{label}: row {i} schema drift — "
            f"mirror_only={sorted(mirror_keys - host_keys)} "
            f"host_only={sorted(host_keys - mirror_keys)}."
        )
        for key in mirror_keys:
            assert m[key] == h[key], (
                f"{label}: row {i} field {key!r} differs — "
                f"mirror={m[key]!r} host={h[key]!r}"
            )


# Phase 7d multi-fixture: every per-person accessor is now
# parametrised across three fixtures spanning two dynasties and
# different data densities. The original single-fixture run
# (Wang Anshi only) gave us no signal on dynasty-boundary edge
# cases (Tang names use Pinyin differently from Song, alt-names
# distributions differ), and a regression that broke one branch
# of the upstream SQL on Tang-era rows could pass the suite.
#
# Verified at fixture-design time (2026-05-31): all three persons
# exist in BIOG_MAIN AND have non-empty rows for at least one of
# the high-fanout accessors (addresses, kinships, writings).
#
# - 1762 = Wang Anshi (Northern Song, c_index_year=1021) —
#   canonical Phase 5c-1 fixture; rich across every accessor.
# - 32540 = Li Bai (Tang, c_index_year=701) — different dynasty,
#   different Pinyin convention, sparser alt-names.
# - 3257 = Zhu Xi (Southern Song, c_index_year=1130) — major
#   neo-Confucian scholar; dense writings + institutions.
_PERSON_FIXTURES: tuple[tuple[int, str], ...] = (
    (1762, "wang_anshi"),
    (32540, "li_bai"),
    (3257, "zhu_xi"),
)

# Tests that only assume a Tier-2 row exists on the canonical
# fixture (e.g. the older 5c-1/5c-2 single-row checks) still use
# this as a default; the parametrised variant is the multi-fixture
# extension.
_FIXTURE_PERSON = 1762


# Hard-coded allowlist of spliced raw-ID columns per mirror.
# Codex 5c-2 caught that importing each mirror's *_id_field_names()
# at test time means the test under-tests anything that mirror
# decides to mark as "ID". Keep this table in the test, not the
# mirror, so the suite is an independent oracle: if a mirror starts
# emitting a new key, the suite notices via the symmetric schema
# check rather than silently stripping it.
_MIRROR_ID_FIELDS: dict[str, tuple[str, ...]] = {
    "addresses":    ("addr_type_code", "addr_id"),
    "altnames":     ("name_type_code", "source_id"),
    "writings":     ("role_id",),
    "entries":      ("entry_code",),
    "statuses":     ("status_code",),
    "possessions":  (),
    "events":       ("event_code",),
    "associations": ("assoc_code",),
    "sources":      ("text_id",),
    "institutions": ("inst_name_code", "inst_code"),
}


# Codex round on the 7d parametrise flagged a real false-pass class:
# `_run_person_pair` accepted `[] == []` as a pass, so any
# (accessor, person_id) combo with zero rows on the canonical
# build silently passed without exercising the upstream SQL at all.
#
# This explicit allow-list documents the combos where ZERO rows is
# the expected, non-regression state on the current canonical
# dataset (Datadump 2026-04-30). Any combo NOT in this set must
# produce a non-empty host row list; if it doesn't, the test fails
# with a "fixture produced zero rows where some were expected"
# diagnostic — that catches a real regression instead of hiding it.
#
# Membership rationale (verified at fixture-design time via direct
# COUNT(*) probes on cbdb.sqlite, 2026-05-31):
#   - possessions: POSSESSION_DATA has zero rows for all three
#     fixtures. POSSESSION_DATA is sparsely populated in CBDB
#     overall; the canonical fixtures don't happen to be among
#     the few people who have entries.
#   - institutions: BIOG_INST_DATA same situation.
#   - events for li_bai / zhu_xi: EVENTS_DATA is also sparse;
#     wang_anshi has 1 event, the others have 0.
#
# If any of these starts returning non-empty rows on a future
# dump, the assertion in `_run_person_pair` will fail and we'll
# refresh this list with the new ground truth. Inverse direction
# (a combo expected non-empty going empty) is the regression
# signal we wanted from 7d in the first place.
_EXPECTED_EMPTY: frozenset[tuple[str, int]] = frozenset({
    ("possessions",  1762),
    ("possessions",  32540),
    ("possessions",  3257),
    ("institutions", 1762),
    ("institutions", 32540),
    ("institutions", 3257),
    ("events",       32540),
    ("events",       3257),
})


def _run_person_pair(
    service: str,
    mirror_fn,
    *,
    id_fields: tuple[str, ...] = (),
    ignore_fields: frozenset[str] = frozenset(),
    person_id: int = _FIXTURE_PERSON,
    label: str | None = None,
) -> None:
    cfg = _load_config_or_skip()
    _prereqs_or_skip(cfg.avalonia_repo)
    sqlite_path = cfg.build_output_dir / "cbdb.sqlite"
    if not sqlite_path.is_file():
        pytest.skip(f"sqlite not built at {sqlite_path}")

    from cbdb_parity.parity_host import invoke_person_accessor_via_host

    tag = f"{service}/{label}" if label is not None else service

    avalonia_data = cfg.avalonia_repo / "Cbdb.App.Data"
    mirror_rows = mirror_fn(
        sqlite_path, person_id, avalonia_data_dir=avalonia_data,
    )
    host_rows = invoke_person_accessor_via_host(
        service, sqlite_path, person_id, avalonia_repo=cfg.avalonia_repo,
    )

    # Phase 7d codex round: false-pass guard. A combo not in
    # `_EXPECTED_EMPTY` must produce at least one row on the
    # canonical dataset, otherwise the parametrised case provides
    # no signal on this accessor at all.
    expected_empty = (service, person_id) in _EXPECTED_EMPTY
    if expected_empty:
        assert len(host_rows) == 0, (
            f"{tag}: host returned {len(host_rows)} rows but the "
            f"combo is in _EXPECTED_EMPTY. The canonical dataset has "
            f"started populating this surface for this person; "
            f"refresh _EXPECTED_EMPTY against the new ground truth."
        )
    else:
        assert len(host_rows) > 0, (
            f"{tag}: host returned 0 rows but the combo is NOT in "
            f"_EXPECTED_EMPTY. Either the canonical dataset stopped "
            f"populating this surface for this person (real "
            f"regression — investigate upstream / Datadump), or "
            f"the fixture choice is wrong for this accessor and "
            f"the combo should be added to _EXPECTED_EMPTY with a "
            f"recorded rationale."
        )

    # Strip the mirror's spliced raw-ID columns so the schema check
    # sees only the upstream-record-shaped fields.
    mirror_clean = _strip_id_fields(mirror_rows, id_fields)
    _assert_rows_equal(
        tag, mirror_clean, host_rows, ignore_fields=ignore_fields,
    )


# Each entry below is one PersonBrowser accessor. The `id_fields`
# tuple lists raw IDs the mirror splices in for diff-keying that
# don't appear in the C# wire format; `_strip_id_fields` removes
# them before comparing. `ignore_fields` covers any per-accessor
# documented mirror gap (none discovered yet for these — all
# pairs are currently byte-equivalent).


@pytest.mark.parametrize("person_id,label", _PERSON_FIXTURES, ids=lambda v: str(v))
def test_addresses_mirror_vs_host(person_id: int, label: str) -> None:
    from cbdb_parity.avalonia_addresses import addresses_query
    _run_person_pair(
        "addresses", addresses_query,
        id_fields=_MIRROR_ID_FIELDS["addresses"],
        person_id=person_id, label=label,
    )


@pytest.mark.parametrize("person_id,label", _PERSON_FIXTURES, ids=lambda v: str(v))
def test_altnames_mirror_vs_host(person_id: int, label: str) -> None:
    from cbdb_parity.avalonia_altnames import altnames_query
    _run_person_pair(
        "altnames", altnames_query,
        id_fields=_MIRROR_ID_FIELDS["altnames"],
        person_id=person_id, label=label,
    )


@pytest.mark.parametrize("person_id,label", _PERSON_FIXTURES, ids=lambda v: str(v))
def test_writings_mirror_vs_host(person_id: int, label: str) -> None:
    from cbdb_parity.avalonia_writings import writings_query
    _run_person_pair(
        "writings", writings_query,
        id_fields=_MIRROR_ID_FIELDS["writings"],
        person_id=person_id, label=label,
    )


@pytest.mark.parametrize("person_id,label", _PERSON_FIXTURES, ids=lambda v: str(v))
def test_entries_mirror_vs_host(person_id: int, label: str) -> None:
    from cbdb_parity.avalonia_entries import entries_query
    _run_person_pair(
        "entries", entries_query,
        id_fields=_MIRROR_ID_FIELDS["entries"],
        person_id=person_id, label=label,
    )


@pytest.mark.parametrize("person_id,label", _PERSON_FIXTURES, ids=lambda v: str(v))
def test_statuses_person_mirror_vs_host(person_id: int, label: str) -> None:
    from cbdb_parity.avalonia_statuses_person import statuses_person_query
    _run_person_pair(
        "statuses", statuses_person_query,
        id_fields=_MIRROR_ID_FIELDS["statuses"],
        person_id=person_id, label=label,
    )


@pytest.mark.parametrize("person_id,label", _PERSON_FIXTURES, ids=lambda v: str(v))
def test_possessions_mirror_vs_host(person_id: int, label: str) -> None:
    from cbdb_parity.avalonia_possessions import possessions_query
    _run_person_pair(
        "possessions", possessions_query,
        id_fields=_MIRROR_ID_FIELDS["possessions"],
        person_id=person_id, label=label,
    )


@pytest.mark.parametrize("person_id,label", _PERSON_FIXTURES, ids=lambda v: str(v))
def test_events_mirror_vs_host(person_id: int, label: str) -> None:
    from cbdb_parity.avalonia_events import events_query
    _run_person_pair(
        "events", events_query,
        id_fields=_MIRROR_ID_FIELDS["events"],
        person_id=person_id, label=label,
    )


@pytest.mark.parametrize("person_id,label", _PERSON_FIXTURES, ids=lambda v: str(v))
def test_associations_mirror_vs_host(person_id: int, label: str) -> None:
    from cbdb_parity.avalonia_associations import associations_query
    _run_person_pair(
        "associations", associations_query,
        id_fields=_MIRROR_ID_FIELDS["associations"],
        person_id=person_id, label=label,
    )


@pytest.mark.parametrize("person_id,label", _PERSON_FIXTURES, ids=lambda v: str(v))
def test_sources_mirror_vs_host(person_id: int, label: str) -> None:
    from cbdb_parity.avalonia_sources import sources_query
    _run_person_pair(
        "sources", sources_query,
        id_fields=_MIRROR_ID_FIELDS["sources"],
        person_id=person_id, label=label,
    )


@pytest.mark.parametrize("person_id,label", _PERSON_FIXTURES, ids=lambda v: str(v))
def test_institutions_mirror_vs_host(person_id: int, label: str) -> None:
    from cbdb_parity.avalonia_institutions import institutions_query
    _run_person_pair(
        "institutions", institutions_query,
        id_fields=_MIRROR_ID_FIELDS["institutions"],
        person_id=person_id, label=label,
    )


@pytest.mark.parametrize("person_id,label", _PERSON_FIXTURES, ids=lambda v: str(v))
def test_detail_mirror_vs_host(person_id: int, label: str) -> None:
    """PersonBrowserService.GetDetailAsync — returns a SINGLE
    PersonDetail (not a list), so the via_host call is a dict, not a
    list. Test asserts the mirror dict and host dict match key-for-
    key and value-for-value, for each parametrised person.
    """
    cfg = _load_config_or_skip()
    _prereqs_or_skip(cfg.avalonia_repo)
    sqlite_path = cfg.build_output_dir / "cbdb.sqlite"
    if not sqlite_path.is_file():
        pytest.skip(f"sqlite not built at {sqlite_path}")

    from cbdb_parity.avalonia_detail import detail_query
    from cbdb_parity.parity_host import invoke_parity_host

    avalonia_data = cfg.avalonia_repo / "Cbdb.App.Data"
    mirror_rows = detail_query(
        sqlite_path, person_id, avalonia_data_dir=avalonia_data,
    )
    host_row = invoke_parity_host(
        "detail", sqlite_path, {"person_id": person_id},
        avalonia_repo=cfg.avalonia_repo,
    )
    assert len(mirror_rows) == 1, (
        f"detail/{label}: mirror returned {len(mirror_rows)} rows"
    )
    assert isinstance(host_row, dict), (
        f"detail/{label}: host returned {type(host_row).__name__}"
    )
    # `fields` (PersonFieldValue[]) is the dynamic-field block the
    # upstream PersonDetail record populates from PersonExtra2024
    # lookups; the mirror never ported it. 5c-final replaces the
    # mirror with a via_host delegate, at which point this gap
    # disappears. Allow it here so the rest of the schema is gated.
    _assert_rows_equal(
        f"detail/{label}", mirror_rows, [host_row],
        ignore_fields=frozenset({"fields"}),
    )


def test_biog_basic_mirror_vs_host() -> None:
    """SqlitePersonBrowserService.SearchAsync — no-keyword branch
    (corpus-wide BIOG_MAIN prefix). limit=50 from offset 0 to get
    a deterministic prefix.
    """
    cfg = _load_config_or_skip()
    _prereqs_or_skip(cfg.avalonia_repo)
    sqlite_path = cfg.build_output_dir / "cbdb.sqlite"
    if not sqlite_path.is_file():
        pytest.skip(f"sqlite not built at {sqlite_path}")

    from cbdb_parity.avalonia_biog_basic import biog_basic_query
    from cbdb_parity.parity_host import invoke_parity_host

    limit = 50
    mirror_rows = biog_basic_query(
        sqlite_path, limit=limit, offset=0,
        avalonia_repo=cfg.avalonia_repo,
    )
    host_rows = invoke_parity_host(
        "biog_basic", sqlite_path,
        {"keyword": None, "limit": limit, "offset": 0},
        avalonia_repo=cfg.avalonia_repo,
    )
    assert isinstance(host_rows, list), f"host returned {type(host_rows).__name__}"
    _assert_rows_equal("biog_basic", mirror_rows, host_rows)


# Phase 6d keyword coverage. The two non-no-keyword branches of
# SqlitePersonBrowserService.SearchAsync are distinguished by
# `int.TryParse(normalized, ...)`:
#   - numeric keyword → person_id filter (single-row exact match)
#   - non-numeric    → fuzzy LIKE across name fields + ALTNAME_DATA
# Phase 6d adds host-vs-mirror coverage for both. The mirror
# (`avalonia_biog_basic.biog_basic_query`) is a thin via_host
# wrapper after 5c-final, so this test really gates the wrapper's
# keyword-passthrough + dataclass-JSON serialisation, not a second
# upstream implementation.


def test_biog_basic_person_id_keyword_mirror_vs_host() -> None:
    """Numeric keyword → person_id exact match branch.

    `keyword="1762"` (Wang Anshi) lands in
    `int.TryParse(...) → hasPersonIdKeyword=true` → single-row
    result by `b.c_personid = $personId`. Verifies (a) the
    upstream branch is reachable through both the dict path and
    the dataclass-mirror path, and (b) both produce the same
    single PersonListItem.
    """
    cfg = _load_config_or_skip()
    _prereqs_or_skip(cfg.avalonia_repo)
    sqlite_path = cfg.build_output_dir / "cbdb.sqlite"
    if not sqlite_path.is_file():
        pytest.skip(f"sqlite not built at {sqlite_path}")

    from cbdb_parity.avalonia_biog_basic import biog_basic_query
    from cbdb_parity.parity_host import invoke_parity_host

    keyword = "1762"  # Wang Anshi
    mirror_rows = biog_basic_query(
        sqlite_path, keyword=keyword, limit=50, offset=0,
        avalonia_repo=cfg.avalonia_repo,
    )
    host_rows = invoke_parity_host(
        "biog_basic", sqlite_path,
        {"keyword": keyword, "limit": 50, "offset": 0},
        avalonia_repo=cfg.avalonia_repo,
    )
    assert isinstance(host_rows, list)
    # `hasPersonIdKeyword` branch returns exactly one row for an
    # existing person_id.
    assert len(host_rows) == 1, (
        f"person_id keyword '{keyword}' should match exactly one "
        f"BIOG_MAIN row; got {len(host_rows)}"
    )
    assert host_rows[0].get("person_id") == 1762
    _assert_rows_equal("biog_basic (person_id keyword)", mirror_rows, host_rows)


def test_biog_basic_fuzzy_keyword_mirror_vs_host() -> None:
    """Non-numeric keyword → fuzzy LIKE across BIOG_MAIN name
    columns UNION ALTNAME_DATA name columns.

    Codex round on the first cut pointed out that a keyword that
    hits BIOG_MAIN.c_name_chn directly (e.g. "王安石") would not
    actually prove the ALTNAME_DATA arm fires: a regression that
    drops the UNION clause could still pass. We use "獾郎"
    instead — one of Wang Anshi's alt-names (沪 sobriquet
    "Huanlang") — verified at fixture-build time to:
      - have ZERO matches in any BIOG_MAIN primary name column,
      - and exactly ONE match in ALTNAME_DATA (Wang Anshi only).
    Any non-empty result therefore exercises the ALTNAME_DATA arm
    specifically. A regression that drops the UNION makes this
    test report 0 rows and fail.
    """
    cfg = _load_config_or_skip()
    _prereqs_or_skip(cfg.avalonia_repo)
    sqlite_path = cfg.build_output_dir / "cbdb.sqlite"
    if not sqlite_path.is_file():
        pytest.skip(f"sqlite not built at {sqlite_path}")

    from cbdb_parity.avalonia_biog_basic import biog_basic_query
    from cbdb_parity.parity_host import invoke_parity_host

    keyword = "獾郎"
    mirror_rows = biog_basic_query(
        sqlite_path, keyword=keyword, limit=200, offset=0,
        avalonia_repo=cfg.avalonia_repo,
    )
    host_rows = invoke_parity_host(
        "biog_basic", sqlite_path,
        {"keyword": keyword, "limit": 200, "offset": 0},
        avalonia_repo=cfg.avalonia_repo,
    )
    assert isinstance(host_rows, list)
    assert len(host_rows) == 1, (
        f"alt-name-only keyword '{keyword}' should match exactly "
        f"one person via ALTNAME_DATA; got {len(host_rows)} — the "
        f"UNION arm of SearchAsync may be broken or unreachable."
    )
    assert host_rows[0].get("person_id") == 1762, (
        f"alt-name-only keyword '{keyword}' should resolve to "
        f"Wang Anshi (1762); got {host_rows[0].get('person_id')}"
    )
    _assert_rows_equal("biog_basic (alt-name keyword)", mirror_rows, host_rows)


def test_postings_mirror_vs_host() -> None:
    """Phase 5c-final left postings as NotImplementedError because
    GetPostingsAsync returns a nested PersonPostingItem wire format
    that the Phase 4 raw-row pair test was not built around. The
    mirror-vs-host check therefore can't run here — see
    `cbdb_parity.avalonia_postings` for the unblock options.
    """
    pytest.skip(
        "postings mirror raises NotImplementedError after 5c-final "
        "(nested PersonPostingItem wire format vs raw-row diff). "
        "See cbdb_parity.avalonia_postings for unblock paths."
    )
