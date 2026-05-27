"""Single-entrypoint build orchestrator (Phase 1.4).

Picks the latest Datadump, refreshes the four external repos, and runs
each sub-builder (Phase 1.2 sqlite, eventually Phase 1.3b mdb) IF the
build_manifest.json doesn't already record a successful build of that
product against the current Datadump SHA. Pass `--rebuild` to force a
full rebuild even when the manifest matches.

This is the only entrypoint that's allowed to write the top-level
`datadump` block in build_manifest.json — the sub-builders' standalone
CLIs (Phase 1.2 `cbdb-parity-build-sqlite`, Phase 1.3b `cbdb-parity-
build-mdb`) overwrite their own product slot but rely on the orchestrator
to anchor everything to one SHA.

Phase 1.3b (mdb writer) is not yet implemented — when it lands here it
slots in as another `_build_mdb_if_needed` call alongside the sqlite one,
no other plumbing changes.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import find_dotenv

from cbdb_parity.config import ConfigError, load_config
from cbdb_parity.datadump import (
    DatadumpError,
    DatadumpInfo,
    find_latest_datadump,
    open_dump_stream,
)
from cbdb_parity.mysqldump import MysqlDumpError
from cbdb_parity.refresh import RefreshError, refresh_all
from cbdb_parity.sqlite_builder import build_sqlite

_MANIFEST_NAME = "build_manifest.json"


def _workspace_root() -> Path:
    """The directory holding `.env` — repo root for editable installs,
    the user's working directory for non-editable installs. NOT `__file__`-
    based (that would resolve to site-packages for installed console
    scripts).
    """
    found = find_dotenv(usecwd=True)
    if found:
        return Path(found).resolve().parent
    # Fallback: cwd. This only fires if .env discovery failed AND
    # load_config didn't raise (which shouldn't happen, but the function
    # has to return *something*).
    return Path.cwd().resolve()


def _manifest_path() -> Path:
    """Manifest lives at the workspace root (next to .env), where AGENTS.md
    and the repo's .gitignore commentary place it for committed provenance.
    """
    return _workspace_root() / _MANIFEST_NAME


def _load_manifest(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        # Treat anything other than a JSON object (e.g. `[]`, a bare string,
        # or a number left behind by hand-editing) as an empty manifest so
        # downstream `.get(...)` calls don't blow up with AttributeError.
        return {}
    return payload


def _existing_product_sha_matches(
    manifest: dict[str, object],
    product: str,
    target_sha: str,
) -> bool:
    """Has `product` already been built from `target_sha` per the manifest?"""
    if not isinstance(manifest.get("datadump"), dict):
        return False
    if manifest["datadump"].get("sha256") != target_sha:  # type: ignore[index]
        return False
    products = manifest.get("products", {})
    if not isinstance(products, dict):
        return False
    return product in products


def _write_manifest(
    path: Path,
    info: DatadumpInfo,
    sha: str,
    products: dict[str, dict[str, object]],
) -> None:
    """Single authoritative write of the orchestrator's manifest view."""
    payload = {
        "version": 1,
        "built_at": datetime.now(UTC).isoformat(),
        "datadump": {
            "filename": info.filename,
            "sha256": sha,
            "date_tag": info.date_tag,
        },
        "products": products,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _build_sqlite_if_needed(
    info: DatadumpInfo,
    sha: str,
    out_path: Path,
    existing: dict[str, object],
    *,
    rebuild: bool,
) -> dict[str, object]:
    """Build cbdb.sqlite unless the manifest already records it for this
    SHA *at the same output path*. A BUILD_OUTPUT_DIR change invalidates
    the cache even if a stale `cbdb.sqlite` happens to sit at the new
    target — otherwise we'd rewrite the manifest with the old path while
    leaving the requested target unbuilt.
    """
    cached_entry: dict[str, object] | None = None
    if _existing_product_sha_matches(existing, "sqlite", sha):
        candidate = existing.get("products", {}).get("sqlite")  # type: ignore[union-attr]
        if isinstance(candidate, dict) and candidate.get("path") == str(out_path):
            cached_entry = candidate
    if not rebuild and cached_entry is not None and out_path.is_file():
        print(f"  [cached]   sqlite  ({cached_entry.get('rows_inserted', 0):,} rows from prior build)")
        return cached_entry

    t0 = time.time()
    print(f"  [building] sqlite  -> {out_path}")
    with open_dump_stream(info) as stream:
        stats = build_sqlite(stream, out_path)
    elapsed = time.time() - t0
    print(
        f"             {stats.tables_created} tables, "
        f"{stats.rows_inserted:,} rows in {elapsed:.1f}s"
    )
    return {
        "path": str(out_path),
        "tables_created": stats.tables_created,
        "tables_skipped": stats.tables_skipped,
        "rows_inserted": stats.rows_inserted,
        "built_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(elapsed, 2),
    }


def build_all(
    *,
    rebuild: bool = False,
) -> int:
    """Run the full Datadump → cbdb.sqlite (+ later cbdb_data.mdb) pipeline.

    Returns shell-style exit code: 0 success, 1 build failure, 2 config error.

    Per AGENTS.md and WORK_PLAN §3.4, the mandatory cross-repo refresh is
    ALWAYS run first. There is no opt-out — if the local checkout of one
    of the four external repos can't fast-forward, fix the checkout (e.g.
    `git checkout master` on a divergent branch) rather than skipping the
    gate.
    """
    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    print("[refresh] git pull --ff-only on the four external repos...")
    try:
        results = refresh_all(cfg)
    except RefreshError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for r in results:
        tag = "updated" if r.updated else "up-to-date"
        print(f"  [{tag}] {r.key}")

    # Datadump selection.
    try:
        info = find_latest_datadump(cfg.datadump_dir)
    except DatadumpError as exc:
        print(f"datadump error: {exc}", file=sys.stderr)
        return 2
    print(f"[datadump] {info.filename} ({info.date_tag})")
    print("[datadump] hashing source archive...")
    try:
        sha = info.sha256
    except OSError as exc:
        print(f"datadump hashing failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"[datadump] sha256 = {sha}")

    manifest = _manifest_path()
    existing = _load_manifest(manifest)

    sqlite_out = cfg.build_output_dir / "cbdb.sqlite"
    # Snapshot the pre-build state so the failure handler can tell whether
    # an existing good `cbdb.sqlite` was touched (in which case it's now
    # partial and must be deleted) or was never touched (in which case
    # deleting it would destroy the last usable artifact).
    pre_existed = sqlite_out.is_file()
    pre_mtime_ns = sqlite_out.stat().st_mtime_ns if pre_existed else None
    # Seed `products` with same-SHA sibling entries from the existing
    # manifest. A sqlite-only successful run must NOT silently drop the
    # mdb (or other product) that was built from the same dump earlier —
    # but only when the sibling's recorded `path` lives under the current
    # BUILD_OUTPUT_DIR. A changed BUILD_OUTPUT_DIR invalidates siblings
    # (their files don't exist at the new location).
    products: dict[str, dict[str, object]] = {}
    existing_dd = existing.get("datadump") if isinstance(existing.get("datadump"), dict) else None
    build_dir_resolved = cfg.build_output_dir.resolve()
    if existing_dd and existing_dd.get("sha256") == sha:  # type: ignore[union-attr]
        existing_products = existing.get("products", {})
        if isinstance(existing_products, dict):
            for k, v in existing_products.items():
                if not isinstance(v, dict) or k == "sqlite":
                    continue
                sib_path = v.get("path")
                if not isinstance(sib_path, str):
                    continue
                try:
                    sib_resolved = Path(sib_path).resolve()
                except OSError:
                    continue
                # Only carry forward siblings whose recorded path is
                # inside the current BUILD_OUTPUT_DIR AND whose file
                # actually still exists.
                try:
                    sib_resolved.relative_to(build_dir_resolved)
                except ValueError:
                    continue
                if not sib_resolved.is_file():
                    continue
                products[k] = v
    try:
        products["sqlite"] = _build_sqlite_if_needed(
            info=info,
            sha=sha,
            out_path=sqlite_out,
            existing=existing,
            rebuild=rebuild,
        )
        # Future: products["mdb"] = _build_mdb_if_needed(...) once Phase 1.3b lands.
    except (
        MysqlDumpError,
        DatadumpError,
        tarfile.TarError,
        OSError,
        RuntimeError,
        sqlite3.Error,
    ) as exc:
        # DatadumpError reaches us through `open_dump_stream` for malformed
        # archives (e.g. missing cbdb_data.sql member); tarfile.TarError
        # covers the case where the archive itself is corrupt (not a valid
        # tar/gzip stream) and never gets far enough to raise DatadumpError.
        print(f"build failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        # Partial-write protection: build_sqlite unlinks the destination
        # before writing, so a mid-stream failure leaves a partial file
        # behind. BUT a pre-build failure (e.g. open_dump_stream rejected
        # a corrupt archive) never touched the destination — the old good
        # artifact is intact and we must NOT delete it. Distinguish via
        # mtime: a touch implies build_sqlite started writing.
        if sqlite_out.is_file():
            now_mtime_ns = sqlite_out.stat().st_mtime_ns
            touched = (not pre_existed) or (now_mtime_ns != pre_mtime_ns)
            if touched:
                try:
                    sqlite_out.unlink()
                except OSError:
                    pass
        # Reconcile the manifest. Two cases:
        #   - existing SHA matches new SHA: only the sqlite entry is stale
        #     (other products may be fine); strip just sqlite.
        #   - existing SHA differs OR there's no existing manifest: we
        #     would have OVERWRITTEN those siblings under the new SHA; to
        #     avoid stamping them with provenance they don't own, drop
        #     the whole `products` block.
        if isinstance(existing.get("products"), dict):
            existing_dd = existing.get("datadump")
            existing_sha = existing_dd.get("sha256") if isinstance(existing_dd, dict) else None
            if existing_sha == sha:
                existing["products"].pop("sqlite", None)  # type: ignore[union-attr]
                products_to_write = existing.get("products", {})
            else:
                products_to_write = {}
            try:
                _write_manifest(manifest, info, sha, products_to_write)  # type: ignore[arg-type]
            except OSError:
                pass
        return 1

    try:
        _write_manifest(manifest, info, sha, products)
    except OSError as exc:
        # Build artefacts exist on disk but provenance write failed
        # (read-only workspace, locked file, full disk, …). Surface as a
        # build failure rather than crashing — the user needs to fix the
        # workspace permission and re-run.
        print(
            f"build artefacts written but manifest write failed: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    print(f"[manifest] {manifest}")
    print("[done] all products in sync with Datadump SHA " + sha[:12])
    return 0


def cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cbdb-parity-build-all")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="force rebuild even if the manifest already records this Datadump SHA",
    )
    args = parser.parse_args(argv)
    return build_all(rebuild=args.rebuild)
