"""Tests for cbdb_parity.avalonia_status_query — SQL builder behaviour."""

from __future__ import annotations

from cbdb_parity.avalonia_status_query import (
    StatusQueryRequest,
    _build_status_query_sql,
    status_query_field_names,
)

_MINIMAL_TEMPLATE = """\
WITH matched_people AS (
    SELECT b.c_personid FROM BIOG_MAIN b
    WHERE ($personKeyword IS NULL OR b.c_name LIKE $personKeyword)
      AND ($useIndexYear = 0 OR b.c_index_year BETWEEN $indexYearFrom AND $indexYearTo)
{dynastyFilter}
)
SELECT b.c_personid FROM STATUS_DATA sd
JOIN matched_people mp ON mp.c_personid = sd.c_personid
JOIN BIOG_MAIN b ON b.c_personid = sd.c_personid
WHERE 1 = 1
"""


def test_no_filters_substitutes_empty_dynasty_filter() -> None:
    request = StatusQueryRequest(limit=200)
    sql, params = _build_status_query_sql(_MINIMAL_TEMPLATE, request)
    assert "{dynastyFilter}" not in sql
    assert "sd.c_status_code IN" not in sql
    assert "b.c_index_addr_id IN" not in sql
    assert params["limit"] == 200


def test_status_codes_appends_in_clause() -> None:
    request = StatusQueryRequest(status_codes=("1", "2"), limit=50)
    sql, params = _build_status_query_sql(_MINIMAL_TEMPLATE, request)
    assert "sd.c_status_code IN (:statusCode0, :statusCode1)" in sql
    assert params["statusCode0"] == "1"
    assert params["statusCode1"] == "2"


def test_dynasty_filter_substitution() -> None:
    request = StatusQueryRequest(status_codes=("1",), dynasty_ids=(15, 16))
    sql, params = _build_status_query_sql(_MINIMAL_TEMPLATE, request)
    assert "AND b.c_dy IN (:dynastyId0, :dynastyId1)" in sql
    assert params["dynastyId0"] == 15


def test_place_filter_default_exact() -> None:
    request = StatusQueryRequest(status_codes=("1",), place_ids=(100, 200))
    sql, _ = _build_status_query_sql(_MINIMAL_TEMPLATE, request)
    assert "b.c_index_addr_id IN (:placeId0, :placeId1)" in sql
    assert "ZZZ_BELONGS_TO" not in sql


def test_place_filter_with_subordinate_units() -> None:
    request = StatusQueryRequest(
        status_codes=("1",), place_ids=(100,), include_subordinate_units=True
    )
    sql, _ = _build_status_query_sql(_MINIMAL_TEMPLATE, request)
    assert "b.c_index_addr_id IN (:placeId0)" in sql
    assert "ZZZ_BELONGS_TO bt WHERE bt.c_addr_id = b.c_index_addr_id" in sql


def test_limit_clamped_to_1_through_100000() -> None:
    _, p_low = _build_status_query_sql(_MINIMAL_TEMPLATE, StatusQueryRequest(limit=0))
    _, p_high = _build_status_query_sql(_MINIMAL_TEMPLATE, StatusQueryRequest(limit=999999))
    assert p_low["limit"] == 1
    assert p_high["limit"] == 100000


def test_order_by_status_label_then_person_then_sequence() -> None:
    sql, _ = _build_status_query_sql(_MINIMAL_TEMPLATE, StatusQueryRequest())
    assert "ORDER BY status_label, b.c_personid, sd.c_sequence" in sql
    assert "LIMIT :limit" in sql


def test_field_names_match_status_record_width() -> None:
    """36-name tuple = 36 fields in Cbdb.App.Core.StatusQueryRecord."""
    fields = status_query_field_names()
    assert len(fields) == 36
    assert fields[0] == "person_id"
    assert fields[14] == "status_code"  # SELECT col 14 = CAST(c_status_code AS TEXT)
    assert fields[35] == "notes"


def test_person_keyword_wraps_and_strips_quotes() -> None:
    request = StatusQueryRequest(person_keyword='  Wang "Anshi"  ')
    _, params = _build_status_query_sql(_MINIMAL_TEMPLATE, request)
    assert params["personKeyword"] == "%Wang Anshi%"


def test_blank_person_keyword_becomes_none() -> None:
    _, params = _build_status_query_sql(_MINIMAL_TEMPLATE, StatusQueryRequest(person_keyword="   "))
    assert params["personKeyword"] is None
