# Work Plan

## 0. Scope contract (read first)

This repository is a **detection / parity test harness**. Every
contributor — human or agent — operates under the following rules.

### 0.a — No upstream modifications
- We surface Avalonia ↔ Access disagreements, document them in
  `reports/known_issues.md`, and let the parity gate skip them via
  `Suppress until …` clauses.
- We **do not modify the upstream Avalonia codebase**
  (`cbdb-desktop-app`) or any other repository — neither locally nor
  by pushing branches. Even when a parity test makes a bug obvious,
  the fix belongs to the team that owns that codebase.
- When a parity test fails because of a documented upstream bug, the
  resolution is **always**: re-arm the auto-skip, link the
  `known_issues.md` entry, raise the issue with the upstream team
  separately. Never patch the other repo from here.

### 0.b — No transcription (added 2026-05-30)
This repo never re-implements upstream logic in Python. Every test
must call **the upstream code itself**, not a Python equivalent of
it. Concretely:

- **Avalonia side**: tests invoke `cbdb-desktop-app`'s real services
  via `Cbdb.App.ParityHost` (see Phase 5). Hand-extracting SQL from
  `Sqlite*Service.cs` and re-running it through Python `sqlite3`,
  hand-porting a BFS state machine, or otherwise "mirroring what
  the C# does" in Python — all forbidden as of Phase 5c-final. The
  Phase 3–4 mirror layer (`cbdb_parity/avalonia_query_sql.py` +
  `avalonia_*` SQL-extract path) is retired.
- **Access side**: tests invoke `cbdb-user-mdb-tests`'s
  `cbdb_replay.lookat*` modules — the historical, user-validated
  query scripts that constitute the Access-side "real code". The
  pre-existing pattern in `cbdb_parity/access_query.py` /
  `access_office_query.py` / `access_status_query.py` (Phase 3c/3d/3e)
  is the template. Hand-writing `_ACCESS_SQL` strings inside
  `cbdb_parity/access_*.py` to recreate Avalonia's joins is the
  Access-side equivalent of mirror-layer transcription and is
  equally forbidden going forward.
- **Implication**: any Tier-2 surface for which neither side has
  a "real code" to call (e.g. Phase 4 per-person accessors that
  have no `cbdb_replay.lookat*` analogue) **cannot** have a Phase 4
  pair test under this rule. Use Phase 5c's mirror-vs-host check as
  the Avalonia-side oracle and document the Access-side gap in
  `reports/known_issues.md`. See Phase 6 for the cleanup plan.

The companion `cbdb-desktop-app` repo on the user's machine is
treated as a read-only reference. Local edits to that tree, and
pushes to any of its remotes, are explicitly out-of-scope for any
`/goal` directed at this repository.

## 1. Objective
Build an independent comparison harness in `cbdb-access-avalonia-parity` that, for **every query feature** in the CBDB Avalonia desktop app (`cbdb-desktop-app`), runs the equivalent query against a CBDB Access stack and diffs the results. The harness must (a) reuse the test-design ideas from `cbdb-user-mdb-tests`, (b) feed both stacks from the **same** Datadump so any difference is logic, not data, and (c) report each Access ↔ Avalonia disagreement with a root cause.

Note: both `cbdb-user-mdb-tests` and `cbdb-desktop-app` already contain partial sketches of this comparison work (e.g. `cbdb-user-mdb-tests/data/cbdb_online_sqlite/`, `cbdb-user-mdb-tests/.external/cbdb-desktop-app/`). The decision is to do this in its own repo rather than continue those sketches.

**Strict-pipeline rule (no substitutions).** The build pipeline goes
`Datadump → cbdb_data.mdb` AND `Datadump → cbdb.sqlite` in order, both
from the *same* Datadump archive. Phase 3's differential harness MUST
consume those generated artefacts. Pre-existing mdb files on the user's
machine (e.g. `CBDB_BJ_20260430/CBDB_20260430_DATA.mdb`) are NOT
acceptable substitutes — they were built from a different Datadump and
would silently inject data-version drift into every parity comparison,
which is the exact failure mode this repo is supposed to prevent.
Phase 1.3b (the Datadump → mdb writer) is on the critical path; nothing
downstream may shortcut around it.

## 2. Inputs (sourced via `.env`, never copied into the repo)

| Key | What it points to | Example placeholder |
|---|---|---|
| `DATADUMP_DIR` | Folder of `cbdb_data_YYYYMMDD.tar.gz` archives (auto-pick latest). | `D:\path\to\Datadump` |
| `CBDB_USER_MDB` | Fixed `CBDB_BJ_User.mdb` (Access UI front-end). | `C:\path\to\CBDB_BJ_User.mdb` |
| `ACCESS_TESTS_REPO` | Local clone of `cbdb-user-mdb-tests`. | `C:\path\to\cbdb-user-mdb-tests` |
| `AVALONIA_REPO` | Local clone of `cbdb-desktop-app`. | `C:\path\to\cbdb-desktop-app` |
| `ONLINE_SERVER_REPO` | Local clone of `cbdb-online-main-server`. | `C:\path\to\cbdb-online-main-server` |
| `MYSQL2ACCESS_DIR` | Local working folder for Datadump → Access conversion (not a git repo). | `C:\path\to\mysql2access` |
| `ACCESS_MYSQL_TRANSFER_REPO` | Local clone of `accessAndMySQLTransfer`. | `C:\path\to\accessAndMySQLTransfer` |
| `BUILD_OUTPUT_DIR` | Local scratch dir for generated `cbdb_data.mdb` and `cbdb.sqlite` (gitignored). | `.build` or any absolute path |
| `MARIADB_HOST` | MariaDB host for the Phase 1.6 intermediate cache (§4d). | `localhost` |
| `MARIADB_PORT` | MariaDB port. | `3306` |
| `MARIADB_USER` | MariaDB user with `CREATE / DROP / INSERT` on `MARIADB_DATABASE`. | `root` |
| `MARIADB_PASSWORD` | MariaDB password. Required; fail-loud if absent. | `notSecureChangeMe` |
| `MARIADB_DATABASE` | DB name the Datadump is imported into. | `cbdb_data` |
| `MARIADB_CONTAINER_NAME` | Informational; used only when `MARIADB_AUTO_LAUNCH=1`. | `cbdb-parity-mariadb` |
| `MARIADB_FORCE_REIMPORT` | `1` = drop and reimport even when SHA matches; `0` = trust the in-DB provenance row. | `0` |
| `MARIADB_AUTO_LAUNCH` | `1` = `docker start <CONTAINER_NAME>` if found stopped; `0` = require the user to bring the container up. | `0` |

`.env.sample` is committed with these keys and placeholder values. `.env` (real local paths and secrets) is gitignored — never commit real machine paths or passwords into the public repo.

## 3. Repository setup
1. `git init`, set default branch `main`, add `.gitignore` (Python, .NET, PHP, .env, scratch dirs, large DBs).
2. Add `README.md`, `LICENSE` (**Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International — CC BY-NC-SA 4.0**), `AGENTS.md`/`CLAUDE.md` conventions.
3. Create empty repo `cbdb-access-avalonia-parity` under `https://github.com/orgs/cbdb-project/` (public) via the local `gh` CLI (already authenticated). Push `main`.
4. Add a "pull-then-use" helper. **Every parity run** (and every build-pipeline run) refreshes the following four repos first via `git -C <repo> pull --ff-only`:
   - `ACCESS_TESTS_REPO` → `cbdb-user-mdb-tests`
   - `AVALONIA_REPO` → `cbdb-desktop-app`
   - `ONLINE_SERVER_REPO` → `cbdb-online-main-server`
   - `ACCESS_MYSQL_TRANSFER_REPO` → `accessAndMySQLTransfer`

   `MYSQL2ACCESS_DIR` and the folder containing `CBDB_USER_MDB` are **not** git repos and are skipped by the refresher. Implement as a single Python utility `scripts/refresh_external_repos.py` that every harness entrypoint calls before doing anything else; fail loudly if any pull is non-fast-forward.

## 4. Build pipeline (Datadump → two databases)

Both sub-pipelines (4a, 4b) MUST consume the SAME `cbdb_data_YYYYMMDD.tar.gz` archive; the `build_all` orchestrator (4c) ties them together. See §1 strict-pipeline rule: pre-existing mdb files are NOT acceptable substitutes for the 4a output.

### 4a. Datadump → Access `cbdb_data.mdb`

Split into two sub-phases:

**Phase 1.3a — `cbdb_parity.access_schema` (✅ done)**
- Loads `$ACCESS_MYSQL_TRANSFER_REPO/TablesFields.xlsx` (85 tables / 669 columns) into typed dataclasses: `AccessSchema`, `AccessTable`, `AccessColumn(name, data_format, nullable, is_primary_key, foreign_key_*, dump_*)`.
- Used by 1.3b for type overrides and FK references; useful on its own for schema validation.

**Phase 1.3b — `cbdb_parity.mdb_builder` (next)**

Python end-to-end, no Docker MySQL, no manual artifacts. Concrete plan:

1. **Bootstrap empty mdb** via `pypyodbc.win_create_mdb(target)` — empirically verified to produce a working 172 KB empty mdb in one call on Windows + Microsoft Access Driver. No ADOX, no `win32com`, no template file. `pypyodbc` is added as a new `[access]` extra dependency; we only use that one function — all other mdb operations (connect / execute / cursor.tables) continue to use `pyodbc` (matching the proven shape of `$ACCESS_MYSQL_TRANSFER_REPO/mysql2access.ipynb`).
2. **Consume the dump stream** via the existing `cbdb_parity.mysqldump.parse_dump()` (Phase 1.1) — no MySQL server needed, no Docker. Reuse the streaming parser we already have, same as `cbdb_parity.sqlite_builder` does.
3. **MySQL → Access type translator** in a new `cbdb_parity.access_types.mysql_type_to_access()` mirroring the shape of `mysql_type_to_sqlite`. Starting map (from `mysql2access.ipynb` + the README at `$ACCESS_MYSQL_TRANSFER_REPO/README.md`):
   - `int / smallint / mediumint / bigint(N)` → `INTEGER` (Long)
   - `double / float` → `DOUBLE`
   - `decimal(p,s)` → `DOUBLE` (Access lacks NUMERIC — verify with CBDB rows)
   - `varchar(N)` → `VARCHAR(255)` capped; **mind the utf8mb4 → utf8 caveat: drop to `VARCHAR(191)`** if INSERT errors come back complaining about row size, per README §1
   - `char(N)` → `VARCHAR(N)` (Access has no fixed-length CHAR)
   - `text / mediumtext / longtext / tinytext` → `LONGTEXT` (Memo)
   - `date / datetime / timestamp / time` → `DATETIME`
   - `bit / tinyint(1)` → `SMALLINT` (per README §3 — boolean flips bug avoided)
   - `varbinary / binary` → `LONGBINARY`
