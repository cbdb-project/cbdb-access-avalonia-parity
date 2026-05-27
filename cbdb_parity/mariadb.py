"""MariaDB intermediate cache layer (Phase 1.6, WORK_PLAN §4d).

Sits between the Datadump (.tar.gz) and the two builders (sqlite, mdb).
The .tar.gz is streamed once into a MariaDB container; both builders
then read structured rows from that DB via `pymysql` instead of
re-parsing the mysqldump file.

Why this exists:
  - `Datadump → Access mdb` via pyodbc + Microsoft Access Driver
    hits Jet's 2 GB transaction-buffer ceiling AND has no bulk-load
    fast path (cf. SQLite's `synchronous=OFF / journal_mode=OFF`).
  - The historical `accessAndMySQLTransfer/mysql2access.ipynb` flow
    (and the user's empirical measurement) routes through MariaDB.
    `tar.gz → mysql` import is fast; `MariaDB → mdb` per-row via
    pyodbc reuses the proven pattern.

What this is NOT:
  - It is NOT a substitute for the strict-pipeline rule (§1). We
    populate the MariaDB cache from OUR own Datadump archive; we do
    not consume any pre-existing user mdb file or pre-loaded
    database. The provenance row inside the DB anchors every cached
    state to a specific Datadump SHA.
  - It is NOT a replacement for either final product. `cbdb.sqlite`
    and `cbdb_data.mdb` are still the two artifacts that flow into
    Phase 3's differential harness.

The user is expected to bring the container up themselves
(`docker compose up -d` or equivalent). `MARIADB_AUTO_LAUNCH=1`
enables `docker start <CONTAINER_NAME>` for a known-stopped
container, but this is opt-in to keep the tool deterministic on
shared workstations where another process might own the docker
daemon.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import tarfile
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cbdb_parity.config import Config, MariaDbConfig
from cbdb_parity.datadump import DatadumpInfo

# Provenance table — single-row, declares which Datadump SHA the
# current DB content was imported from. Lives INSIDE the cache DB so a
# container restart with a persisted volume retains its cached state
# without any external manifest file.
_PROVENANCE_TABLE = "_cbdb_parity_provenance"
_PROVENANCE_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS `{_PROVENANCE_TABLE}` (
    datadump_sha CHAR(64) NOT NULL PRIMARY KEY,
    datadump_filename VARCHAR(255) NOT NULL,
    imported_at DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""".strip()


class MariaDbError(RuntimeError):
    """Raised on any MariaDB cache failure that isn't a plain config error."""


@dataclass(frozen=True, slots=True)
class CacheStatus:
    """Result of `ensure_imported()`: was the cache reused, or freshly imported?"""

    reused: bool                      # True = cached SHA matched; False = re-imported
    datadump_sha: str
    elapsed_seconds: float
    imported_at: datetime


# --- container / driver plumbing --------------------------------------------

def _require_mariadb_cfg(cfg: Config) -> MariaDbConfig:
    """Pull MariaDbConfig off Config or raise a clear, actionable error."""
    if cfg.mariadb is None:
        raise MariaDbError(
            "MariaDB cache is not configured. Set the 5 required MARIADB_* "
            "keys in .env (see .env.sample) or pass source='datadump' to the "
            "builder to use the Python-parser fallback."
        )
    return cfg.mariadb


def _connect(mdb: MariaDbConfig, *, database: str | None) -> Any:
    """Open a pymysql connection. `database=None` connects without USE.

    Lazy import keeps pymysql out of the non-MariaDB code path.
    """
    import pymysql

    return pymysql.connect(
        host=mdb.host,
        port=mdb.port,
        user=mdb.user,
        password=mdb.password,
        database=database,
        charset="utf8mb4",
        local_infile=False,
        autocommit=True,
    )


def _container_state(name: str) -> str | None:
    """Return `docker ps` status for the named container, or None if no
    such container exists. 'running', 'exited', 'paused', etc.

    Returns None (NOT raise) when `docker` itself isn't on PATH — the
    caller decides whether to error.
    """
    if shutil.which("docker") is None:
        return None
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}}", name],
            capture_output=True, text=True, check=False, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _endpoint_reachable(mdb: MariaDbConfig, *, timeout: float = 1.0) -> bool:
    """Is something listening on `MARIADB_HOST:MARIADB_PORT`?

    A quick TCP connect probe. We do this BEFORE any container check so
    a healthy host-installed MariaDB at the configured endpoint isn't
    blocked by an unrelated stopped container that happens to share
    `MARIADB_CONTAINER_NAME` (codex P2 finding).
    """
    try:
        with socket.create_connection((mdb.host, mdb.port), timeout=timeout):
            return True
    except OSError:
        return False


