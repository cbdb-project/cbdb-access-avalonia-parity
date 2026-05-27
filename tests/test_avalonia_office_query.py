"""Tests for cbdb_parity.avalonia_office_query — Python re-execution of
the Avalonia SqliteOfficeQueryService.QueryAsync SQL against cbdb.sqlite.

These tests pin the SQL-builder behaviour without needing the full CBDB
sqlite — they assert the template substitution, parameter binding, and
field-order contract.
"""

from __future__ import annotations

from cbdb_parity.avalonia_office_query import (
    OfficeQueryRequest,
    _build_office_query_sql,
    office_query_field_names,
)

_MINIMAL_TEMPLATE = """\
WITH matched_people AS (
    SELECT DISTINCT b.c_personid
    FROM BIOG_MAIN b
    WHERE ($personKeyword IS NULL OR b.c_name LIKE $personKeyword)
      AND ($useIndexYear = 0 OR b.c_index_year BETWEEN $indexYearFrom AND $indexYearTo)
{dynastyFilter}
)
SELECT
    b.c_personid,
    {personPlaceMatchExpr} AS person_place_match,
    {officePlaceMatchExpr} AS office_place_match,
    {placeWorkflowExpr} AS place_workflow
FROM POSTED_TO_OFFICE_DATA pto
JOIN matched_people mp ON mp.c_personid = pto.c_personid
LEFT JOIN POSTED_TO_ADDR_DATA pta ON pta.c_posting_id = pto.c_posting_id
WHERE 1 = 1
  AND ($useOfficeYear = 0
       OR (
           ($officeYearFrom IS NULL OR pto.c_firstyear >= $officeYearFrom)
           AND ($officeYearTo IS NULL OR pto.c_lastyear <= $officeYearTo)
       ))
"""


def test_no_filters_substitutes_unfiltered_expressions() -> None:
    """With no place / dynasty filters the template should bake in the
    `'Unfiltered'` / single-CASE expressions and zero dynasty WHERE."""
    request = OfficeQueryRequest(limit=200)
    sql, params = _build_office_query_sql(_MINIMAL_TEMPLATE, request)

    assert "{dynastyFilter}" not in sql
    assert "{personPlaceMatchExpr}" not in sql
    assert "{officePlaceMatchExpr}" not in sql
    assert "{placeWorkflowExpr}" not in sql
    # Unfiltered person-place uses the literal `'Unfiltered'`.
    assert "'Unfiltered' AS person_place_match" in sql
    # Unfiltered office-place still distinguishes 'No office place' for
    # rows with no POSTED_TO_ADDR_DATA join row.
    assert "WHEN pta.c_addr_id IS NULL THEN 'No office place'" in sql
    # Limit clamp matches Avalonia's [1, 10000].
    assert params["limit"] == 200
    # No office_codes => no AND-IN appended.
    assert "pto.c_office_id IN" not in sql


def test_office_codes_appends_in_clause() -> None:
    request = OfficeQueryRequest(office_codes=(7, 9, 11), limit=50)
    sql, params = _build_office_query_sql(_MINIMAL_TEMPLATE, request)
    assert "pto.c_office_id IN (:officeCode0, :officeCode1, :officeCode2)" in sql
    assert params["officeCode0"] == 7
    assert params["officeCode1"] == 9
    assert params["officeCode2"] == 11


def test_dynasty_filter_substitution() -> None:
    request = OfficeQueryRequest(office_codes=(7,), dynasty_ids=(15, 16))
    sql, params = _build_office_query_sql(_MINIMAL_TEMPLATE, request)
    # `{dynastyFilter}` gets the `AND b.c_dy IN (:dynastyId0, :dynastyId1)`
    # injection at every template occurrence.
    assert "AND b.c_dy IN (:dynastyId0, :dynastyId1)" in sql
    assert params["dynastyId0"] == 15
    assert params["dynastyId1"] == 16


