"""Run accessAndMySQLTransfer/mysql2access.ipynb verbatim against the
current MariaDB cache, writing to a fresh .mdb at the same target
folder as the user's existing cbdb.mdb (but a different filename so
we don't clobber it).

If THIS script crashes at ~268 MB too, the issue is the May-27
dataset size hitting Jet's actual hard limit, not anything our
mdb_builder does. If THIS script reaches 792 MB, the difference is
the ipynb's specific shape that we still haven't replicated.

Translated cell-by-cell from the notebook; credentials and target
path adjusted for this machine's actual MariaDB container.
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path

import pymysql
import pyodbc
import pypyodbc

# Make sure the repo root is on sys.path when this script is invoked
# directly from a fresh checkout (e.g. `python scripts/run_ipynb_verbatim.py`
# before `pip install -e .`). Other entry-points in `scripts/` do the
# same thing.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# --- Credentials resolved from .env (no machine-specific values baked in) ---
from cbdb_parity.config import load_config  # noqa: E402

_cfg = load_config()
if _cfg.mariadb is None:
    print(
        "ERROR: this diagnostic needs MariaDB configured (set the five "
        "required MARIADB_* keys in .env, see .env.sample).",
        file=sys.stderr,
    )
    sys.exit(2)
DB_HOST = _cfg.mariadb.host
DB_PORT = _cfg.mariadb.port
DB_DATABASE = _cfg.mariadb.database
DB_USERNAME = _cfg.mariadb.user
DB_PASSWORD = _cfg.mariadb.password

# Target mdb path lives under BUILD_OUTPUT_DIR so anyone running this
# diagnostic on a different clone gets a writable location they own.
# The user's original ipynb wrote to $MYSQL2ACCESS_DIR/cbdb.mdb; we
# avoid that path on purpose so we don't clobber a real production
# artifact someone may have at $MYSQL2ACCESS_DIR.
TARGET_MDB = str(_cfg.build_output_dir / "cbdb_ipynb_verbatim.mdb")

# Always start from a fresh empty .mdb (drop any prior diagnostic
# artifact). Reusing a stale file would carry Jet's accumulated page
# allocations from earlier runs and skew the size / crash-point
# measurement away from a clean ipynb-vs-builder comparison.
if os.path.exists(TARGET_MDB):
    os.remove(TARGET_MDB)
laccdb = TARGET_MDB[:-4] + ".laccdb" if TARGET_MDB.endswith(".mdb") else TARGET_MDB + ".laccdb"
if os.path.exists(laccdb):
    try:
        os.remove(laccdb)
    except OSError:
        # If Jet's lock file is still held by another process this
        # will fail; raise loudly so the user notices instead of
        # silently writing to a half-locked target.
        raise
pypyodbc.win_create_mdb(TARGET_MDB)
print(f"[bootstrap] created empty {TARGET_MDB}", flush=True)


# --- ipynb cell 0: pyodbc connection + field_type ---------------------------
field_type = {
    1: "INTEGER",
    2: "INTEGER",
    3: "INTEGER",
    5: "DOUBLE",
    7: "TIMESTAMP",
    12: "TIMESTAMP",
    16: "BIT",
    252: "LONGTEXT",
    253: "VARCHAR(255)",
}

conn_str = (
    r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
    rf"DBQ={TARGET_MDB};"
)
cnxn = pyodbc.connect(conn_str)
crsr = cnxn.cursor()


# --- ipynb cell 1 -----------------------------------------------------------
def get_table_name():
    db = pymysql.connect(host=DB_HOST, port=DB_PORT, user=DB_USERNAME,
                         password=DB_PASSWORD, database=DB_DATABASE,
                         charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
    cursor = db.cursor()
    cursor.execute("show tables")
    data = cursor.fetchall()
    db.close()
    return data


# --- ipynb cell 2 -----------------------------------------------------------
def get_columns(table_name):
    res = ""
    db = pymysql.connect(host=DB_HOST, port=DB_PORT, user=DB_USERNAME,
                         password=DB_PASSWORD, database=DB_DATABASE,
                         charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
    cursor = db.cursor()
    sql = f"select * from `{table_name}` limit 1"
    cursor.execute(sql)
    data_schema = cursor.description
    for row in data_schema:
        column_name = row[0]
        type_name = field_type[row[1]]  # KeyError → caller skips table
        res += f"`{column_name}` {type_name},"
    res = res[:-1]
    sql = f"CREATE TABLE `{table_name}` ( {res} )"
    db.close()
    return sql


def create_table(table_name, sql, table_list):
    if table_name in table_list:
        print(f"DROP TABLE `{table_name}`", flush=True)
        crsr.execute(f"DROP TABLE `{table_name}`")
        cnxn.commit()
    crsr.execute(sql)
    cnxn.commit()
    print(f"create {table_name} succeeded", flush=True)


def get_values(table_name):
    db = pymysql.connect(host=DB_HOST, port=DB_PORT, user=DB_USERNAME,
                         password=DB_PASSWORD, database=DB_DATABASE,
                         charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
    cursor = db.cursor()
    cursor.execute(f"SELECT * FROM `{table_name}`")
    data = cursor.fetchall()
    db.close()
    return data


def insert_values(table_name, rows):
    for i in range(len(rows)):
        row = []
        for _, k in rows[i].items():
            row.append(k)
        for j in range(len(row)):
            if row[j] == b"\x00":
                row[j] = 0
            elif row[j] == b"\x01":
                row[j] = 1
            elif row[j] == "0000-00-00 00:00:00":
                row[j] = None
        query = (
            f"INSERT INTO `{table_name}` values ("
            + ",".join(["?"] * len(row))
            + ");"
        )
        crsr.execute(query, tuple(row))
    cnxn.commit()


# --- ipynb cell 3 (with ADDRESSES added for like-for-like comparison) ------
# The reference ipynb omits `addresses`, but our production mdb_builder
# explicitly excludes it because it's not in the production Access
# `CopyTables` allowlist and is the known memo-heavy outlier. Including
# the same skip here keeps the 792/831 MB reference numbers comparable
# with what mdb_builder would emit (codex feedback).
SKIP_TABLES = [
    "CBDB__NAME_FTS",
    "CBDB__TRAD_SIMP_MAP",
    "users",
    "operations",
    "password_resets",
    "personal_access_tokens",
    "pinyin",
    "migrations",
    "oauth_access_tokens",
    "oauth_auth_codes",
    "oauth_clients",
    "oauth_personal_access_clients",
    "oauth_refresh_tokens",
    "audit_log",
    "ai_fill_logs",
    "nl_query_logs",
    "addresses",
]


def main():
    table_list = []
    for table_info in crsr.tables(tableType="TABLE"):
        table_list.append(table_info.table_name)
    print(f"[existing tables in mdb: {len(table_list)}]", flush=True)
    # Skip-set is case-insensitive: MariaDB returns `ADDRESSES` while
    # the ipynb's literal `SKIP_TABLES` mixes case. Normalising both
    # sides to lower lets `addresses` actually filter the uppercase
    # CBDB table.
    skip_lower = {s.lower() for s in SKIP_TABLES}
    t0 = time.time()
    for entry in get_table_name():
        for _, table_name_in_dic in entry.items():
            if table_name_in_dic.lower() in skip_lower:
                print(f"Skipped table: {table_name_in_dic}", flush=True)
                continue
            table_name = table_name_in_dic.upper()
            try:
                create_table_sql = get_columns(table_name)
            except KeyError as exc:
                print(f"Skipped table: {table_name_in_dic} (unknown type {exc})", flush=True)
                continue
            try:
                create_table(table_name, create_table_sql, table_list)
                rows_data = get_values(table_name)
                t_insert = time.time()
                insert_values(table_name, rows_data)
                size_mb = os.path.getsize(TARGET_MDB) / (1 << 20)
                print(
                    f"[{time.strftime('%H:%M:%S')}] {table_name}: "
                    f"{len(rows_data):,} rows in {time.time()-t_insert:.1f}s, "
                    f"mdb size = {size_mb:.1f} MB",
                    flush=True,
                )
            except Exception:
                size_mb = os.path.getsize(TARGET_MDB) / (1 << 20) if os.path.exists(TARGET_MDB) else 0
                elapsed = time.time() - t0
                print(
                    f"[FAILED] table={table_name} after total {elapsed:.1f}s, "
                    f"mdb size = {size_mb:.1f} MB",
                    flush=True,
                )
                traceback.print_exc()
                raise
    cnxn.close()
    total = time.time() - t0
    size_mb = os.path.getsize(TARGET_MDB) / (1 << 20)
    print(f"[SUCCESS] total {total:.1f}s, mdb size = {size_mb:.1f} MB", flush=True)


if __name__ == "__main__":
    print(f"[start] {time.strftime('%H:%M:%S')} target={TARGET_MDB}", flush=True)
    try:
        main()
    except Exception:
        sys.exit(1)