def ensure_container_running(mdb: MariaDbConfig) -> None:
    """Best-effort check that something is listening at the configured
    MariaDB endpoint, with optional `docker start` fallback.

    Order of operations:
      1. Try a quick TCP connect to `MARIADB_HOST:MARIADB_PORT`. If
         something is listening there, the endpoint is healthy and we
         return — the container state is irrelevant (the user might be
         running MariaDB on the host directly, or in a differently-
         named container that we don't manage).
      2. Otherwise, if `MARIADB_HOST` doesn't resolve to THIS machine,
         return — a remote endpoint that's unreachable is not a
         container problem; let the connection attempt later surface
         the real error.
      3. Local host AND endpoint unreachable AND container with
         `MARIADB_CONTAINER_NAME` exists in `docker ps -a` and is
         stopped:
           - If `auto_launch=True`: `docker start <name>` and wait for
             the daemon to accept connections.
           - Else: raise with the exact `docker start` command.
      4. Local host AND endpoint unreachable AND no such container:
         return (let pymysql.connect produce a clean ConnectionRefused
         later).

    We DO NOT create the container — the user is expected to manage its
    lifecycle (volumes, ports, root password).
    """
    # Fast path: if the endpoint is up, nothing else matters.
    if _endpoint_reachable(mdb):
        return
    # Endpoint not reachable. If host is remote, the container check
    # doesn't apply; let pymysql.connect raise the real error.
    if not _resolves_to_local_machine(mdb.host):
        return
    state = _container_state(mdb.container_name)
    if state is None:
        # No docker CLI or no such container — let the connection attempt
        # surface the real error. (User may run mariadb directly on the
        # host without Docker; that's also fine.)
        return
    if state == "running":
        return
    if not mdb.auto_launch:
        raise MariaDbError(
            f"MariaDB container '{mdb.container_name}' is {state!r}, not running. "
            f"Either start it (`docker start {mdb.container_name}`) or set "
            f"MARIADB_AUTO_LAUNCH=1 in .env."
        )
    try:
        subprocess.run(
            ["docker", "start", mdb.container_name],
            check=True, capture_output=True, text=True, timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        stderr = getattr(exc, "stderr", "")
        raise MariaDbError(
            f"failed to `docker start {mdb.container_name}`: {exc}\n{stderr}"
        ) from exc
    # Daemons take a moment after `docker start` before they accept
    # connections. Poll briefly rather than sleep blindly.
    deadline = time.time() + 30
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            conn = _connect(mdb, database=None)
            conn.close()
            return
        except Exception as exc:  # pragma: no cover - timing-dependent
            last_err = exc
            time.sleep(1)
    raise MariaDbError(
        f"MariaDB container '{mdb.container_name}' started but is not "
        f"accepting connections within 30s. Last error: {last_err}"
    )


# --- provenance read / write ------------------------------------------------

def _ensure_provenance_table(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(_PROVENANCE_SCHEMA)


def _read_cached_sha(conn: Any) -> tuple[str, datetime] | None:
    """Return `(sha, imported_at)` of the most-recently-imported Datadump,
    or None ONLY when the provenance table does not exist (=fresh DB).

    Any other failure (connection drop, permission denied, corrupt
    table) is propagated so `ensure_imported()` aborts rather than
    silently treating a healthy cache as empty and dropping it — codex
    P2 caught the original `except Exception` doing exactly that.

    MySQL/MariaDB returns error code 1146 ("Table 'x' doesn't exist")
    for the missing-table case; we narrow the catch to that specific
    code via pymysql's `ProgrammingError`. Any other DB error escapes.
    """
    import pymysql

    with conn.cursor() as cur:
        try:
            cur.execute(
                f"SELECT datadump_sha, imported_at FROM `{_PROVENANCE_TABLE}` "
                "ORDER BY imported_at DESC LIMIT 1"
            )
        except pymysql.err.ProgrammingError as exc:
            # exc.args[0] is the MySQL/MariaDB error code. 1146 = the
            # provenance table doesn't exist yet (fresh container or
            # post-DROP DATABASE). Anything else (permission, syntax)
            # is a real fault and must propagate.
            if exc.args and exc.args[0] == 1146:
                return None
            raise
        row = cur.fetchone()
        if not row:
            return None
        sha, imported_at = row
        return str(sha), imported_at


def _write_provenance(conn: Any, *, sha: str, filename: str, imported_at: datetime) -> None:
    """Replace the provenance row with the just-imported Datadump's info."""
    with conn.cursor() as cur:
        # Single-row semantics: clear prior entries so the table reflects
        # exactly the current cached state.
        cur.execute(f"DELETE FROM `{_PROVENANCE_TABLE}`")
        cur.execute(
            f"INSERT INTO `{_PROVENANCE_TABLE}` "
            "(datadump_sha, datadump_filename, imported_at) VALUES (%s, %s, %s)",
            (sha, filename, imported_at),
        )


# --- import implementation --------------------------------------------------

def _drop_and_create_db(conn: Any, db_name: str) -> None:
    """Reset the cache DB before a fresh import."""
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
        cur.execute(
            f"CREATE DATABASE `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )


def _open_dump_stream(info: DatadumpInfo) -> Iterable[bytes]:
    """Yield chunks of the inner `cbdb_data.sql` file from the .tar.gz.

    Streaming the tar member avoids materialising a ~3.5 GB intermediate
    file on disk before piping it into mysql. Chunk size is tuned for
    pipe writes (64 KiB).
    """
    tar = tarfile.open(info.path, "r|gz")
    try:
        for member in tar:
            if member.name == "cbdb_data.sql":
                fh = tar.extractfile(member)
                if fh is None:
                    raise MariaDbError(
                        f"{info.path}: cbdb_data.sql member could not be extracted"
                    )
                while True:
                    chunk = fh.read(64 * 1024)
                    if not chunk:
                        break
                    yield chunk
                return
        raise MariaDbError(
            f"{info.path}: archive does not contain cbdb_data.sql"
        )
    finally:
        tar.close()


_LOOPBACK_HOSTS: frozenset[str] = frozenset({
    "localhost", "127.0.0.1", "::1", "0.0.0.0",
})


def _resolves_to_local_machine(host: str) -> bool:
    """Heuristic: does `host` name THIS machine?

    Recognises loopback literals AND non-loopback names that resolve to
    the same IP as the machine's own hostname — e.g. the workstation
    name, or a hosts-file entry pointing at the local box (codex P2
    finding). Any name that doesn't resolve to a known-local IP is
    treated as remote.
    """
    h = host.strip().lower()
    if h in _LOOPBACK_HOSTS:
        return True
    try:
        target_ip = socket.gethostbyname(h)
    except (OSError, socket.gaierror):
        return False
    # Build the set of IPs that this machine is reachable at.
    local_ips: set[str] = {"127.0.0.1", "::1"}
    try:
        local_ips.add(socket.gethostbyname(socket.gethostname()))
    except (OSError, socket.gaierror):
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            local_ips.add(info[4][0])
    except (OSError, socket.gaierror):
        pass
    return target_ip in local_ips


def _container_targets_configured_endpoint(mdb: MariaDbConfig) -> bool:
    """Does `docker exec`-ing the container actually reach the server
    that `MARIADB_HOST:MARIADB_PORT` describes?

    `docker exec` runs the CLI INSIDE the container; its `-h 127.0.0.1`
    talks to the container-local mariadbd on its native 3306, NOT to
    whatever the host has mapped that port to. So we can only safely
    use docker-exec when the host-side endpoint is also pointing at
    the same server — i.e. the host resolves to THIS machine AND the
    container's MARIADB_PORT mapping matches MARIADB_PORT.

    The mapping check protects against the case where two containers
    are running and the user's `MARIADB_PORT` corresponds to a
    different container than `MARIADB_CONTAINER_NAME`.
    """
    if not _resolves_to_local_machine(mdb.host):
        return False
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "port", mdb.container_name, "3306/tcp"],
            capture_output=True, text=True, check=False, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    # `docker port <name> 3306/tcp` prints lines like "0.0.0.0:3307"
    # for each mapped interface. Accept any line whose host-port suffix
    # matches the configured MARIADB_PORT.
    suffix = f":{mdb.port}"
    for line in result.stdout.splitlines():
        if line.strip().endswith(suffix):
            return True
    return False


def _build_mysql_cli_cmd(mdb: MariaDbConfig) -> list[str]:
    """Resolve the right `mysql` CLI invocation for this host.

    Preference order:
      1. `docker exec -i <CONTAINER_NAME> mysql ...` WHEN we have
         verified that the container's `3306/tcp` is mapped to
         `MARIADB_PORT` AND `MARIADB_HOST` is a local hostname. This
         guarantees the docker-exec CLI talks to the same mariadbd
         that pymysql.connect(host=mdb.host, port=mdb.port) would.
      2. Host-installed `mysql` on PATH. We connect over TCP via the
         configured host/port — works for any reachable MariaDB,
         including a remote one.

    Raises MariaDbError if neither is available. The auto-detection
    deliberately refuses to use docker-exec when the configured
    endpoint points elsewhere, to avoid the case where we read/drop
    one server and stream the dump into a different one (codex P1).
    """
    if (
        _container_state(mdb.container_name) == "running"
        and _container_targets_configured_endpoint(mdb)
    ):
        # `-h 127.0.0.1 -P 3306` INSIDE the container — already
        # confirmed by the targeting check above to be the same
        # mariadbd that mdb.host:mdb.port points at from the host.
        return [
            "docker", "exec", "-i", mdb.container_name,
            "mysql",
            "--protocol=tcp",
            "-h", "127.0.0.1",
            "-u", mdb.user,
            f"-p{mdb.password}",
            "--default-character-set=utf8mb4",
            "--binary-mode=1",
            mdb.database,
        ]
    if shutil.which("mysql") is not None:
        return [
            "mysql",
            "--protocol=tcp",
            "-h", mdb.host,
            "-P", str(mdb.port),
            "-u", mdb.user,
            f"-p{mdb.password}",
            "--default-character-set=utf8mb4",
            "--binary-mode=1",
            mdb.database,
        ]
    raise MariaDbError(
        "No `mysql` CLI available: neither a `docker exec` path against the "
        f"running '{mdb.container_name}' container whose 3306/tcp maps to "
        f"{mdb.host}:{mdb.port}, nor a host-installed `mysql` on PATH. "
        "Start the MariaDB container (with the matching port mapping), "
        "install the MariaDB client, or set source='datadump' on the "
        "builders to skip the cache."
    )


def _import_via_mysql_cli(mdb: MariaDbConfig, info: DatadumpInfo) -> None:
    """Pipe the inner cbdb_data.sql through the `mysql` CLI.

    The CLI is dramatically faster than pymysql.execute() for a 1.4 GB
    dump because it uses MySQL's text protocol with a single connection
    and zero per-statement Python overhead.

    SET-OPTIONS sent before the dump:
      - `FOREIGN_KEY_CHECKS=0`: CBDB dumps reference rows in different
        table-load orders; foreign-key checks would otherwise refuse
        legitimate rows mid-import.
      - `UNIQUE_CHECKS=0`: same reason; declared uniques get re-validated
        on the index rebuild at commit anyway.
      - `SQL_MODE=NO_AUTO_VALUE_ON_ZERO`: lets `0000-00-00`/`0`-typed
        date columns import verbatim (downstream readers handle them).
    """
    cmd = _build_mysql_cli_cmd(mdb)
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    assert proc.stdin is not None
    try:
        try:
            # Preamble: relax cross-table constraints so CBDB's row
            # ordering doesn't get rejected on referential checks.
            # NOTE: we intentionally do NOT wrap the whole 1.4 GB dump
            # in a single START TRANSACTION ... COMMIT pair. On smaller
            # MariaDB hosts that pattern can exhaust InnoDB redo/undo
            # log space (codex P1 finding); leaving autocommit ON lets
            # the dump's own per-CREATE/per-extended-INSERT structure
            # control transaction boundaries, matching how the standard
            # `mysql < dump.sql` invocation behaves.
            proc.stdin.write(
                b"SET FOREIGN_KEY_CHECKS=0;\n"
                b"SET UNIQUE_CHECKS=0;\n"
                b"SET sql_mode='NO_AUTO_VALUE_ON_ZERO,NO_ENGINE_SUBSTITUTION';\n"
            )
            for chunk in _open_dump_stream(info):
                proc.stdin.write(chunk)
            proc.stdin.close()
        except (BrokenPipeError, OSError) as exc:
            # Connection / pipe failure: surface as MariaDbError after
            # tearing the child down so we don't leak a running mysql
            # process.
            proc.kill()
            _, stderr = proc.communicate()
            raise MariaDbError(
                f"mysql CLI rejected the import stream: {exc}; "
                f"stderr={stderr.decode('utf-8', 'replace')[:2000]}"
            ) from exc
        except (tarfile.TarError, EOFError, MariaDbError) as exc:
            # Archive corruption / missing cbdb_data.sql member /
            # truncated read mid-stream. _open_dump_stream() raises
            # these; we'd otherwise leave the spawned mysql running
            # because the outer except above doesn't catch them
            # (codex P2 finding).
            proc.kill()
            proc.communicate()
            raise MariaDbError(
                f"Datadump streaming failed during MariaDB import: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            # Truncate to keep error messages tractable.
            err = stderr.decode("utf-8", "replace")[:2000]
            out = stdout.decode("utf-8", "replace")[:500]
            raise MariaDbError(
                f"mysql CLI exited rc={proc.returncode}; stderr={err}; stdout={out}"
            )
    except BaseException:
        # Any unexpected exit (including KeyboardInterrupt) must NOT
        # leave a live mysql child behind. Best-effort terminate; the
        # original exception still propagates after.
        if proc.poll() is None:
            proc.kill()
            try:
                proc.communicate(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        raise


# --- top-level orchestration ------------------------------------------------

_ERR_UNKNOWN_DATABASE = 1049     # MySQL: "Unknown database '...'"
_ERR_TABLE_DOES_NOT_EXIST = 1146  # MySQL: "Table 'x' doesn't exist"


def _try_cache_hit(mdb: MariaDbConfig, target_sha: str) -> tuple[str, datetime] | None:
    """Cache-reuse fast path: connect directly to the configured DB and
    read the provenance row without issuing any DDL.

    Returns the cached `(sha, imported_at)` if the row exists, or None
    when the DB / provenance table doesn't exist yet (= cold cache).

    Crucially, this path requires only SELECT on the configured
    database — no CREATE DATABASE / CREATE TABLE — so a least-privilege
    cache-reader account works on the warm-cache path (codex P2 #1).
    Any non-"missing table/db" error still propagates.
    """
    import pymysql

    try:
        conn = _connect(mdb, database=mdb.database)
    except pymysql.err.OperationalError as exc:
        if exc.args and exc.args[0] == _ERR_UNKNOWN_DATABASE:
            return None
        raise
    try:
        return _read_cached_sha(conn)
    finally:
        conn.close()


def ensure_imported(cfg: Config, info: DatadumpInfo) -> CacheStatus:
    """Make sure the MariaDB cache holds the rows from `info`'s Datadump.

    Order of operations:
      1. Verify (and optionally auto-start) the container.
      2. Cache-reuse fast path: connect to the configured database and
         try to read the provenance row. NO DDL on this path — a
         read-only account works fine on warm caches.
      3. If the read returns the matching SHA AND `MARIADB_FORCE_REIMPORT=0`,
         return CacheStatus(reused=True).
      4. Otherwise (cold cache, SHA mismatch, or forced reimport):
         CREATE the DB if missing, DROP+CREATE for a clean slate, pipe
         the Datadump through `mysql`, then re-open and write the
         provenance row.

    Any `pymysql` exception is wrapped into a `MariaDbError` so the
    `cbdb-parity-import-mariadb` CLI's `except MariaDbError` handler
    produces a readable error message rather than a traceback
    (codex P2 #2).

    Idempotent on a healthy cache: callers can invoke this every run.
    """
    import pymysql

    mdb = _require_mariadb_cfg(cfg)
    ensure_container_running(mdb)

    t0 = time.time()
    target_sha = info.sha256
    target_imported_at = datetime.now(UTC)

    try:
        cached = _try_cache_hit(mdb, target_sha)
        if (
            cached is not None
            and cached[0] == target_sha
            and not mdb.force_reimport
        ):
            return CacheStatus(
                reused=True,
                datadump_sha=target_sha,
                elapsed_seconds=round(time.time() - t0, 2),
                imported_at=cached[1],
            )

        # Cold cache, SHA mismatch, or forced reimport — issue DDL now.
        # CREATE-if-needed on a "no-db" connection covers the brand-new-
        # container case; the subsequent DROP+CREATE gives the importer
        # a clean schema regardless.
        server_conn = _connect(mdb, database=None)
        try:
            with server_conn.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{mdb.database}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            _drop_and_create_db(server_conn, mdb.database)
        finally:
            server_conn.close()
    except pymysql.MySQLError as exc:
        raise MariaDbError(
            f"MariaDB pre-import check failed: {type(exc).__name__}: {exc}"
        ) from exc

    # Heavy work: actually run the dump through mysql. Already wraps its
    # own subprocess/IO failures in MariaDbError.
    _import_via_mysql_cli(mdb, info)

    # Re-open against the freshly-loaded DB to (re-)create the
    # provenance table and write the cache row. Wrap pymysql errors so
    # late-stage failures (e.g. lost connection right after import)
    # also surface cleanly via the CLI's MariaDbError handler.
    try:
        db_conn = _connect(mdb, database=mdb.database)
        try:
            _ensure_provenance_table(db_conn)
            _write_provenance(
                db_conn,
                sha=target_sha,
                filename=info.filename,
                imported_at=target_imported_at,
            )
        finally:
            db_conn.close()
    except pymysql.MySQLError as exc:
        raise MariaDbError(
            f"MariaDB provenance write failed after a successful import: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    return CacheStatus(
        reused=False,
        datadump_sha=target_sha,
        elapsed_seconds=round(time.time() - t0, 2),
        imported_at=target_imported_at,
    )


# --- standalone CLI ---------------------------------------------------------

def cli_main(argv: list[str] | None = None) -> int:
    """`cbdb-parity-import-mariadb` entry point.

    Exit codes:
      0 — cache present (reused or freshly imported)
      1 — import failed (mysql CLI error, connection lost, ...)
      2 — .env / config error or no Datadump found
    """
    import argparse

    from cbdb_parity.config import ConfigError, load_config
    from cbdb_parity.datadump import DatadumpError, find_latest_datadump

    parser = argparse.ArgumentParser(prog="cbdb-parity-import-mariadb")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-import even if the cache SHA matches (equivalent to "
             "MARIADB_FORCE_REIMPORT=1 for this single invocation).",
    )
    args = parser.parse_args(argv)

    try:
        cfg = load_config()
        info = find_latest_datadump(cfg.datadump_dir)
    except (ConfigError, DatadumpError) as exc:
        print(f"config / discovery error: {exc}", file=sys.stderr)
        return 2

    if cfg.mariadb is None:
        print(
            "MariaDB cache not configured (no MARIADB_* keys in .env). "
            "See .env.sample for the schema.",
            file=sys.stderr,
        )
        return 2

    # --force overrides .env's MARIADB_FORCE_REIMPORT for this call. We
    # rebuild MariaDbConfig immutably with force_reimport=True; the
    # rest of cfg stays the same.
    effective_cfg = cfg
    if args.force and not cfg.mariadb.force_reimport:
        from dataclasses import replace
        effective_cfg = replace(cfg, mariadb=replace(cfg.mariadb, force_reimport=True))

    print(f"Source       : {info.path}")
    print(f"Date tag     : {info.date_tag}")
    print(f"MariaDB host : {cfg.mariadb.host}:{cfg.mariadb.port}/{cfg.mariadb.database}")
    print("Hashing source archive...")
    try:
        sha = info.sha256
    except OSError as exc:
        print(f"hashing failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"SHA256       : {sha}")
    print()

    try:
        status = ensure_imported(effective_cfg, info)
    except MariaDbError as exc:
        print(f"MariaDB import failed: {exc}", file=sys.stderr)
        return 1

    verb = "reused cached" if status.reused else "re-imported"
    print(f"[mariadb] {verb} Datadump SHA {status.datadump_sha[:12]} "
          f"in {status.elapsed_seconds:.1f}s")
    return 0


__all__ = [
    "CacheStatus",
    "MariaDbError",
    "cli_main",
    "ensure_container_running",
    "ensure_imported",
]