def test_person_place_filter_adds_exact_clause_by_default() -> None:
    request = OfficeQueryRequest(
        office_codes=(7,),
        person_place_ids=(100, 200),
        include_subordinate_person_units=False,
    )
    sql, _ = _build_office_query_sql(_MINIMAL_TEMPLATE, request)
    assert "b.c_index_addr_id IN (:personPlaceId0, :personPlaceId1)" in sql
    # No subordinate-units branch.
    assert "ZZZ_BELONGS_TO bt WHERE bt.c_addr_id = b.c_index_addr_id" not in sql.split(
        "AND b.c_index_addr_id IN"
    )[1]


def test_person_place_filter_with_subordinate_units() -> None:
    request = OfficeQueryRequest(
        office_codes=(7,),
        person_place_ids=(100,),
        include_subordinate_person_units=True,
    )
    sql, _ = _build_office_query_sql(_MINIMAL_TEMPLATE, request)
    # Both forms present (exact OR subordinate).
    assert "b.c_index_addr_id IN (:personPlaceId0)" in sql
    assert "ZZZ_BELONGS_TO bt WHERE bt.c_addr_id = b.c_index_addr_id" in sql


def test_office_year_range_binds_endpoint_values() -> None:
    request = OfficeQueryRequest(
        office_codes=(7,),
        use_office_year_range=True,
        office_year_from=900,
        office_year_to=1100,
    )
    _, params = _build_office_query_sql(_MINIMAL_TEMPLATE, request)
    assert params["useOfficeYear"] == 1
    assert params["officeYearFrom"] == 900
    assert params["officeYearTo"] == 1100


def test_office_year_disabled_yields_null_endpoints() -> None:
    request = OfficeQueryRequest(office_codes=(7,))
    _, params = _build_office_query_sql(_MINIMAL_TEMPLATE, request)
    assert params["useOfficeYear"] == 0
    assert params["officeYearFrom"] is None
    assert params["officeYearTo"] is None


def test_limit_clamped_to_1_through_10000() -> None:
    low = OfficeQueryRequest(limit=0)
    high = OfficeQueryRequest(limit=99999)
    _, p_low = _build_office_query_sql(_MINIMAL_TEMPLATE, low)
    _, p_high = _build_office_query_sql(_MINIMAL_TEMPLATE, high)
    assert p_low["limit"] == 1
    assert p_high["limit"] == 10000


def test_order_by_limit_appended() -> None:
    request = OfficeQueryRequest(office_codes=(7,))
    sql, _ = _build_office_query_sql(_MINIMAL_TEMPLATE, request)
    assert "ORDER BY office_label, pto.c_firstyear, b.c_personid" in sql
    assert "LIMIT :limit" in sql


def test_field_names_count_matches_csharp_select_width() -> None:
    """The 65-column field tuple must stay in lockstep with the
    SqliteOfficeQueryService SELECT. Per the .cs source, every
    `reader.GetXxx(N)` reads SQL column N; the constructor's visual
    parameter order differs from SELECT order but there is no actual
    column swap to mirror here."""
    fields = office_query_field_names()
    assert len(fields) == 65
    # Column 57 is `posting_place_count.place_count`; 58 is `pto.c_source`.
    assert fields[57] == "office_place_count"
    assert fields[58] == "source_id"


def test_person_keyword_wraps_in_percent_signs() -> None:
    request = OfficeQueryRequest(person_keyword='  Wang "Anshi"  ')
    _, params = _build_office_query_sql(_MINIMAL_TEMPLATE, request)
    # Strips, removes embedded double-quotes, wraps in % for LIKE.
    assert params["personKeyword"] == "%Wang Anshi%"


def test_person_keyword_blank_becomes_none() -> None:
    request = OfficeQueryRequest(person_keyword="   ")
    _, params = _build_office_query_sql(_MINIMAL_TEMPLATE, request)
    assert params["personKeyword"] is None