4. **CREATE TABLE / INSERT** via `pyodbc`. Skip `CBDB__*` internal tables by default (same default as `sqlite_builder`); skip the `SKIP_TABLES` ops/audit list from `mysql2access.ipynb` cell 3 (oauth_*, migrations, users, operations, password_resets, …). Batch INSERTs via `cursor.executemany(...)` — the notebook uses row-by-row `execute`, which is slow for 5M+ rows; we use the same `_BATCH_ROWS=1000` constant `sqlite_builder` does.
5. **Special-value normalisation** from notebook cell 2: `b'\x00'`→0, `b'\x01'`→1, `'0000-00-00 00:00:00'`→None.
6. **Output `BUILD_OUTPUT_DIR\cbdb_data.mdb`**. Pair with fixed `CBDB_USER_MDB` to form the working Access stack.

CLI: `scripts/build_mdb.py` + `[project.scripts] cbdb-parity-build-mdb`. Orchestrator integration: `build_all.py` gains a `_build_mdb_if_needed` call alongside the existing `_build_sqlite_if_needed`, sharing the same SHA-cache invariants and per-product manifest slot.

**Why not Docker MySQL.** Considered as fallback but ruled out: the empty-mdb bootstrap (the only step that initially looked hard) is solved by `pypyodbc.win_create_mdb`; the dump-parsing step is solved by the already-built `cbdb_parity.mysqldump`. Going through Docker would re-introduce MySQL as a dependency and produce a longer pipeline (tar.gz → docker mysql:8 → notebook code → mdb) than the direct one (tar.gz → parse → mdb). The Docker route stays available as an escape hatch if some CBDB-specific dump shape defeats the type translator, mirroring 4b's policy.

**Codex review gate (same as 4b).** During 1.3b implementation, three consecutive codex review rounds flagging serious issues with the Python port flip the offending step to the Docker fallback. User-triggered, not automatic.

### 4b. Datadump → Avalonia SQLite

**Primary route — pure Python port.** The Laravel command of record is `cbdb-online-main-server/app/Console/Commands/ExportMysqlToSqlite.php` (signature `db:export-to-sqlite`). It expects a live MySQL connection, *not* a tar.gz. The plan is to port the *logic* of that command (plus the auxiliary index/address rebuilders it relies on — `RebuildIndexAddress.php`, `RebuildIndexYear.php`, `RebuildNameSearchIndex.php`, `RegenerateAddresses.php`, `ImportTradSimpMap.php`) directly to Python, so the pipeline becomes:

&nbsp;&nbsp;&nbsp;&nbsp;`tar.gz` → parse MySQL dump in Python → write `cbdb.sqlite` directly.

This avoids spinning up MySQL on every run and keeps the pipeline self-contained. Output: `BUILD_OUTPUT_DIR\cbdb.sqlite`. Validate against the row counts of the existing reference `cbdb-user-mdb-tests/data/cbdb_online_sqlite/cbdb_20260328.sqlite3` (older but useful as a structural sanity check).

