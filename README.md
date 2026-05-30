# cbdb-access-avalonia-parity

Differential testing harness comparing CBDB Avalonia desktop queries against
the CBDB Access automated test results, ensuring both stacks return identical
results when fed from the same Datadump.

> **Scope contract** (see `WORK_PLAN.md §0`):
>
> **§0.a — No upstream modifications.** This repository is a
> **detection / parity test harness**. It surfaces and documents
> Avalonia ↔ Access disagreements via `reports/known_issues.md`; it
> **MUST NOT modify the upstream Avalonia codebase**
> (`cbdb-desktop-app`) or any other repository. The right action
> chain is: (1) write/run the parity test, (2) record the divergence
> in `reports/known_issues.md` with a `Suppress until …` clause,
> (3) let the test skip gracefully until upstream patches.
>
> **§0.b — No transcription.** This repo never re-implements
> upstream logic in Python. Avalonia-side tests call
> `cbdb-desktop-app`'s real services through `Cbdb.App.ParityHost`;
> Access-side tests call `cbdb-user-mdb-tests`'s
> `cbdb_replay.lookat*` modules directly. Hand-extracted SQL or
> hand-ported state machines on either side are forbidden.

## What this repo does

For **every query feature** implemented in the
[CBDB Avalonia desktop app](https://github.com/frankslin/cbdb-desktop-app),
this harness:

1. Builds an Access stack (generated `cbdb_data.mdb` + fixed `CBDB_BJ_User.mdb`)
   and an Avalonia SQLite database **from the same Datadump**, so any
   difference observed is logic, not data.
2. Runs the equivalent query against both stacks.
3. Normalises and diffs the two result sets.
4. Records each Access ↔ Avalonia disagreement together with a root cause.

The harness reuses the differential-testing pattern pioneered in
[cbdb-user-mdb-tests](https://github.com/cbdb-project/cbdb-user-mdb-tests).

## Architecture at a glance

```
              ┌───────────────────────────┐
              │  Datadump (latest .tar.gz)│
              └────────────┬──────────────┘
                           │
                ┌──────────┴───────────┐
                │                      │
                ▼                      ▼
    ┌───────────────────┐   ┌─────────────────────┐
    │ build_mdb (py)    │   │ build_sqlite (py)   │
    │  Datadump → mdb   │   │  Datadump → sqlite  │
    │  (MariaDB cache)  │   │  (MariaDB cache)    │
    └─────────┬─────────┘   └──────────┬──────────┘
              │                        │
              ▼                        ▼
    ┌───────────────────┐   ┌─────────────────────┐
    │  cbdb_data.mdb    │   │   cbdb.sqlite       │
    └─────────┬─────────┘   └──────────┬──────────┘
              │                        │
              ▼                        ▼
    ┌───────────────────┐   ┌─────────────────────┐
    │ cbdb_replay.      │   │ Cbdb.App.ParityHost │
    │ lookat* (Python   │   │ (.NET console →     │
    │  bridge via       │   │  upstream services  │
    │  pyodbc + sys.path)│  │  via ProjectRef)    │
    └─────────┬─────────┘   └──────────┬──────────┘
              │                        │
              └──────────┬─────────────┘
                         ▼
              ┌─────────────────────┐
              │  Differential diff  │
              │  reports/<query_id> │
              └─────────────────────┘
```

Both arms call **upstream code directly** per `WORK_PLAN.md §0.b`:
the Avalonia arm invokes `cbdb-desktop-app`'s real
`Sqlite*QueryService` / `SqlitePersonBrowserService` via the
ParityHost console (Phase 5); the Access arm invokes
`cbdb-user-mdb-tests`'s VBA-historical `cbdb_replay.lookat*`
scripts via Python (Phase 3c/3d/3e + Phase 6a).

## Repository status

Phases 1–8 landed (2026-05-27 → 2026-05-31). Current suite:
**387 passed, 7 skipped, 1 xfailed**. Implementation is tracked
phase-by-phase in `WORK_PLAN.md` (English) and
`WORK_PLAN.zh-CN.md` (Chinese, authoritative for project
decisions made in Chinese). Both `WORK_PLAN.md §9` and
`WORK_PLAN.zh-CN.md §9` carry a Post-Phase-7 status block
enumerating the active suppressions and their re-arm
conditions.

ParityHost runs in two modes (Phase 7h + Phase 8a binding):
one-shot via `dotnet run` for ad-hoc callers, and a
long-lived NDJSON daemon that the
`parity_host_daemon` pytest fixture binds for the whole
session — the host-using subset of the suite drops from
~150s to ~61s under the binding.

§0.b-compliant cross-engine pair tests at HEAD:
- Tier 1: `entry`, `office`, `status` (each via `cbdb_replay.lookat*`).
- Tier 2: `kinships` (1-hop direct branch via
  `cbdb_replay.lookatkinship`; Phase 6a rewire).

Avalonia-side correctness for every other PersonBrowser surface is
gated by `tests/test_phase5c_person_mirror_vs_host.py`, which calls
the real upstream service through the ParityHost. See
`reports/known_issues.md` for the surfaces (12 + associations) that
have no §0.b-compliant Access oracle.

## Quick start

```powershell
# 1. Configure local paths
Copy-Item .env.sample .env
# edit .env with the real paths on your machine

# 2. Install (uv-managed venv recommended; pyodbc + pypyodbc are
#    Windows-only and live in the [access] extra)
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev,harness,access]"

# 3. Build both databases from the latest Datadump.
#    `build-all` refreshes the four external repos, picks the newest
#    cbdb_data_YYYYMMDD.tar.gz, then writes cbdb.sqlite AND cbdb_data.mdb
#    to .env's BUILD_OUTPUT_DIR. SHA-anchored — re-runs are cached.
cbdb-parity-build-all
# or, individual sub-builders:
#     cbdb-parity-build-sqlite
#     cbdb-parity-build-mdb

# 4. Run the differential harness. Per-query reports under reports/.
#    The entry-pair smoke test requires both DBs to be present AND
#    anchored to the same Datadump SHA per build_manifest.json
#    (the strict-pipeline rule from WORK_PLAN §1); it skips cleanly
#    otherwise.
pytest tests/
```

The pre-flight `cbdb-parity-refresh` is still callable on its own if you
just want to `git pull --ff-only` the four external repos without
building anything.

After a parity run, regenerate the top-level dashboard with:

```powershell
cbdb-parity-summary             # writes reports/SUMMARY.md from cwd
# or
cbdb-parity-summary --reports-dir <path>
```

`reports/known_issues.md` is hand-maintained and is not regenerated.

## External dependencies (configured via `.env`)

| Key | What it is |
|---|---|
| `DATADUMP_DIR` | Folder of `cbdb_data_YYYYMMDD.tar.gz` archives. Latest is picked automatically. |
| `CBDB_USER_MDB` | Fixed path to `CBDB_BJ_User.mdb` (Access UI front-end). |
| `ACCESS_TESTS_REPO` | Local clone of [cbdb-user-mdb-tests](https://github.com/cbdb-project/cbdb-user-mdb-tests). |
| `AVALONIA_REPO` | Local clone of [cbdb-desktop-app](https://github.com/frankslin/cbdb-desktop-app). |
| `ONLINE_SERVER_REPO` | Local clone of [cbdb-online-main-server](https://github.com/cbdb-project/cbdb-online-main-server). |
| `MYSQL2ACCESS_DIR` | Local `mysql2access` working folder (Datadump → Access port). |
| `ACCESS_MYSQL_TRANSFER_REPO` | Local clone of [accessAndMySQLTransfer](https://github.com/cbdb-project/accessAndMySQLTransfer). |
| `BUILD_OUTPUT_DIR` | Scratch folder for generated `cbdb_data.mdb` and `cbdb.sqlite` (gitignored). |

`.env.sample` is committed with placeholder values; `.env` is gitignored.

## License

Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International
(CC BY-NC-SA 4.0). See [`LICENSE`](LICENSE).
