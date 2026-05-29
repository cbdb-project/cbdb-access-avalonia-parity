# Query `biog_basic_search` parity report

**Verdict**: PASS
**Generated**: 2026-05-29T20:07:44.684156+00:00
**Datadump SHA**: `ed294faed44b36e80169cae8815f83d9d9c5ca3cdb79520c8d058383ad52eb43`

## Stats
- Rows Avalonia: 50
- Rows Access: 50
- Matching: 50
- Only in Avalonia: 0
- Only in Access: 0
- Value mismatches (same key, different fields): 0

## Request
```json
{
  "limit": 50,
  "offset": 0,
  "keyword": null
}
```

See `diff.json` for full per-row detail; `avalonia.json` / `access.json`
hold the raw inputs (gitignored).

For root-cause analysis, edit `hypothesis.md` in this directory.
