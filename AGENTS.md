# AGENTS.md — repo conventions for AI assistants and contributors

This file documents how AI assistants (and humans) should work in this repo.
It is the authoritative source for tooling defaults, review gates, and the
"never-do" list.

## Mission (one paragraph)

This repo is a **differential testing harness**. For every CBDB Avalonia
desktop query, it must run the equivalent Access query and diff the results.
Both stacks must be fed from the **same** Datadump so any observed
disagreement is logic, not data. Every disagreement is recorded with a
hypothesised root cause.

The full plan lives in `WORK_PLAN.md` (English) and `WORK_PLAN.zh-CN.md`
(Chinese). The Chinese version is authoritative when project decisions were
made in Chinese.

## Scope contract — TEST ONLY, NEVER MODIFY OTHER REPOS

This harness's responsibility ends at **detection**. AI assistants and
human contributors MUST NOT:

- Edit files in `$AVALONIA_REPO` (`cbdb-desktop-app`) or any of the
  other four referenced external repos.
- Commit on, or push to, any of those repos' branches — local or
  remote.
- Send pull requests on behalf of this harness's work.

When a parity test fails because of an upstream Avalonia bug, the
correct response is:

1. **Don't fix it here.** Re-arm the auto-skip pattern in the failing
   test, catching the specific OperationalError (or whatever symptom)
   and `pytest.skip()` with a pointer to `reports/known_issues.md`.
2. **Record the divergence** in `reports/known_issues.md` (and the
   `.zh-Hant.md` mirror) with a `Suppress until …` clause naming the
   upstream condition that would re-arm the test.
3. **Hand the report off** to the upstream maintainer team out-of-band.
   The parity report file itself is the artifact that travels.

### No transcription (added 2026-05-30)

This repo never re-implements upstream logic in Python. Every test
calls **the upstream code itself**, not a Python equivalent of it.

- **Avalonia side**: invoke `cbdb-desktop-app`'s real services
  through `Cbdb.App.ParityHost` (see Phase 5). The Phase 3–4
  hand-extracted-SQL mirror layer (`avalonia_query_sql.py` + the
  `cbdb_parity/avalonia_*.py` SQL-extract path) was retired in
  Phase 5c-final. Do not reintroduce that pattern.
- **Access side**: invoke `cbdb-user-mdb-tests`'s
  `cbdb_replay.lookat*` modules — the historical, user-validated
  query scripts that constitute the Access-side "real code".
  Template: `cbdb_parity/access_query.py`,
  `access_office_query.py`, `access_status_query.py`. Hand-writing
  `_ACCESS_SQL` strings inside `cbdb_parity/access_*.py` to
  recreate Avalonia's joins is the Access-side equivalent of
  mirror-layer transcription and is equally forbidden.
- **No upstream → no test**: when a surface has no `cbdb_replay.lookat*`
  analogue, that surface cannot have a Phase 4 pair test under this
  rule. Use Phase 5c mirror-vs-host as the Avalonia-side oracle and
  document the Access-side gap in `reports/known_issues.md`. See
  WORK_PLAN.md Phase 6 for the cleanup plan.

## Phase 7 + Phase 8 operational landings (added 2026-05-31)

Two infrastructure pieces landed in Phase 7 / Phase 8 that new
contributors should know about up front.

### CI workflow (Phase 7g)

`.github/workflows/ci.yml` runs on every `push` and
`pull_request`. It installs only the `[dev,harness]` extras
(NOT `[access]` — pyodbc is Windows-only), runs
`pytest --collect-only` to catch import / syntax regressions
across the whole test tree, runs the non-DB unit tests
(summary_report, diff_report, config, datadump, mysqldump,
access_types, access_schema), and lints `cbdb_parity/` +
`tests/` with ruff.

What CI deliberately does NOT do:
- build the mdb or sqlite (Windows ODBC + Datadump required),
- spin up the ParityHost (needs the AVALONIA_REPO clone),
- run any test that touches the real databases.

