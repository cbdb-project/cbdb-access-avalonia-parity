# Query `office__office1_song` parity report

**Verdict**: PASS
**Generated**: 2026-05-30T07:25:57.239724+00:00
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
  "case_id": "office1_song",
  "replay_inputs": "OfficeQueryInputs(office_codes=[1], year_filter=YearFilter(mode='dynasty', from_year=None, to_year=None, from_dynasty=15, to_dynasty=15, from_dynasty_begin=960, to_dynasty_end=1279), use_office_years=False, office_from_year=None, office_to_year=None)"
}
```

See `diff.json` for full per-row detail; `avalonia.json` / `access.json`
hold the raw inputs (gitignored).

For root-cause analysis, edit `hypothesis.md` in this directory.
