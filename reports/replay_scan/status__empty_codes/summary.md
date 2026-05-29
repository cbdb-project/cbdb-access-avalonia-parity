# Query `status__empty_codes` parity report

**Verdict**: PASS
**Generated**: 2026-05-29T06:27:37.828823+00:00
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
  "category": "status",
  "case_id": "empty_codes",
  "replay_inputs": "StatusQueryInputs(status_codes=None, addr_ids=None, include_subunits=False, use_xy_radius=False, xy_narrow=True, year_mode='none', from_year=None, to_year=None, from_dynasty=-1, to_dynasty=-1, from_dynasty_begin=None, to_dynasty_end=None)"
}
```

See `diff.json` for full per-row detail; `avalonia.json` / `access.json`
hold the raw inputs (gitignored).

For root-cause analysis, edit `hypothesis.md` in this directory.