Those test runs stay local. Contributors whose changes
touch imports, the non-DB unit tests, or the lint scope
should ensure CI stays green.

### ParityHost daemon mode (Phase 7h + Phase 8a)

`Cbdb.App.ParityHost` has two run modes:

- **One-shot** (default — `dotnet run --project … -- <service>
  <sqlite-path>`): every call spawns a fresh subprocess.
  Cold-start ~1 s per call. Suitable for ad-hoc invocation and
  for the one-shot tests in `tests/test_phase7h_parity_host_daemon.py`
  that exercise the lifecycle directly.
- **Daemon** (`--daemon` flag): a single long-lived subprocess
  reads NDJSON request frames on stdin and writes NDJSON
  response frames on stdout. Per-call cost drops to tens of
  milliseconds.

Test opt-in for the daemon goes through the
`parity_host_daemon` pytest fixture defined in
`tests/conftest.py`. A test (or a whole module via
`pytestmark = pytest.mark.usefixtures("parity_host_daemon")`)
that declares the fixture gets every `invoke_parity_host` /
`invoke_person_accessor_via_host` call routed through the
session-bound daemon automatically. `tests/test_phase5c_person_mirror_vs_host.py`
and `tests/test_phase4_replay_scan.py` are the canonical
examples. Tests that manage their own
`with ParityHostDaemon(...) as host:` block (e.g. Phase 7h's
smoke tests) still work — they bypass the ContextVar binding
and own the subprocess lifecycle directly.

The host-using subset of the suite runs ~150 s in one-shot
mode vs ~61 s under the daemon binding. The full
`pytest tests/` cost is dominated by non-host work
(build pipeline, mariadb cache, lint setup) that the daemon
doesn't speed up.

## External resources

Configured in `.env` (see `.env.sample` for the full schema and key list).
**Never copy their contents into this repo** — always reference them through
`.env`-resolved paths.

The keys split into three groups:

**(a) Four external git repos.** Pulled with `git pull --ff-only` at the
start of every parity run by `scripts/refresh_external_repos.py`:

- `ACCESS_TESTS_REPO`          → `cbdb-user-mdb-tests`
- `AVALONIA_REPO`              → `cbdb-desktop-app`
- `ONLINE_SERVER_REPO`         → `cbdb-online-main-server`
- `ACCESS_MYSQL_TRANSFER_REPO` → `accessAndMySQLTransfer`

**(b) Two non-git local resources.** The refresher skips both:

- `MYSQL2ACCESS_DIR` → a plain working folder (see `.env.sample` for the example placeholder; real path lives in your local `.env`)
- `CBDB_USER_MDB`    → a single `.mdb` file (see `.env.sample` for the example placeholder; real path lives in your local `.env`)

**(c) Two data / scratch paths.** Neither is a code repo:

- `DATADUMP_DIR`     → folder of `cbdb_data_YYYYMMDD.tar.gz` archives (input data)
- `BUILD_OUTPUT_DIR` → local scratch dir for generated `cbdb_data.mdb` and `cbdb.sqlite` (gitignored)

**(d) MariaDB intermediate cache (Phase 1.6).** Eight keys configure the
Docker MariaDB container we use as a fast import staging layer between
the Datadump and the two builders. The WORK_PLAN §4d holds the full
shape; the gist:

- `MARIADB_HOST` / `MARIADB_PORT` / `MARIADB_USER` / `MARIADB_PASSWORD`
  / `MARIADB_DATABASE` — connection.
- `MARIADB_CONTAINER_NAME` — informational; we don't auto-launch by default.
- `MARIADB_FORCE_REIMPORT` — `0/1`; bypass the in-DB SHA cache.
- `MARIADB_AUTO_LAUNCH`    — `0/1`; whether to `docker start` a stopped container.

