# Query `office__empty_codes` parity report

**Verdict**: PASS
**Generated**: 2026-05-29T06:27:41.182368+00:00
**Datadump SHA**: `ed294faed44b36e80169cae8815f83d9d9c5ca3cdb79520c8d058383ad52eb43`

## Stats
- Rows Avalonia: 0
- Rows Access: 0
- Matching: 0
- Only in Avalonia: 0
- Only in Access: 0
- Value mismatches (same key, different fields): 0

## Request
```json
{
  "category": "office",
  "case_id": "empty_codes",
  "replay_inputs": "OfficeQueryInputs(office_codes=None, year_filter=YearFilter(mode='none', from_year=None, to_year=None, from_dynasty=-1, to_dynasty=-1, from_dynasty_begin=None, to_dynasty_end=None), use_office_years=False, office_from_year=None, office_to_year=None)"
}
```

See `diff.json` for full per-row detail; `avalonia.json` / `access.json`
hold the raw inputs (gitignored).

For root-cause analysis, edit `hypothesis.md` in this directory.
