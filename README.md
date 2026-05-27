# cbdb-access-avalonia-parity

Differential testing harness comparing CBDB Avalonia desktop queries against
the CBDB Access automated test results, ensuring both stacks return identical
results when fed from the same Datadump.

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
    │ build_access_data │   │ build_sqlite (py)   │
    │  (Datadump→.mdb)  │   │  Python primary,    │
    │                   │   │  Docker MySQL fall. │
    └─────────┬─────────┘   └──────────┬──────────┘
              │                        │
              ▼                        ▼
    ┌───────────────────┐   ┌─────────────────────┐
    │  cbdb_data.mdb +  │   │   cbdb.sqlite       │
    │  CBDB_BJ_User.mdb │   │ (used by Avalonia)  │
    └─────────┬─────────┘   └──────────┬──────────┘
              │                        │
              ▼                        ▼
    ┌───────────────────┐   ┌─────────────────────┐
    │ Access driver     │   │ .NET test host →    │
    │ (pyodbc / VBA UI  │   │ Cbdb.App.Data       │
    │  via pywinauto)   │   │ Sqlite*QueryService │
    └─────────┬─────────┘   └──────────┬──────────┘
              │                        │
              └──────────┬─────────────┘
                         ▼
              ┌─────────────────────┐
              │  Differential diff  │
              │  reports/<query_id> │
              └─────────────────────┘
```

## Repository status

Initial skeleton. Implementation tracked phase-by-phase in `WORK_PLAN.md`
(English) and `WORK_PLAN.zh-CN.md` (Chinese, authoritative for project
decisions made in Chinese).

## Quick start (once implemented)

```powershell
# 1. Configure local paths
Copy-Item .env.sample .env
# edit .env with the real paths on your machine

# 2. Refresh external repos and rebuild the two databases
python scripts/refresh_external_repos.py
python scripts/build_all.py

# 3. Run the differential harness
pytest tests/
```

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