**Fallback route — Docker MySQL.** If a faithful Python port turns out to be impractical (e.g. an artisan command relies on a non-trivial MySQL-only feature like collation-sensitive name search indexes that doesn't translate cleanly), fall back to: `tar.gz` → restore into a throwaway `mysql:8` Docker container → run the real `php artisan db:export-to-sqlite` against it → copy out `cbdb.sqlite`. Wrap as `scripts/build_sqlite_docker.py` and only invoke it if the Python route fails or diverges.

**Decision point.** Phase 1 must pick one of these *and stick with it* before Phase 2 — running both forever is not the goal. Verify row counts of key tables (BIOG_MAIN, ADDR_CODES, OFFICE_CODES, …) match the Access build to prove "same data, two formats" before any query diffing.

### 4c. One-shot orchestrator (✅ done — `cbdb_parity.build_all`)
`scripts/build_all.py` + `cbdb-parity-build-all` CLI. Runs 4a + 4b from a single Datadump archive and records the dump filename + SHA in `build_manifest.json` (at workspace root, discovered via `find_dotenv`) so every report ties back to a specific data version. SHA-based caching skips rebuilds when the manifest already records the current SHA AND the recorded product path matches the current target AND the file exists. `--rebuild` forces. Refresh of the four external repos is mandatory and cannot be skipped.

Currently wires only 4b (sqlite). Once 4a Phase 1.3b lands, the orchestrator adds the parallel `_build_mdb_if_needed` call alongside `_build_sqlite_if_needed`; manifest invariants (SHA-anchored sibling preservation, partial-write protection, stale-sibling drop on SHA change) are already in place.

### 4d. MariaDB intermediate cache (⏳ Phase 1.6 — adopted after Phase 1.3b empirics)

The Phase 1.3b real-world build against the 1.4 GB May-27 Datadump revealed two pyodbc/Jet pathologies even with the Python port working as designed:

1. **Jet 2 GB transaction-buffer ceiling** — even when the final mdb would be < 1 GB, a single-transaction bulk load against `Microsoft Access Driver` raised `HY001` once Jet's accumulated work-buffer crossed the .mdb format's 2 GB hard limit. Fixed in `mdb_builder._drain` by committing per-table.
2. **Duplicate values blocking declared PKs** — Jet aborts the whole transaction with `IntegrityError 23000` when a Datadump row violates a PK declared via the TablesFields.xlsx overlay, even though the production Access mdb maintained in `$MYSQL2ACCESS_DIR` does not enforce those PKs either. Fixed by suppressing the overlay's PRIMARY KEY clause.

Both fixes hold the Datadump-direct path together, but the **Datadump → Access** write is fundamentally throttled by the Jet ODBC driver's row-level locking with no bulk-load fast path (cf. SQLite's `synchronous=OFF / journal_mode=OFF`). The historical workflow in `$ACCESS_MYSQL_TRANSFER_REPO/mysql2access.ipynb` (and the user's empirical measurement) routes through MariaDB instead — `Datadump → MariaDB` is fast (5–10× the Python parser path), and `MariaDB → Access` via pyodbc reuses the proven ipynb pattern.

**The MariaDB step is a CACHE LAYER, not a replacement for either output.** The two final products are still `cbdb.sqlite` (for the Avalonia side) and `cbdb_data.mdb` (for the Access side). The mdb still flows into `cbdb_replay`-driven pyodbc tests exactly as Phase 3 designs. Phase 1.6 displaces the in-process mysqldump parser as the **default** import step for both builders; the `cbdb_parity.mysqldump`-based path is retained as a fallback for non-Docker hosts and selected via `source='datadump'`.

**Module / config layout (`Phase 1.6`):**

- `.env` keys (new; documented in `.env.sample` and §2 alongside the other inputs):
  - `MARIADB_HOST=localhost`
  - `MARIADB_PORT=3306`
  - `MARIADB_USER=root`
  - `MARIADB_PASSWORD=…`  (required; no default — fail-loud if missing)
  - `MARIADB_DATABASE=cbdb_data`
  - `MARIADB_CONTAINER_NAME=cbdb-parity-mariadb` (informational; we don't auto-launch the container — the user runs `docker compose up` themselves)
  - `MARIADB_FORCE_REIMPORT=0` (1 = drop and reimport even when SHA matches; 0 = trust the in-DB provenance row)
  - `MARIADB_AUTO_LAUNCH=0` (1 = `cbdb_parity.mariadb` will `docker start <CONTAINER_NAME>` if found stopped; 0 = fail with a clear "please start the container" message; default 0 keeps the tool deterministic against shared workstations)

- `cbdb_parity.mariadb`:
  - `connect(cfg) → pymysql.Connection`
  - `ensure_imported(cfg, info: DatadumpInfo)`:
    1. Connect; create `cbdb_data` DB if absent.
    2. Check `_cbdb_parity_provenance(datadump_sha, imported_at)` single-row table for `info.sha256`.
    3. If SHA matches AND `MARIADB_FORCE_REIMPORT=0`: return cached.
    4. Else: `DROP DATABASE IF EXISTS cbdb_data; CREATE DATABASE cbdb_data;`, stream the .tar.gz through `mysql` CLI (`tar -O -xzf … | mysql …`) or pymysql `executescript`, then write the provenance row.

- `sqlite_builder` and `mdb_builder` gain `source={'datadump','mariadb'}` (default `mariadb` once 1.6 lands, with `datadump` retained as fallback for non-Docker hosts):
  - From `mariadb`: `SHOW TABLES` + `SELECT * FROM <t>` per table → existing CREATE/INSERT loop. Both builders share a `_pull_table_rows(conn, table) → (TableSchema, Iterable[Row])` helper so the rest of the code path (skip lists, batching, manifest, per-table commit) stays the same.

- `build_all` orchestrator:
  - First runs `mariadb.ensure_imported(cfg, info)`.
  - Then runs sqlite + mdb sub-builders against the cached MariaDB.
  - If `MARIADB_AUTO_LAUNCH=1` the orchestrator may `docker start` the container; otherwise it surfaces "please start the container" and returns rc=2.

**This is additive to Phase 1.3b, not a replacement** — the strict-pipeline rule still bans using pre-existing user mdb files as substitutes for the generated product. MariaDB import is part of OUR pipeline; it just sits between the Datadump and the two writers.

## 5. Query coverage inventory
1. Crawl `cbdb-desktop-app/Cbdb.App.Avalonia` + `Cbdb.App.Core` to enumerate every implemented query/view (people search, office, kinship, association, place, etc.). Output `coverage/avalonia_queries.yaml`: `{id, name, params, status: implemented|missing}`.
2. Crawl `cbdb-user-mdb-tests` (especially `test_vba_*.py`, `cbdb_driver/`, `cbdb_replay/`) to enumerate every Access query the existing framework can drive. Output `coverage/access_queries.yaml`.
3. Produce `coverage/matrix.md` joining the two: Avalonia feature ↔ matching Access query ↔ status (paired / Avalonia-only / Access-only / missing-on-both).

## 6. Differential harness (Phase 3)
- Pytest-based, modeled on the VBA differential pattern in `cbdb-user-mdb-tests/tests/test_vba_differential.py` and `cbdb_driver`/`cbdb_replay`.
- For each paired query in `coverage/matrix.md`:
  1. **Access side** — drive the real Access UI via the existing `cbdb_driver` (pywinauto) **or** issue the equivalent SQL against the **generated** `cbdb_data.mdb` (Phase 1.3b output) via pyodbc, depending on whether the query is UI-only or SQL-expressible. Per §1 strict-pipeline rule, pre-existing local mdbs are NOT acceptable inputs.
  2. **Avalonia side** — call the same query path. Two options to evaluate in a spike: (a) UI-drive Avalonia via Appium/FlaUI, (b) instantiate `Cbdb.App.Core` query services directly from a small .NET test host that returns JSON. (b) is faster and more stable; prefer it unless we need to validate UI binding.
  3. Normalize both result sets to a canonical record shape, sort, diff.
  4. Emit a per-query report under `reports/<query_id>/{access.json, avalonia.json, diff.json, summary.md}`.
- Shared parametrization fixtures (person IDs, office IDs, kinship roots) live in `tests/fixtures/` so both sides hit the same inputs.

**Starter set (first 3 paired queries — revised from WORK_PLAN's original BIOG/office/kinship after Phase 2 found shape mismatches).** Per `coverage/matrix.md` Tier 1, the three strict-same-shape pairs that can be driven without further shape negotiation:
1. **Entry query** — Avalonia `IEntryQueryService.QueryAsync` vs Access `cbdb_replay/lookatentry` + Form_LookAtEntry CmdQuery
2. **Office query** — Avalonia `IOfficeQueryService.QueryAsync` vs Access `cbdb_replay/lookatoffice` + Form_LookAtOffice CmdQuery
3. **Status query** — Avalonia `IStatusQueryService.QueryAsync` vs Access `cbdb_replay/lookatstatus` + Form_LookAtStatus CmdQuery

BIOG basic, kinship recursive, and associations have shape mismatches that need a Phase 4 narrowing step before they're paired.

## 7. Reporting & root-cause loop
- Top-level `reports/SUMMARY.md` aggregates: total queries, paired, passing, failing, Avalonia-missing.
- For each failing query, capture: input, two outputs, diff, and a `hypothesis.md` slot for the human-or-LLM-written root cause (schema mismatch, missing join, code-table drift, etc.).
- `reports/known_issues.md` tracks confirmed Avalonia gaps so they don't re-trigger noise on every run.

## 8. Phasing & status

- **Phase 0 — repo init**
  - ✅ 0.1 `git init` + LICENSE (CC BY-NC-SA 4.0 canonical text) + README + AGENTS + `.gitignore` + `.env.sample`
  - ✅ 0.2 `cbdb_parity.config` (`.env` loader, strict validation, find_dotenv-based discovery)
  - ✅ 0.3 `cbdb_parity.refresh` + `cbdb-parity-refresh` CLI (refresh gate, mandatory)
  - ✅ 0.4 `gh repo create cbdb-project/cbdb-access-avalonia-parity --public` + initial push

- **Phase 1 — Datadump → two databases**
  - ✅ 1.0 `cbdb_parity.datadump` (newest-by-date-tag, streaming `r|gz`, SHA)
  - ✅ 1.1 `cbdb_parity.mysqldump` (forward-only mysqldump parser, fail-loud)
  - ✅ 1.2 `cbdb_parity.sqlite_builder` + `cbdb-parity-build-sqlite` (Python port of `ExportMysqlToSqlite`; real-world: 94 tables / 5.74M rows / 559 MB in 405 s)
  - ✅ 1.3a `cbdb_parity.access_schema` (TablesFields.xlsx loader)
  - ✅ 1.3b code complete (`cbdb_parity.access_types`, `cbdb_parity.mdb_builder`, `cbdb-parity-build-mdb` CLI, build_all integration). Codex rounds clean through v10 + Phase 3d v7. Two real-world fixes applied after first end-to-end attempt against the May-27 Datadump:
    - Jet 2 GB transaction-buffer hit → **per-table commit** in `_drain`.
    - `IntegrityError 23000` on duplicate PK values → **PRIMARY KEY clause suppressed** in `_create_table_sql` (NOT NULL / DataFormat overlays still applied).
    The Datadump-direct path now completes; the MariaDB cache path (§4d, Phase 1.6) supersedes it once landed.
  - ✅ 1.4 `cbdb_parity.build_all` + `cbdb-parity-build-all` (SHA cache, manifest invariants, partial-write protection, mandatory refresh) — extended in 1.3b to build both products
  - ✅ 1.5 `cbdb_parity.parity_check` (row-count diff between mdb and sqlite)
  - ✅ **1.6 — MariaDB intermediate cache** (`cbdb_parity.mariadb` + `cbdb-parity-import-mariadb` CLI + `cbdb_parity.mariadb_source` event adapter; sqlite_builder + mdb_builder `source=mariadb` default; build_all orchestrator calls `ensure_imported` first). Real-world: Datadump → MariaDB 226 s, MariaDB → SQLite 130 s (3.1× faster than the prior Datadump-direct path). Codex iterated v1..v9 of 1.6a; the per-section gate on 1.6b/c is queued behind the codex rate-limit reset. See §4d for the shape this implements.

- **Phase 2 — Query coverage matrix**
  - ✅ `coverage/avalonia_queries.yaml` (29 methods / 9 services) + `coverage/access_queries.yaml` (43 queries / 11 forms) + `coverage/matrix.md` (16 directly-paired + 4 shape-mismatched + 4 access-only)

- **Phase 3 (1–2 weeks)** — differential harness skeleton + first 3 paired queries (Entry / Office / Status — revised starter set, see §6).
  - ✅ 3a (revised — no .NET test host, since the user's machine has only the .NET runtime, not the SDK): `cbdb_parity.avalonia_query_sql` (raw-string SQL extractor from `Sqlite*QueryService.cs`) + `cbdb_parity.avalonia_query` (Python re-execution of the extracted SQL via `sqlite3`; produces bit-identical rows because both Microsoft.Data.Sqlite and Python's sqlite3 wrap the same engine). `EntryQueryRequest` mirror + `entry_query()` verified end-to-end against the real .build/cbdb.sqlite. **Codex round pending.**
  - ✅ 3b: `cbdb_parity.diff_report` (DiffStats / DiffResult / `diff_rows` with composite-key + compare-fields subset + `write_report` producing the WORK_PLAN §6/§7 file tree with hypothesis.md preserved across re-runs) + `cbdb_parity.access_query` (cbdb_replay bridge: sys.path injection for `$ACCESS_TESTS_REPO/tests`, EntryQueryRequest → EntryQueryInputs mapper, row projection to the 9-field common cross-section). **Codex round pending.**
  - ✅ 3c entry pair smoke test: `tests/test_phase3c_entry_pair.py` — runs both backends, diffs by `(person_id, sequence)` on the common fields, writes the report tree, asserts diff.stats.matches. Skips cleanly when prereqs (mdb, manifest same-SHA, pyodbc, cbdb_replay) aren't met. **Will execute end-to-end once Phase 1.3b's bg build finishes AND `cbdb-parity-build-all` is run to anchor both products to the same SHA.**
  - ✅ 3d (Office pair): `cbdb_parity.avalonia_office_query` + `cbdb_parity.access_office_query` + `tests/test_phase3d_office_pair.py`. Field naming aligns with `Cbdb.App.Core.OfficeQueryRecord` snake-case property names; the 57/64 reader swap (SQL columns vs constructor positions) is mirrored in `_sql_row_to_record_row`. Access bridge rejects request branches `cbdb_replay/lookatoffice` cannot faithfully replay (person_keyword / dynasty_ids / place ids when set / empty office_codes) so the parity report doesn't blame Avalonia for mismatches the bridge silently caused. Codex iterated v1..v7 clean.
  - ✅ 3e (Status pair): `cbdb_parity.avalonia_status_query` + `cbdb_parity.access_status_query` + `tests/test_phase3e_status_pair.py`. Same shape as 3d (positional record-order, unsupported-branch rejection, post-fetch label sort, strict-pipeline path-match gate). 36-field record; no positional swap (the C# reader's column indices match SELECT order directly). Codex queued behind rate-limit reset.

- **Phase 4 (complete; superseded by Phase 5c-final + Phase 6)** — query-by-query coverage expansion. The pair-test surfaces and implementation pattern listed below are the **Phase 4 landing state** at 2026-05-28, kept for commit-history context. **Phase 5c-final retired the Python mirror layer entirely**, and **Phase 6b removed 13 of the per-person pair tests** for §0.b non-compliance (no `cbdb_replay.lookat*` analogue). The current pair-test count and §0.b-compliant surfaces are tracked in §9 "Post-Phase-9 status" below — do NOT take the Phase 4 numbers here as live.
  - ✅ **Tier 1 strict-same-shape** (Phase 3): entry / office / status — `tests/test_phase3{c,d,e}_*_pair.py`.
  - ✅ **Tier 1 shape-negotiated** (Phase 4):
    - **BIOG basic** — `tests/test_phase4_biog_basic_pair.py` (SearchAsync no-keyword branch). 50/50 matching at limit=50.
    - **associations cross-person** — resolved into Tier 2 per-person `tests/test_phase4_associations_pair.py` (660/660 matching with text_title in diff key).
    - **kinship recursive** — direct-branch resolved into Tier 2 `tests/test_phase4_kinships_pair.py` (25/25). The `expandNetwork=true` graph traversal is queued in known_issues.md (`kinship_expanded_network`) — port of `KinshipTraversalState`+`ReduceKinship` is pure post-processing on top of the already-verified SQL.
    - **GroupData** — closed as no-pair (genuinely misaligned shapes); known_issues.md entry `group_data_demographics`.
  - ✅ **Tier 2 per-person PersonBrowser accessors** — 13/13:
    - altnames, entries, addresses, writings, statuses, possessions, events, kinships, associations, sources, institutions, detail (PASS).
    - postings auto-skips on the documented upstream `pto.c_appt_type_code` schema bug (same bug as office_basic); same single upstream fix re-arms both.
  - ✅ **Access-only categories** (Texts / Networks / AssociationPairs / Place): documented as Avalonia gaps in `reports/known_issues.md` under `avalonia_gap`. Nothing to compare until Avalonia implements the corresponding services in `cbdb-desktop-app`.
  - **HISTORICAL — retired in Phase 5c-final + Phase 6**.
    Established Tier 2 implementation pattern at Phase 4 landing
    (codified across 13 accessors). Phase 5c-final retired
    steps 1, 3, 4, 5; Phase 6a moved kinships to
    `cbdb_replay.lookatkinship`; Phase 6b deleted the bridges
    and pair tests for the other 12 surfaces (no
    `cbdb_replay.lookat*` analogue → §0.b non-compliant). Do
    NOT use this pattern in new code; §0.b explicitly forbids
    hand-mirroring upstream SQL.
    1. extract C# SQL via `find_sql_block(cs_path, discriminator)` where the discriminator is a token unique to that block (often a raw alias like `bad.c_sequence` or table-qualified column);
    2. splice raw ID columns into the SELECT for stable diff-keying (anchor: a unique substring just before `FROM`);
    3. hand-mirror the Access SQL with parenthesised chained LEFT JOINs (N joins → N−1 opening parens before the base table) and SQLite→Access expression rewrites (`||`→`&`, `CASE`→`IIf`, `LIMIT/OFFSET`→`TOP n` + Python slice, `WITH`→inline subquery);
    4. apply `JoinDisplay` post-processing identically on both sides;
    5. coerce bool columns via `_to_bool_or_none` for `c_*_intercalary`/`c_natal`/etc.;
    6. choose a diff key that's unique-per-person (sometimes requires the natural key tail — e.g. ASSOC_DATA needs `c_text_title` because multiple texts can document the same logical association).
  - **HISTORICAL — also retired**. Infrastructure helpers added during Phase 4:
    - `cbdb_parity.avalonia_query_sql.extract_sql_blocks` — module deleted in Phase 5c-final.
    - `cbdb_parity.access_query._replay_row_to_avalonia_shape` (and office/status variants) coerce pandas-NaN → None; this is still live because the Phase 3c/3d/3e bridges that produced it still drive `cbdb_replay.lookat*` directly under §0.b.
    - Shared `_join_display` / `_to_bool_or_none` helpers in `cbdb_parity.avalonia_altnames` and `cbdb_parity.avalonia_addresses` — deleted in Phase 5c-final + Phase 6b (the helpers had no remaining callers once the per-surface bridges came down).

- **Phase 5 (next, planned 2026-05-29 onwards)** — pivot to direct
  .NET Avalonia execution via a new `Cbdb.App.ParityHost` console.
  Reason: Phase 3-4 used the "extract SQL + Python re-execute" path
  because the user's machine only had .NET runtime, no SDK. The
  user's followup goal installs SDK 8.0.421 (verified
  `dotnet --list-sdks` shows it; `dotnet build Cbdb.App.Data.csproj`
  succeeds clean against the existing tree). With SDK available we
  can stop mirroring C# semantics in Python and instead invoke the
  real C# services. Concretely:

  - **5a — ParityHost console (lives IN THIS REPO, not upstream)**:
    - Per §0 scope contract: the console project lives in
      `cbdb-access-avalonia-parity/parity_host/Cbdb.App.ParityHost/`
      (`dotnet new console -f net8.0`), NOT in `cbdb-desktop-app`.
      We do not commit code to upstream Avalonia — the harness
      references it.
    - References `Cbdb.App.Core` and `Cbdb.App.Data` via
      `<ProjectReference Include="$(AvaloniaRepo)/Cbdb.App.Core/Cbdb.App.Core.csproj" />`
      style — the `AvaloniaRepo` MSBuild property is read from the
      **process environment variable** of the same name. MSBuild
      doesn't parse `.env` natively, so the contract is:
        - Python harness (the normal caller): always loads `.env` via
          `python-dotenv` before any subprocess call, so
          `os.environ["AVALONIA_REPO"]` is set before invoking
          `dotnet run` or the published binary. Both `Popen` and
          `subprocess.run` inherit the parent env by default.
        - Manual `dotnet build` (rare — initial scaffold,
          contributor IDE setup): contributor sets `AVALONIA_REPO`
          themselves before running, e.g. `$env:AVALONIA_REPO = ...`
          in PowerShell. A small `parity_host/README.md` documents
          this one-liner.
        - `Directory.Build.props` at the project root just exposes
          the env var as an MSBuild property, e.g.
          `<AvaloniaRepo>$(AVALONIA_REPO)</AvaloniaRepo>` inside a
          `<PropertyGroup>`. No parsing of `.env`.
    - When the upstream tree moves (a `git pull` in
      `$AVALONIA_REPO`), this console picks up the changes on next
      `dotnet build`. No commits to upstream needed; no .csproj
      edits in `cbdb-desktop-app`.
    - CLI: `cbdb-parity-host <service> <sqlite-path> <request-json>`
      → reads JSON request from stdin, instantiates the service, runs
      `QueryAsync` / `Get*Async`, JSON-serialises the result to stdout.
      Errors → JSON `{error: ..., stack: ...}` on stderr.
    - One executable handles 6 of the 7 Avalonia query surfaces
      (Entry, Office, Status, PersonBrowser's record-returning methods,
      GroupPeople, PlaceLookup, DynastyLookup). **Special case**:
      `IPersonBrowserService.GetRelatedItemsAsync` returns a
      `DataTable` rather than a record/list DTO, so it needs a custom
      JSON projection (column metadata + row arrays) — handled by a
      dedicated dispatch branch, not the generic record-list serialiser.
    - **Encoding contract** (load-bearing on Windows): both sides
      MUST agree on UTF-8 for stdin/stdout/stderr. C# side sets
      `Console.OutputEncoding = Console.InputEncoding = new UTF8Encoding(false)`
      at host startup. Python side uses `subprocess.Popen(...,
      stdin=PIPE, stdout=PIPE, stderr=PIPE, text=False)` and
      .read()/.write() raw bytes that we decode/encode as UTF-8
      explicitly. Without this, the many Chinese fields in CBDB rows
      (c_name_chn, c_title_chn, etc.) mojibake under the default
      Windows code page and parity diffs become meaningless.

  - **5b — Python harness switchover (✅ landed 2026-05-29)**: each of the existing
    `cbdb_parity/avalonia_*.py` modules currently does
    `extract_sql_blocks(cs_path) → sqlite3.connect(...).execute(...)`.
    Adds a NEW execution mode `via_parity_host(...)` that
    subprocess-invokes the ParityHost binary with the JSON-serialised
    request and parses the JSON response. Original SQL-extract path
    kept as `via_sql_extract(...)` for diffing (the two paths SHOULD
    produce identical row sets — any divergence is a Python-mirror
    bug we've been failing to catch).

  - **5c — phase out the Python mirror layer (✅ landed 2026-05-29)** once the
    via-ParityHost path is proven equivalent: drop the SQL extractor +
    its associated rewrites (`_csharp_params_to_sqlite`,
    `_join_display`, `_to_bool_or_none`, the AddrField casefold, the
    NULL sequence → 0 coercion, etc.). All of these have been bug
    sources (codex caught ~10 P1/P2 issues across the 18 review
    rounds purely from Python-mirror drift). The replay scan +
    Tier 1/2 pair tests stay; only their backend swaps. **NB**: the
    full dependency chain that the 5d kinship cross-check needs MUST
    be retained until 5d finishes, NOT just
    `cbdb_parity/avalonia_kinships_expanded.py` itself.
    Concretely, `avalonia_kinships_expanded.py` imports
    `_load_get_kinships_sql` from `cbdb_parity/avalonia_kinships.py`
    (which in turn uses `extract_sql_blocks` from
    `cbdb_parity/avalonia_query_sql.py`) and `_join_display` from
    `cbdb_parity/avalonia_altnames.py`. Removing any of those before
    5d finishes breaks the comparison target at import time. The
    safe 5c ordering: defer deletion of the entire
    `avalonia_{query_sql, altnames, kinships, kinships_expanded}.py`
    cluster until 5d signs off, then delete all four in one commit.

  - **5d — kinship expandNetwork=true cross-check (✅ landed 2026-05-29, then retired in 5c-final)** (must precede
    5c's deletion of the kinships_expanded.py module): the BFS state
    machine in `cbdb_parity/avalonia_kinships_expanded.py` is the
    biggest manual port. Run both ports against the same set of
    person_ids and require byte-identical output before deprecating
    the Python copy. If 5d uncovers divergence, 5c on the kinships
    module is blocked until reconciled.

  - **5e — coverage extension (✅ landed 2026-05-29)**: with the C#
    directly callable, the lookup/group surfaces already in
    cbdb-desktop-app (DynastyLookup, PlaceLookup, GroupPeople) are
    now exposed through the ParityHost and wrapped in Python
    (`cbdb_parity/avalonia_lookups.py`) with smoke tests in
    `tests/test_phase5e_lookups_smoke.py`. The other documented
    gaps (Texts / Networks / AssociationPairs) are NOT in upstream
    yet, so per the §0 scope contract they remain out of scope
    until an upstream commit lands them — at which point this repo
    only needs to add the host dispatch + Python wrapper + smoke
    test. The original 5e plan listed three integration costs per
    new service:
      1. land the upstream service in `cbdb-desktop-app` (record +
         interface + SqliteXxxService.cs, per the existing pattern);
      2. add a dispatch branch in `Cbdb.App.ParityHost` that knows
         how to deserialise the request JSON and serialise the
         response;
      3. add the Python-side wrapper in `cbdb_parity/avalonia_*.py`
         (request dataclass + subprocess invocation + row
         normalisation) and Access bridge (cbdb_replay mapping) and
         pair test.
    What 5e DOES win: the C# implementation runs literally, so there's
    no more "Python mirror drifts from C#" failure mode. But every
    new query still costs 3 distinct integrations, not zero.

  - **Caveats / open questions**:
    - **Startup cost**: `dotnet run` cold-start is ~500ms-1s. For ~400
      tests × multiple sub-queries each this matters. Mitigation:
      ParityHost stays alive as a daemon, Python harness streams
      NDJSON over stdin/stdout (UTF-8 byte pipes — see 5a encoding
      contract). One-shot CLI mode kept for debugging.
    - **UTF-8 pipe contract** (load-bearing): see 5a. NEVER let the
      pipe inherit the default Windows code page (cp936 / cp1252
      etc.) — CBDB rows are predominantly CJK.
    - **`Cbdb.App.Data` references Microsoft.Data.Sqlite**: ParityHost
      will too. No additional native deps. `Cbdb.App.Data` is a
      library project with no DI container of its own; ParityHost
      `new`s up `SqliteXxxService` instances directly (no
      `IServiceProvider` needed).
    - **Test repro**: ParityHost output should be deterministic for a
      fixed (sqlite_path, request) pair. CI / parity reports keep
      the same SHA-anchoring contract.
    - **Backwards-compat during transition**: don't delete the SQL
      extractor (or the `avalonia_kinships_expanded.py` BFS port,
      explicitly) until 5d's byte-for-byte cross-check passes; the
      existing 400-test green state is the floor.

- **Phase 6 (planned 2026-05-30 onwards)** — enforce the §0.b
  "no transcription" rule retrospectively across Phase 4.

  Phase 5c-final retired the Python mirror layer on the Avalonia
  side but left Phase 4's Access-side hand-written `_ACCESS_SQL`
  bridges in place — they recreate Avalonia's joins inside
  `cbdb_parity/access_*.py` and are exactly the transcription
  pattern §0.b forbids. Phase 6 aligns Phase 4 with the new rule.

  The Access-side "real code" is `cbdb-user-mdb-tests`'s
  `cbdb_replay.lookat*` modules (the same package Phase 3c/3d/3e
  already drive via `cbdb_parity/access_query.py` /
  `access_office_query.py` / `access_status_query.py` — that is
  the integration template every Phase 6 rewrite copies).

  - **6a — rewrite the bridges that have a cbdb_replay analogue**.
    Only ONE surface qualifies — see "discovery" note below:

      | surface       | upstream module                  | current bridge                     |
      |---------------|----------------------------------|------------------------------------|
      | kinships      | `cbdb_replay.lookatkinship`      | `cbdb_parity.access_kinships`      |

    Replace `_ACCESS_SQL` + pyodbc plumbing with the
    `_ensure_cbdb_replay_on_path` + `replay_run` + field projection
    pattern (template: `cbdb_parity/access_office_query.py`).
    Update `tests/test_phase4_kinships_pair.py` to thread the
    `access_tests_repo` kwarg through. Codex review.

    **Discovery (2026-05-30, mid-execution)**: associations was
    originally planned for 6a alongside kinships, but on inspection
    `cbdb_replay.lookatassociations.run` takes only
    `(assoc_codes, addr_ids, year_filter)` — there is no
    `person_id` input. It answers "rows matching these assoc_codes",
    which is a structurally different question from Avalonia's
    per-person `GetAssociationsAsync(personId)`. Wrapping it to
    answer the per-person question requires Python post-filtering
    on `c_personid`, which is the orchestration-side equivalent of
    transcription and violates §0.b. Associations therefore
    *moves down to 6b* (deletion) — same treatment as the 11
    surfaces that never had a cbdb_replay analogue.

  - **6b — delete the bridges that have NO cbdb_replay analogue
    for the per-person question**. Thirteen surfaces — twelve
    without any `cbdb_replay.lookat*` module, plus associations
    whose `lookatassociations` answers a structurally different
    question per the 6a discovery:

    ```
    addresses, altnames, associations, biog_basic, detail,
    entries (per-person), events, institutions,
    possessions, postings, sources,
    statuses_person, writings
    ```

    Their `cbdb_parity/access_<surface>.py` modules and the
    matching `tests/test_phase4_<surface>_pair.py` files come out.
    The Avalonia-side oracle for the 12 PersonBrowser-style surfaces
    in this list is preserved by
    `tests/test_phase5c_person_mirror_vs_host.py`, which is
    unaffected. The 13th surface (associations) is also covered
    there as `test_associations_mirror_vs_host`.

    Files to remove (13 + 13; postings counts in here even though
    its bridge was already a stub; associations was relocated from
    6a per the discovery above):

    ```
    cbdb_parity/access_addresses.py    tests/test_phase4_addresses_pair.py
    cbdb_parity/access_altnames.py     tests/test_phase4_altnames_pair.py
    cbdb_parity/access_associations.py tests/test_phase4_associations_pair.py
    cbdb_parity/access_biog_basic.py   tests/test_phase4_biog_basic_pair.py
    cbdb_parity/access_detail.py       tests/test_phase4_detail_pair.py
    cbdb_parity/access_entries.py      tests/test_phase4_entries_pair.py
    cbdb_parity/access_events.py       tests/test_phase4_events_pair.py
    cbdb_parity/access_institutions.py tests/test_phase4_institutions_pair.py
    cbdb_parity/access_possessions.py  tests/test_phase4_possessions_pair.py
    cbdb_parity/access_postings.py     tests/test_phase4_postings_pair.py
    cbdb_parity/access_sources.py      tests/test_phase4_sources_pair.py
    cbdb_parity/access_statuses_person.py
                                       tests/test_phase4_statuses_person_pair.py
    cbdb_parity/access_writings.py     tests/test_phase4_writings_pair.py
    ```

    `coverage/matrix.md` is updated to mark each row "no Access
    ground truth; tracked in `reports/known_issues.md`
    `tier2_per_person`". Codex review.

  - **6c — Phase 5e pair tests: none feasible (discovered
    2026-05-30)**. Initial plan was to graduate `group_people` and
    `place_lookup` from smoke-only to cbdb_replay-backed pair
    tests. On inspection, neither cbdb_replay module answers the
    same question:

    - **`place_lookup` vs `cbdb_replay.lookatplace`**: Avalonia's
      `IPlaceLookupService.GetPlacesAsync` returns the **place
      dropdown options** (every place in the DB).
      `lookatplace.run` returns **people at given places** —
      `BIOG_MAIN` records filtered by `c_index_addr_id IN
      (addr_ids)`. Different question, different output shape.
      Cannot cross-engine diff under §0.b.
    - **`group_people` vs `cbdb_replay.lookatgroupdata`**:
      Avalonia's `GroupPeopleQueryResult` contains **only 5
      category sub-tables** (`StatusRecords`, `OfficeRecords`,
      `EntryRecords`, `TextRecords`, `AddressRecords`); with all
      `include_*` flags off it returns 5 empty lists.
      `lookatgroupdata.run` returns **base `BIOG_MAIN` records**
      for the input person list when no category flag is on, and
      raises `NotImplementedError` if any flag is on. The two
      output shapes have no overlap — no cross-engine diff is
      possible under §0.b.

    `dynasty_lookup` has no cbdb_replay analogue at all
    (`DYNASTIES` is a small lookup table; cbdb_replay never
    needed a wrapper for it).

    Action: all three Phase 5e surfaces stay smoke-only. The
    current `tests/test_phase5e_lookups_smoke.py` IS the §0.b-
    compliant floor. Document the discovery in
    `reports/known_issues.md`. Codex review of the documentation.

  - **6d — biog_basic keyword branch coverage**.
    Add a keyword-search case (e.g. `keyword="王安石"`) to
    `tests/test_phase5c_person_mirror_vs_host.py::test_biog_basic_mirror_vs_host`.
    This is host-vs-host (upstream service vs upstream service via
    the wire format), not Phase 4 pair — biog_basic has no
    cbdb_replay analogue so Phase 4 stays out of scope per 6b.
    Codex review.

  - **Expected test-suite delta** (revised after 6a + 6c
    discoveries):
    - 13 Phase 4 tests deleted (6b) — pure subtraction (was 12; +1
      for associations relocation in 6a).
    - 1 Phase 4 test rewritten (6a) — same count, different backend
      (was 2; -1 for associations relocation).
    - 0 Phase 5e pair tests added (6c) — was 2; -2 after the 6c
      discovery that neither lookatplace nor lookatgroupdata
      answers the matching Avalonia question.
    - 2 Phase 5c cases added (6d) — pure addition: one numeric
      keyword branch (`int.TryParse(...)` → person_id exact match)
      and one fuzzy keyword branch (LIKE across name fields +
      ALTNAME_DATA). Was originally projected as a single case.

    Current floor: 364 passed. Actual after Phase 6: 354 passed.
    The 13-test drop in 6b is the explicit cost of enforcing
    §0.b — those tests were asserting "my hand-written SQL ==
    upstream's SQL", which the new rule classifies as a false
    oracle. Net: -12 (one skip replaced one pass since postings
    was already skip), +2 from 6d ⇒ 364 − 12 + 2 = 354.

  - **Out of scope for Phase 6** (per §0 + §0.b):
    - postings raw-row diff via Python unfolding: would re-create
      Avalonia's nested-to-flat transform in Python = transcription.
      Postings stays uncovered on the Access side until upstream
      adds `cbdb_replay.lookatpostings`.
    - Texts / Networks / AssociationPairs: upstream has no service.
    - detail's `fields` (PersonExtra2024): Access has no analogue
      to extract; already excluded from Phase 5c compare.
    - `cbdb-user-mdb-tests` modifications: out of scope per §0.

  - **Sequencing**: 6a → 6b → 6c → 6d, each ending with `git push`
    after codex sign-off. Phase 6 is incremental; the repo stays
    green at every commit boundary (suite count drops only between
    6b's commits, not within them).

- **Phase 7 (planned 2026-05-30 onwards)** — in-repo housekeeping
  + CI scaffold + runtime optimisation. Everything that is
  doable WITHOUT modifying `cbdb-desktop-app`, `cbdb-user-mdb-tests`,
  or filing issues against them. Items requiring upstream changes
  (Texts/Networks/AssociationPairs services, per-person
  `lookat<surface>` modules, LEFT JOIN variant of `lookatkinship`,
  GroupPeopleQueryResult-shaped variant of `lookatgroupdata`,
  `lookatdynasty`, `lookat_place_options`) are deliberately out
  of scope per §0.a. GitHub issue filing is also out of scope per
  user directive.

  Phase 7 is split into eight independent sub-phases. Each ends
  with `git push` after codex sign-off, mirroring the Phase 5/6
  cadence.

  - **7a (✅ landed 2026-05-30) — `coverage/matrix.md` Tier 3/4
    explicit out-of-scope marking**. Tier 3 (Access-only export
    workflows: GIS, Neo4j, UCINet, Pajek, Gephi) and Tier 4
    (per-form bulk-IO helpers) were listed in the matrix for
    completeness but produce file artefacts rather than
    diffable result rows. Added a one-paragraph header to each
    tier making clear they are deliberately out of this repo's
    parity scope per §0.a. Pure-documentation.

    *Codex round*: clean.

  - **7b (✅ landed 2026-05-30) — `WORK_PLAN.md §9 Open questions`
    Post-Phase-6 close-out**. §9 had stopped at planning-era
    decisions; added a "Post-Phase-6 status (2026-05-30)"
    subsection enumerating (a) what is suppressed in
    `known_issues.md` and why, (b) what would re-arm each
    suppression, (c) the suite-count contract (354/6/1).
    Pure-documentation.

    *Codex round*: caught three issues — the 354/6/1 contract
    was anchored at "HEAD" but 7c was about to add 4 passing
    tests, so the anchor needed to point at the Phase 6 close
    commit (`dddedc1`) instead; the "Active suppressions" table
    mixed in a historical breadcrumb row that wasn't actually
    active; the `avalonia_gap (legacy)` umbrella re-arm
    condition was too weak ("at least one") and was re-phrased
    so the umbrella stays open until all four services land.

  - **7c (✅ landed 2026-05-30) — `reports/SUMMARY.md`
    auto-generation hook**. Added a `cbdb-parity-summary` CLI
    entrypoint wrapping the existing
    `cbdb_parity.summary_report.write_summary` so the
    `reports/SUMMARY.md` dashboard can be regenerated on
    demand. Exit codes: 0 normal, 2 when the reports tree
    doesn't exist. Added 3 CLI tests covering happy path,
    missing-dir, and default-cwd resolution.

    *Codex round*: caught two issues — the rewrite happy-path
    test didn't pre-seed a sentinel `SUMMARY.md`, so a CLI that
    silently appended or refused would have false-passed (fixed
    by writing a sentinel and asserting it's gone); the
    `--reports-dir` flag accepted any path that `exists()`,
    which would crash later in `iterdir()` if the path was a
    file (fixed by adding an `is_dir()` check returning exit
    code 2 with a controlled diagnostic, plus a 4th test
    pinning the behaviour).

  - **7d (✅ landed 2026-05-30) — Phase 5c multi-fixture
    parameterisation**. Each
    `test_phase5c_person_mirror_vs_host.py` case had used only
    `person_id=1762` (Wang Anshi); parameterised every
    per-person accessor across three fixtures spanning two
    dynasties — Wang Anshi (Northern Song), Li Bai (Tang,
    32540), and Zhu Xi (Southern Song, 3257). 11 accessors × 2
    new fixtures = +22 passing cases.

    *Codex round*: caught a real false-pass class — the helper
    accepted `[] == []` as a pass, so any (accessor, person_id)
    combo with zero rows on the canonical dataset silently
    passed without exercising the upstream SQL at all. Direct
    `COUNT(*)` probes against `cbdb.sqlite` showed possessions
    and institutions were empty for all three fixtures and
    events was empty for two. Fixed with an explicit
    `_EXPECTED_EMPTY` allow-list and a bidirectional gate:
    combo NOT in allow-list AND host returns 0 → FAIL; combo
    IN allow-list AND host returns ≥1 → FAIL. Also threaded
    the `label` parameter through `_run_person_pair` so
    assertion messages identify the failing fixture by name.

  - **7e (✅ landed 2026-05-30) — Phase 4 kinships pair
    orphan-kin proof case**. The `kinships_basic_person` known
    issue documents that cbdb_replay's INNER JOIN drops orphan
    kin while Avalonia's LEFT JOIN keeps them, but the canonical
    fixture (Wang Anshi / 1762) has no orphan kin, so the gap
    was invisible. Added a runtime detector that scans the
    current build for any person with an orphan kin — both
    `c_kin_id` values that have no BIOG_MAIN match AND
    `NULL c_kin_id` rows (the INNER JOIN drops both, the
    LEFT JOIN keeps both) — and either asserts the documented
    divergence shape against that person or skips with a
    precise diagnostic. The 2026-04-30 Datadump has zero
    orphans on either path, so the test skipped on the
    landing build; the detector is wired to arm whenever a
    future dump exercises either path.

    *Codex round*: caught three issues — the detector excluded
    `NULL c_kin_id` rows even though those also fire the gap
    (INNER JOIN drops NULL); a count-only assertion
    (`rows_only_in_avalonia == expected_orphan_count`) could
    false-pass if the same person also had an unrelated
    only-in-Avalonia divergence (fixed by switching to a
    row-identity check on the spliced `kin_person_id` set);
    the skip message overstated "arms on any future dump"
    without naming the smoke-test preconditions (built
    mdb/sqlite, matching manifest SHA, pyodbc installed).

  - **7f (✅ landed 2026-05-30) — Phase 4 replay_scan kinship
    extension**. After 6a kinships became §0.b-compliant via
    `cbdb_replay.lookatkinship`; extended
    `test_phase4_replay_scan.py` to also drive that for three
    additional seed persons spanning Tang (Li Bai), Northern
    Song (Fan Zhongyan), Southern Song (Zhu Xi). Each verified
    non-empty at fixture-design time.

    *Codex round*: caught two issues — the case-payload
    validator only checked dict-with-key, not value type, so a
    corrupted payload like `{"person_id": "32540"}` or
    `{"person_id": True}` would slip past the contract boundary
    (fixed by adding non-bool-int validation; `bool` is a
    subclass of `int` in Python and is rejected explicitly);
    the kinship dispatch branch had the same empty-row trivial
    pass class 7d fixed for Phase 5c (fixed with non-empty
    asserts on both Avalonia and access rows before diffing).

  - **7g (✅ landed 2026-05-30) — GitHub Actions CI workflow**.
    `.github/` didn't exist. Added a workflow that on `push`
    and `pull_request` (1) installs the dev + harness extras
    (NOT access — pyodbc is Windows-only), (2) runs
    `pytest --collect-only` to catch import / syntax
    regressions across the entire test tree, (3) runs the
    non-DB unit tests, (4) lints `cbdb_parity/` and `tests/`
    with ruff. Does not attempt to build the mdb or sqlite
    or spin up the ParityHost; those test runs stay local.

    Also cleaned up the existing repo's ruff state so the lint
    job would actually pass: auto-fixed 29 issues (mostly
    I001 import order + unused imports) across 21 files, and
    fixed one real B904 in `cbdb_parity.parity_host` (an
    `except` clause that re-raised `ParityHostError` without
    `from exc`, losing the underlying JSON-decode failure
    context).

    *Codex round*: flagged that the initial `RUF002/RUF003`
    global ignore was broader than the actual need — it would
    silently accept future accidental ambiguous-Unicode
    anywhere in repo prose. Narrowed to
    `[tool.ruff.lint.per-file-ignores]` scoped to the three
    files where `×` / `−` are intentional technical notation
    (`access_status_query.py`, `avalonia_postings.py`,
    `test_parity_host_vs_mirror.py`); anywhere else, ruff
    resumes catching accidental homoglyphs.

  - **7h (✅ landed 2026-05-30) — ParityHost NDJSON daemon
    mode**. Every host call had previously paid ~1s of
    `dotnet run --no-build` cold-start. NDJSON daemon mode
    keeps one host process alive and streams
    `{service, sqlite_path, request}` JSON frames over stdin
    (one per line) with `{ok: …}` or `{error, stack}` framed
    responses on stdout. The one-shot mode stays available
    for debugging.

    Implementation:
    - C# side: a new `--daemon` flag puts `Program.Main` into a
      `while ((line = await Console.In.ReadLineAsync()) != null)`
      loop. Per-frame failures don't kill the daemon; EOF on
      stdin exits 0. Explicit `FlushAsync()` after each response
      line is required on Windows because stdout buffers don't
      drain until process exit otherwise.
    - Python side: `cbdb_parity.parity_host.ParityHostDaemon`
      context manager spawns the daemon, surfaces per-frame
      `{"error"}` payloads as `ParityHostError`, and on EOF
      raises `ParityHostError("daemon died after N frames")`
      carrying stderr.
    - Per-frame errors keep the daemon alive; daemon-death is
      a hard restart signal.

    Phase 8a subsequently wired this daemon into the
    heavy-traffic test files via a session fixture (see
    Phase 8); 7h itself landed the daemon + 4 smoke tests
    without switching any existing test over.

    *Codex round*: caught three issues — `per_call_timeout_seconds`
    was stored but never enforced, so a stuck dispatch would
    hang pytest forever (fixed by wrapping
    `proc.stdout.readline()` in a helper thread the main
    thread joins with the configured timeout); nothing was
    draining stderr during normal operation, so a child that
    wrote ~64 KB to stderr would deadlock before flushing the
    NDJSON response (fixed with a background thread that
    drains stderr from `__enter__` to `__exit__` into a
    bounded `deque`); `__exit__`'s timeout-then-kill path
    discarded stdout/stderr buffers and lost the only useful
    crash context (fixed by ordering close-stdin → wait →
    kill-if-needed → signal-and-join the stderr drain
    thread, so captured lines stay accessible).

  - **Expected suite delta** (additive only — no §0.b
    regressions): 7d adds ~6–10 parametrised cases, 7e adds 1,
    7f adds 3–5 replay_scan rows. 7a/7b/7c/7g/7h add no test
    cases (pure infra/docs).

  - **Out of scope for Phase 7** (per §0.a + user directive
    2026-05-30):
    - Asking `cbdb-user-mdb-tests` to add `lookat<surface>`
      modules for the 12 missing surfaces, the LEFT JOIN
      kinship variant, the GroupPeopleQueryResult-shaped
      `lookatgroupdata`, `lookatdynasty`, or
      `lookat_place_options`.
    - Asking `cbdb-desktop-app` to add Texts / Networks /
      AssociationPairs services or to expose
      `GetPeopleAtPlacesAsync`.
    - Filing GitHub issues against either repo to track any of
      the above (excluded by explicit user directive).

  - **Sequencing**: 7a → 7b → 7c → 7d → 7e → 7f → 7g → 7h.
    Each step ends with codex sign-off + `git push`. 7a/7b/7c
    are tiny doc-only changes and can be batched if convenient.
    7d → 7e → 7f all touch tests and stay green throughout. 7g
    is independent of everything else; 7h is the last and
    largest.

- **Phase 8 (planned 2026-05-30 onwards)** — Phase 7 wrap-up:
  realise the deferred 7h runtime payoff, sweep stale prose
  and comments, and bring all documentation indices into a
  consistent post-Phase-7 state. After Phase 8 the repo is in
  a true steady-state pending upstream action on every
  documented `known_issues.md` suppression.

  Discovered during the post-Phase-7 audit (2026-05-30). None
  of the items below require modifying `cbdb-desktop-app` or
  `cbdb-user-mdb-tests`; none requires filing GitHub issues
  against any repo. Per §0.a + the 2026-05-30 user directive
  those are explicitly out of scope.

  Phase 8 is split into four sub-phases, each ending with codex
  sign-off + `git push`, mirroring the Phase 5/6/7 cadence.

  - **8a — Wire `ParityHostDaemon` into the heavy-traffic
    tests**. Phase 7h landed the daemon mode + 4 smoke tests
    but did NOT switch any existing test over to it. Existing
    `invoke_parity_host` and `invoke_person_accessor_via_host`
    call sites still spawn one subprocess per call. The 7h
    WORK_PLAN delta ("from ~4m to ~30s on the host-using
    subset") has not been realised yet.

    Concretely:
    - Add a session-scoped pytest fixture in
      `tests/conftest.py` that yields a single
      `ParityHostDaemon` for the suite, started once at
      collection time and torn down at session teardown.
    - Add a thin overload (or kwarg) on
      `invoke_person_accessor_via_host` /
      `invoke_parity_host` that takes an optional
      `daemon=<ParityHostDaemon>` and, when given, calls
      `daemon.invoke(...)` instead of spawning a new
      subprocess.
    - Switch `tests/test_phase5c_person_mirror_vs_host.py`
      and `tests/test_phase4_replay_scan.py` (the two
      heaviest host consumers) to use the fixture.
    - Phase 7d's `_run_person_pair` helper is the central
      injection point on the 5c side; on the replay_scan
      side the kinship branch already calls the bridge
      directly and just needs the daemon threaded through.

    Acceptance criterion (refined during 8a codex round): the
    **host-using subset** (test_phase5c_person_mirror_vs_host
    + test_phase4_replay_scan kinship branches + test_phase7h)
    drops to ≤90s. The 5c file alone goes from ~70s to ≤30s
    (-60%+). Whole-suite runtime improves but is dominated by
    the non-host portion (build pipeline, mariadb, lint setup,
    etc.) so a ≤90s full-suite target would be over-ambitious
    and was walked back during 8a's codex review. Codex review
    of the actual final implementation, not just the plan.

  - **8b — Stale prose and code-comment sweep**. The
    post-Phase-7 audit found six locations with stale
    references that survived earlier phase boundaries:

    | location | current text | issue |
    |---|---|---|
    | `cbdb_parity/parity_host.py` docstring (lines 5–6, 109) | "the NDJSON daemon mode that amortises that comes in a later commit (Phase 5a-5 per WORK_PLAN.md)" | Daemon landed in 7h, not 5a-5. |
    | `parity_host/Cbdb.App.ParityHost/Program.cs` line 18 | "(NDJSON daemon mode comes in a later commit)" | Same. |
    | `cbdb_parity/access_office_query.py` lines 20, 95 | "Phase 4 will widen the bridge as the cross-section grows" / "Phase 4 can either teach cbdb_replay these branches or…" | Phase 4 is closed; the cross-section is now what §0.b will allow without transcription. |
    | `cbdb_parity/avalonia_biog_basic.py` line 6 | "when a follow-up wants to cover that, just pass `keyword` through" | The keyword branches are covered by Phase 6d/7's `test_biog_basic_person_id_keyword_mirror_vs_host` and `test_biog_basic_fuzzy_keyword_mirror_vs_host`. |
    | `reports/known_issues.md` "Suppression sunset" section | "Per WORK_PLAN §7, every entry in this file should also have a follow-up tracking issue in `cbdb-project`'s issue tracker." | Contradicts the 2026-05-30 user directive that excluded F1/F2. The `known_issues.md` file IS the canonical action list now; the issue-tracker requirement should be removed. |
    | `reports/known_issues.zh-Hant.md` "豁免到期管理" section | same content in Traditional Chinese | Mirror of the above. |

    Update each to either (a) point at the actual landing
    commit, or (b) drop the obsolete future-tense entirely.
    The sunset rewrite should explicitly state that
    `known_issues.md` is itself the canonical action list and
    each entry's "Suppress until" line is the actionable
    trigger. Pure documentation. Codex review.

  - **8c — Local-only stale report directory cleanup**.
    Phase 6b deleted 13 `reports/<surface>_basic_person/`
    (and `_basic`) directories from git, but local pytest
    runs from BEFORE Phase 6b left the directories on the
    filesystem:

    ```
    reports/addresses_basic_person     reports/altnames_basic
    reports/associations_basic_person  reports/biog_basic_search
    reports/detail_basic_person        reports/entries_basic_person
    reports/events_basic_person        reports/institutions_basic_person
    reports/possessions_basic_person   reports/postings_basic_person
    reports/sources_basic_person       reports/statuses_basic_person
    reports/writings_basic_person
    ```

    `git ls-tree` confirms they are NOT tracked; `git status`
    doesn't surface them either (untracked directories
    without new files don't show up). They exist as
    pre-Phase-6b sediment only.

    Action: `rm -rf` them locally as part of the Phase 8c
    commit's preamble (the rm itself produces no commit; the
    commit captures only the rationale in a follow-up
    doc-touch, or just lands as part of 8b). No `.gitignore`
    addition is needed — the corresponding pair tests are
    deleted, so nothing will re-create these directories on
    future runs. If a developer's local clone has them they
    can repeat the rm.

    Optional belt-and-braces: add a one-line note to
    `reports/.gitkeep`'s comment block (if any) reminding
    that retired per-surface directories should be removed
    locally. Discretionary; codex review only if any
    versioned file changes.

  - **8d — Phase 7 retrospective in `WORK_PLAN.md` + zh-CN
    sync**. Phase 7 was written into both `WORK_PLAN.md` and
    `WORK_PLAN.zh-CN.md` as a PLAN before execution. After
    7a–7h all landed, neither file received the matching
    `(✅ landed YYYY-MM-DD)` markers that Phase 5b/5c/5d/5e
    and Phase 6a–6d carry. Phase 7 sub-phases also accrued
    codex round findings + actual suite deltas that the
    plans don't reflect.

    Actions:
    - Add `(✅ landed 2026-05-30)` markers to each Phase 7
      sub-phase heading in `WORK_PLAN.md` (7a → 7h).
    - Append the actual codex-round deltas to each
      sub-phase's section (e.g. 7c added 4 CLI tests not 0;
      7d's empty-row guard caught a real false-pass class;
      7e's NULL c_kin_id detection extension; 7f's payload
      typing tightening; 7g's per-file RUF002/RUF003 scoping;
      7h's timeout enforcement + stderr drainer + safer exit).
    - Extend the §9 "Post-Phase-6 status (2026-05-30)" block
      with a "Post-Phase-7 status (2026-05-30)" subsection
      anchoring the new suite-count contract: 388 passed,
      7 skipped, 1 xfailed at Phase 7 close (commit `46e8186`).
    - Refresh `README.md` "Repository status" — "Phases 1–6
      landed (2026-05-27 → 2026-05-30). Current suite: 354
      passed, 6 skipped, 1 xfailed." becomes "Phases 1–7
      landed (2026-05-27 → 2026-05-30). Current suite: 388
      passed, 7 skipped, 1 xfailed." Mention `ParityHostDaemon`
      availability in the architecture diagram explanation.
    - Mirror all of the above into `WORK_PLAN.zh-CN.md`
      verbatim — § 0 split, every Phase 7 sub-phase ✅
      marker, the Phase 7 close anchor, the same
      codex-round annotations. The zh-CN mirror is
      authoritative when project decisions are made in
      Chinese; keeping it within 1–2 commits of the
      English head is part of the §0.a contract.

    Codex review on the final consolidated edit (en + zh-CN
    in one batch is fine for this purely-documentary
    sub-phase).

  - **Expected suite delta**: Phase 8 adds **zero** new
    passing tests. 8a is a runtime change, 8b/8c/8d are
    docs/local-cleanup. The 388/7/1 contract anchored at
    Phase 7 close stands as the canonical numbers after
    Phase 8.

  - **Out of scope for Phase 8** (per §0.a + 2026-05-30
    user directive):
    - Same exclusions as Phase 7 — no upstream changes, no
      issue filing against other repos.
    - The "verify CI on a real PR" item is not a separate
      task: GHA will run on the next push or PR that lands
      from any contributor, and that real-world validation
      replaces a synthetic precondition test. If CI red-lines
      on the first PR, Phase 8e (a hypothetical follow-up)
      lands the fix at that point.

  - **Sequencing**: 8a → 8b → 8c → 8d. 8a is the only
    substantive code change (and the only one with a
    suite-runtime observable); 8b/8c/8d are documentation +
    local cleanup and can be batched together if convenient,
    matching the 7a/7b/7c precedent. Each step ends with
    codex sign-off + `git push`.

- **Phase 9 (planned 2026-05-30)** — Phase 8 cosmetic
  follow-up. Two purely documentary sub-phases that the
  Phase 8 close-out scan surfaced but were small enough to
  defer to a separate pass.

  Phase 9 does not change suite count, runtime, or any
  exported API. Both items are about making the in-repo
  documentation accurately reflect post-Phase-8 reality.

  - **9a (✅ landed 2026-05-30) — Phase 7 sub-phase prose
    past-tense + codex annotations** (en + zh-CN). The 8d
    markers had given each Phase 7 sub-phase a `(✅ landed
    2026-05-30)` tag but left the paragraph bodies in
    planning-era future tense. Rewrote every Phase 7
    sub-phase paragraph in both heads as past-tense
    retrospective and appended each sub-phase's actual
    codex-round delta as a short *Codex round* annotation
    block:
      - 7a: codex clean.
      - 7b: arithmetic + suppression-table accuracy + Phase 6
        close-out anchor.
      - 7c: rewrite happy-path needed a sentinel + reports-
        dir-is-a-file rejection.
      - 7d: empty-row false-pass class → `_EXPECTED_EMPTY`
        allow-list + label threading.
      - 7e: NULL c_kin_id detection + row-identity
        assertion + skip-msg precision.
      - 7f: tighter payload typing + empty-row guard on the
        kinship dispatch branch.
      - 7g: per-file RUF002/RUF003 scoping (was global).
      - 7h: timeout enforcement + background stderr drainer
        + safer `__exit__`.

    *Codex round*: caught three issues — 7e's body
    underspecified the landed behaviour (the detector also
    needed to treat `NULL c_kin_id` as a trigger; the body
    only mentioned the no-BIOG_MAIN-match path); the 7h
    cross-reference to Phase 8a was still forward-looking
    ("later wires" → "subsequently wired"); en/zh-CN 7d
    drifted on the "spanning two dynasties" qualifier
    (added to zh-CN to match).

  - **9b (✅ landed 2026-05-30) — `AGENTS.md` Phase 7/8
    notes**. AGENTS.md had §0.b but didn't mention two
    operationally relevant landings new contributors needed
    to know about up front. Added a "Phase 7 + Phase 8
    operational landings" subsection covering:
      - the CI workflow at `.github/workflows/ci.yml`
        (Phase 7g) — what it runs, what it deliberately
        doesn't run, and which kinds of changes should keep
        it green;
      - ParityHost daemon mode via the `parity_host_daemon`
        pytest fixture (Phase 7h + 8a) — the two-mode
        contract, the fixture wiring,
        `tests/test_phase5c_person_mirror_vs_host.py` and
        `tests/test_phase4_replay_scan.py` as canonical
        opt-in examples, and the runtime delta of ~150s →
        ~61s on the host-using subset.

    *Codex round*: caught three issues — "`[access]` —
    pyodbc is Windows-only" was factually wrong (pyodbc
    itself is cross-platform; the Windows-only constraint
    is `pypyodbc` + `pywinauto` plus the Access ODBC/ACE
    driver that pyodbc binds to in this codebase); the
    "build the mdb or sqlite (Windows ODBC + Datadump
    required)" CI-exclusion line overgeneralised (sqlite
    doesn't strictly need Windows ODBC; the actual reason
    is Datadump + MariaDB cache living on the contributor's
    machine — split per-builder); the "(added 2026-05-31)"
    subsection date was future-dated relative to the actual
    commit date 2026-05-30, which exposed 37 stale
    `(✅ landed 2026-05-31)` markers propagated through
    WORK_PLAN / AGENTS / README from Phase 7 onward — all
    swept to 2026-05-30.

  - **Suite delta**: 0 — pure docs.

  - **Out of scope** (per §0.a + 2026-05-30 directive):
    same exclusions as Phase 8.

  - **Sequencing**: 9a → 9b. Each step ended with codex
    sign-off + `git push`, preserving the Phase 5/6/7/8
    codex-per-step rhythm.

  - **No further retro-fit**: Phase 9 deliberately ends the
    "each phase retroactively cleans up the previous one"
    pattern. The Phase 9 sub-phase paragraphs above carry
    their own past-tense + ✅ markers + codex annotations in
    the same commit that wrote them; no Phase 10 will land
    just to retro-fit Phase 9's prose. If a future contributor
    spots a real factual error here they fix it directly; the
    self-referential recursion stops at this paragraph.

## 9. Open questions

**Resolved during planning:**
- ✅ Artisan command identified: `db:export-to-sqlite` in `app/Console/Commands/ExportMysqlToSqlite.php`. Auxiliary index/address rebuilders also identified (see §4b).
- ✅ Avalonia headless: `Cbdb.App.Core` is interface-only (`IEntryQueryService`, `IOfficeQueryService`, `IStatusQueryService`, `IGroupPeopleService`, `IPersonBrowserService`, `IPlaceLookupService`, `IDynastyLookupService`); `Cbdb.App.Data` holds the SQLite-backed implementations. A .NET test host that instantiates the `Sqlite*Service` classes directly is structurally feasible. Phase 3 will validate with one query.
- ✅ Repo name: `cbdb-access-avalonia-parity`. Will be created under `cbdb-project` org via local `gh`.

**Decisions made during planning:**
- ✅ **Caching**: cache both the generated Access `cbdb_data.mdb` and the Avalonia `cbdb.sqlite` by Datadump filename + SHA. Re-use the cached artifact unless the Datadump SHA changes or the user passes `--rebuild`.
- ✅ **Python → Docker switch criterion**: the threshold is **not** measured in working days. Instead, during 4a (1.3b) AND 4b implementation, the user invokes Codex review on the Python-port code. If **three consecutive Codex review rounds still flag serious issues** with the Python port for that step, switch the offending command (or the entire pipeline for that side) to a Docker MySQL fallback. Codex review is **user-triggered**, not automatic.
- ✅ **Codex CLI invocation defaults**: `codex --dangerously-bypass-approvals-and-sandbox -c model=gpt-5.4 -c model_reasoning_effort=medium review --uncommitted --title "..."`. The dangerous-bypass is needed on this Windows machine because the default codex sandbox fails with `spawn setup refresh`; `gpt-5.4` + `medium` is the per-section baseline so iterative rounds stay comparable. See `AGENTS.md` for full rationale and when to deviate (e.g. CI machines, especially subtle invariants).
- ✅ **LICENSE**: Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0).
- ✅ **Empty mdb bootstrap (1.3b)**: `pypyodbc.win_create_mdb()` — empirically verified to produce a 172 KB empty mdb in one call. NOT `pyodbc` (rejects non-existent file), NOT ADOX/`win32com` (heavier), NOT a committed template binary (not reproducible). `pypyodbc` becomes a new `[access]` extra dependency, used for that single function only; all other mdb operations stay on `pyodbc`.
- ✅ **MariaDB intermediate cache (Phase 1.6)**: adopted as the default import source for both `sqlite_builder` and `mdb_builder` after the Phase 1.3b real-world build hit two Jet-specific pathologies (2 GB transaction-buffer ceiling, PK-on-duplicates `IntegrityError 23000`). The MariaDB cache is **not** a substitute for the strict-pipeline rule's prohibition on pre-existing user mdbs — it is an internal staging layer that we ourselves populate from the Datadump, gated by an in-DB SHA provenance row. The pre-1.6 `cbdb_parity.mysqldump`-direct path is retained as a fallback (`source='datadump'`) for non-Docker hosts. This decision is **complementary to** — not a substitute for — the earlier "three consecutive codex rounds → Docker MySQL fallback" trigger above, which still governs the Python-port-vs-Docker-MySQL decision **inside the sqlite builder**.

### Post-Phase-6 status (2026-05-30)

Phase 7b close-out, added 2026-05-30. Snapshot of the suite and
suppressions at the moment Phase 6 closed and Phase 7 was
opened.

**Suite-count contract (canonical numbers at Phase 6 close —
commit `dddedc1`):**

- 354 passed
- 6 skipped (all with explicit, documented reasons — see below)
- 1 xfailed (the `entry/all_jinshi_general_song` replay scan
  case where cbdb_replay has no ORDER BY and the truncated row
  sets don't overlap with Avalonia's hard LIMIT cap; documented
  inline in `tests/test_phase4_replay_scan.py` and in
  `coverage/replay_scan_results.md`).

These numbers anchor at the Phase 6 close commit, not at HEAD —
Phase 7 sub-phases push the passed count up additively (no
§0.b regressions expected; see Phase 7 sub-phase delta notes
above). Any change that moves the numbers should record the
delta in its commit message so future readers can reconstruct
the diff.

**Current §0.b-compliant pair tests (4):** Tier 1 entry / office /
status via `cbdb_replay.lookat{entry,office,status}` (Phase 3c/3d/
3e) + Tier 2 kinships via `cbdb_replay.lookatkinship` (Phase 6a).

**Active suppressions in `reports/known_issues.md` and the
condition that would re-arm each:**

| entry | re-arm condition |
|---|---|
| `kinships_basic_person` (INNER vs LEFT JOIN orphan-kin gap) | cbdb-user-mdb-tests adds a LEFT JOIN variant of LookAtKinship, OR a parity request explicitly excludes orphan-kin fixtures. Phase 7e adds an executable assertion that pins the current gap shape. |
| `associations_basic_person` (lookatassociations has no person_id input — question-shape mismatch) | cbdb-user-mdb-tests adds a per-person variant of LookAtAssociations. |
| `phase5e_lookups` (no §0.b-compliant pair for group_people / place_lookup / dynasty_lookup) | Symmetric: either cbdb-user-mdb-tests adds an appropriate `lookat*` module (place options / GroupPeopleQueryResult-shaped variant / `lookatdynasty`), OR cbdb-desktop-app converges on the existing cbdb_replay question shape (e.g. `GetPeopleAtPlacesAsync` matching `lookatplace`). |
| `tier2_per_person` (12 surfaces with no cbdb_replay.lookat* module, plus associations cross-reference) | cbdb-user-mdb-tests adds a per-surface `lookat<surface>` module. Phase 6b removed the bridges and pair tests; nothing to clean up downstream of this repo. |
| `avalonia_gap (legacy)` Texts/Networks/AssociationPairs/Place | Each surface clears independently when its service lands in cbdb-desktop-app. The umbrella entry stays open until ALL four are present; landing one does NOT clear the row — it only narrows the remaining gap. Track per-surface progress against `coverage/avalonia_queries.yaml` rather than this row. |

The `events_basic_person` / `postings_basic_person` /
`office_basic` legacy entries in `known_issues.md` are historical
breadcrumbs from before Phase 5c-final and Phase 6b retired the
corresponding code paths. They are NOT active suppressions and
have no re-arm condition — they are preserved as commit-history
context only.

All "re-arm conditions" listed above require changes in another
repo, which is exactly why they are suppressed here: per §0.a we
cannot make those changes, and per the 2026-05-30 user directive
we are not filing issues against those repos either. The
documented suppressions therefore stay until upstream takes
independent action.

**Out-of-scope work that the user has confirmed will not be done
in this repo:**

- F1 — filing GitHub issues against
  `cbdb-project/cbdb-access-avalonia-parity` (or any other repo)
  to track entries in `known_issues.md`. The
  `known_issues.md` file itself is the canonical action list as
  of 2026-05-30.
- F2 — filing GitHub issues against `cbdb-user-mdb-tests` or
  `cbdb-desktop-app` requesting the upstream changes named in
  the re-arm conditions above.

Phase 7 was the in-repo backlog as understood at Phase 6 close;
in execution it surfaced a small post-completion audit that
shipped as Phase 8, which in turn surfaced two cosmetic gaps
(Phase 7 sub-phase prose still in planning future tense, and
AGENTS.md not yet citing CI/daemon) that shipped as Phase 9.
See the Post-Phase-9 status block below for the final
close-out.

### Post-Phase-9 status (2026-05-30)

Phase 9b close-out. Phase 7 landed in eight sub-phases (7a–7h),
the post-Phase-7 audit surfaced four Phase 8 sub-phases
(8a daemon binding, 8b prose sweep, 8c report-dir cleanup,
8d retrospective), and the post-Phase-8 audit surfaced two
Phase 9 sub-phases (9a retrospective prose conversion for
Phase 7 sub-phases, 9b AGENTS.md Phase 7/8 operational notes).
With Phase 9 closed, the suite-count contract is:

- **387 passed** (was 354 at Phase 6 close → +33 net delta:
  Phase 7a/7c/7d/7e/7f/7h added 34 passing cases, then
  Phase 8a consolidated the dedicated daemon smoke test into
  the session-bound path for -1, so 354 + 34 − 1 = 387).
- **7 skipped** — all documented:
  - 3 `replay_scan[entry/…_indexyears/_entryyears]` cases
    where Avalonia EntryQueryRequest can't model
    `addr_field='person'` (upstream Avalonia gap;
    `coverage/matrix.md` Tier 1 row 2).
  - `replay_scan[status/empty_codes]` and
    `replay_scan[office/empty_codes]` (cbdb_replay picker
    contract returns no rows on an empty filter while
    Avalonia runs unfiltered; bridge can't replay both).
  - `test_phase5c_person_mirror_vs_host::test_postings_mirror_vs_host`
    (postings mirror is `NotImplementedError` post-5c-final;
    nested PersonPostingItem wire format incompatible with
    raw-row diff).
  - `test_phase4_kinships_pair::test_kinships_pair_orphan_kin_documented_divergence`
    (canonical 2026-04-30 Datadump has zero orphan kin;
    arms on any future dump that has one).
- **1 xfailed** — `replay_scan[entry/all_jinshi_general_song]`
  where cbdb_replay returns ~40k rows and Avalonia caps at
  10000 with no aligned ORDER BY; the semantics are aligned
  (verified by the dynasty-filter probe), the row sets just
  don't overlap.

These numbers anchor at the Phase 9 close (commit `da1c6d2`).
Phase 9 was pure docs, so the suite count didn't move from the
Phase 8 close anchor it inherited. Any subsequent change that
moves them should record the delta in its commit message.

Phase 8a actualised the Phase 7h daemon runtime win: the
host-using test subset (Phase 5c + replay_scan kinship + 7h
itself) drops from ~150s to ~61s with the
`parity_host_daemon` fixture active. The full
`pytest tests/` runtime is ~222s — the remaining cost is
non-host work (build pipeline, mariadb cache, lint setup)
that the daemon can't speed up.

**Active suppressions and their re-arm conditions** (mirror
of the zh-CN table; both heads carry the same list to keep
en/zh-CN parity at the Phase 9 close):

| entry | re-arm condition |
|---|---|
| `kinships_basic_person` (INNER vs LEFT JOIN orphan-kin gap) | `cbdb-user-mdb-tests` adds a LEFT JOIN variant of LookAtKinship, OR a parity request explicitly excludes orphan-kin fixtures. Phase 7e adds an executable assertion that pins the current gap shape. |
| `associations_basic_person` (lookatassociations has no person_id input) | `cbdb-user-mdb-tests` adds a per-person variant of LookAtAssociations. |
| `phase5e_lookups` (no §0.b-compliant pair for group_people / place_lookup / dynasty_lookup) | Symmetric: either `cbdb-user-mdb-tests` adds an appropriate `lookat*` module, OR `cbdb-desktop-app` converges on the existing cbdb_replay shape. |
| `tier2_per_person` (12 surfaces with no cbdb_replay.lookat*) | `cbdb-user-mdb-tests` adds per-surface `lookat<surface>` modules. Phase 6b removed the bridges and pair tests; nothing to clean up on this side. |
| `avalonia_gap (legacy)` Texts/Networks/AssociationPairs/Place | Each surface clears independently when its service lands in `cbdb-desktop-app`. The umbrella entry stays open until all four are present. |

Every re-arm condition above needs an upstream change — per
§0.a we don't make those from this repo, and per the
2026-05-30 user directive we don't file issues to request
them. The suppressions wait on independent upstream action.

After Phase 9 closes the repo is in a true steady-state. No
further in-repo work is queued; Phase 9 itself explicitly
terminates the "each phase retroactively cleans up the
previous one" pattern (see the no-further-retro-fit note at
the end of the Phase 9 section). The next change should
arrive either as a downstream consumer clearing an obsolete
suppression in `known_issues.md` or as an upstream commit
(`cbdb-user-mdb-tests` / `cbdb-desktop-app`) re-arming a
previously skipped test.