The MariaDB cache is part of **our** pipeline; it does NOT relax the
"never substitute pre-existing user mdb files" rule from §1 of the
WORK_PLAN. It is also separate from the older "three consecutive codex
review rounds → switch to Docker MySQL fallback" gate below — that
gate governs the **SQLite builder's** Python-port-vs-Docker-MySQL
decision; the MariaDB cache is an upstream import step shared by both
builders.

## Tooling defaults

- **Python**: 3.11+. Dependency management via `uv` if available, else
  `python -m venv` + `requirements.txt`.
- **.NET**: pinned by `global.json` in `cbdb-desktop-app`; the local test
  host follows that pin.
- **Shell**: PowerShell on Windows, with `bash` fallback for cross-platform
  scripts.
- **Commit style**: Conventional Commits (`feat:`, `fix:`, `chore:`,
  `docs:`, `test:`, `refactor:`).
- **Default branch**: `main`.

## Per-section review gate (mandatory)

The user's working agreement for this repo is:

> 每完成一个小环节，都启动一个能检查代码和文档的 reviewer 进行 review，
> 要连续 review 到没有严重问题之后再放行。放行之后，还要启动 codex 进行
> 一轮额外的 review 和 debug。这些都 pass 之后，才能进行下一个小环节。

In English: every small section ("小环节") follows this gate:

1. Implement the section.
2. Spawn an internal **reviewer agent** that checks both code and docs.
3. Fix every serious issue. Re-spawn the reviewer. Repeat until the reviewer
   reports no serious issues.
4. Run **`codex` CLI** (`codex-cli`, installed locally) for an additional
   review and debug pass.
5. Only when both gates pass does the section close and the next section
   start.

**Codex invocation defaults** (per user direction, baseline for this repo):

```powershell
codex --dangerously-bypass-approvals-and-sandbox `
      -c model=gpt-5.4 `
      -c model_reasoning_effort=medium `
      review --uncommitted --title "..."
```

- `--dangerously-bypass-approvals-and-sandbox`: required on this Windows
  machine — codex's default sandbox mode hits a `spawn setup refresh`
  error that blocks every shell command, making the review impossible.
- `-c model=gpt-5.4`: pin the review model so iterative rounds give
  comparable findings across the lifetime of the repo.
- `-c model_reasoning_effort=medium`: balanced depth/latency for the
  per-section gate; bump to `high` if a phase has unusually subtle
  invariants (e.g. cache-key correctness, manifest reconciliation).

When running on a different machine (e.g. CI), revisit these flags
deliberately — the dangerous-bypass is a workstation accommodation, not
a security recommendation.

The Python-port vs Docker-MySQL fallback for the SQLite builder is governed
by this same gate, with a stricter trigger: **three consecutive codex review
rounds flagging serious issues on the Python port → switch to Docker MySQL
fallback**. Canonical script names:

- Primary  (Python port):   `scripts/build_sqlite.py`
- Fallback (Docker MySQL):  `scripts/build_sqlite_docker.py`

## Never-do list

- Never commit `.env` (it contains real local paths; placeholder values
  belong in `.env.sample`).
- Never commit generated databases (`*.mdb`, `*.sqlite`, `*.sqlite3`).
  Rebuild them from the Datadump.
- Never copy external repo contents into this repo. Reference them via
  `.env`.
- Never skip the refresher (`scripts/refresh_external_repos.py`). Every
  parity run starts with it.
- Never use `git push --force` on `main` without explicit user approval.
- Never bypass hooks (`--no-verify`, `--no-gpg-sign`, etc.).

## Reporting layout

```
reports/
  SUMMARY.md              # aggregate parity dashboard
  known_issues.md         # confirmed Avalonia gaps; suppressed from noise
  <query_id>/
    access.json           # raw Access-side result
    avalonia.json         # raw Avalonia-side result
    diff.json             # canonical diff
    summary.md            # human-readable summary
    hypothesis.md         # root cause (filled in after analysis)
```

`build_manifest.json` at repo root records the Datadump filename + SHA used
for the most recent build, so every report ties back to a specific data
version.
