"""Refresh the four external git repos referenced by `.env`.

Every parity-harness entry point calls `refresh_all()` before doing any
other work. A failure here (non-fast-forward, network error, missing
`.git`) aborts the whole run with a clear message instead of letting
downstream tools discover the staleness mid-pipeline.

Library entry points:
    `refresh_all(config=None)` — refresh all four REFRESH_KEYS targets.
    `refresh_one(key, path, runner=None)` — refresh a single repo.

The `runner` parameter is the subprocess invoker (defaults to
`subprocess.run`); tests substitute a fake runner so they exercise every
code path without spawning real git.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from cbdb_parity.config import REFRESH_KEYS, Config, ConfigError, load_config

GitRunner = Callable[[Path, tuple[str, ...]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True, slots=True)
class RefreshResult:
    key: str
    path: Path
    ok: bool
    head_before: str
    head_after: str
    message: str

    @property
    def updated(self) -> bool:
        return self.ok and self.head_before != self.head_after


class RefreshError(RuntimeError):
    """Raised when one or more refresh targets fail to fast-forward.

    Carries the complete `results` list (including the successful repos)
    so a CLI caller can still log per-repo status, not just the failures.
    """

    def __init__(self, message: str, results: list[RefreshResult]) -> None:
        super().__init__(message)
        self.results = results


def _default_runner(path: Path, args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    """Real `git -C <path> <args>` invocation."""
    return subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _head_sha(path: Path, runner: GitRunner) -> str:
    try:
        r = runner(path, ("rev-parse", "HEAD"))
    except OSError:
        return "(unknown)"
    return r.stdout.strip() if r.returncode == 0 else "(unknown)"


def refresh_one(key: str, path: Path, runner: GitRunner | None = None) -> RefreshResult:
    """Try to fast-forward `path`. Never raises; returns a RefreshResult.

    Any OSError from launching git (missing binary, permission denied,
    interrupted syscall) is converted into a failed RefreshResult rather
    than propagating — `refresh_all` relies on this so a single broken
    repo doesn't abort the loop before the other three are even tried.
    """
    run = runner or _default_runner
    head_before = _head_sha(path, run)
    try:
        pull = run(path, ("pull", "--ff-only"))
    except FileNotFoundError as exc:
        return RefreshResult(
            key=key, path=path, ok=False,
            head_before=head_before, head_after=head_before,
            message=f"git executable not found on PATH: {exc}",
        )
    except OSError as exc:
        return RefreshResult(
            key=key, path=path, ok=False,
            head_before=head_before, head_after=head_before,
            message=f"failed to invoke git: {type(exc).__name__}: {exc}",
        )
    head_after = _head_sha(path, run)
    ok = pull.returncode == 0
    if ok:
        message = (pull.stdout or "").strip() or "Already up to date."
    else:
        parts = [s.strip() for s in (pull.stderr, pull.stdout) if s and s.strip()]
        message = "\n".join(parts) if parts else "git pull failed"
    return RefreshResult(
        key=key,
        path=path,
        ok=ok,
        head_before=head_before,
        head_after=head_after,
        message=message,
    )


def refresh_all(
    config: Config | None = None,
    *,
    keys: Iterable[str] = REFRESH_KEYS,
    runner: GitRunner | None = None,
) -> list[RefreshResult]:
    """Refresh all REFRESH_KEYS targets in deterministic order.

    Returns a list of per-repo results. Raises `RefreshError` if any
    target failed, *after* attempting every target — that way a single
    flaky remote doesn't mask later problems on other repos.
    """
    if config is None:
        config = load_config()

    targets = config.refresh_targets()
    results = [refresh_one(key, targets[key], runner=runner) for key in keys]

    failed = [r for r in results if not r.ok]
    if failed:
        summary = "\n".join(f"  {r.key} ({r.path}): {r.message}" for r in failed)
        raise RefreshError(
            f"{len(failed)} of {len(results)} refresh target(s) failed:\n{summary}",
            results,
        )
    return results


def _print_results(results: list[RefreshResult]) -> None:
    for r in results:
        if not r.ok:
            print(f"  [FAILED]     {r.key:<28}  {r.message}")
        elif r.updated:
            print(f"  [updated]    {r.key:<28}  {r.head_before[:8]} -> {r.head_after[:8]}")
        else:
            print(f"  [up-to-date] {r.key:<28}  {r.head_before[:8]}")


def cli_main() -> int:
    """Console-script entry point. Wired up via `[project.scripts]` in
    pyproject.toml as `cbdb-parity-refresh`, and also invoked by the
    `scripts/refresh_external_repos.py` source-checkout bootstrap.

    Exit codes:
      0 — all repos fast-forwarded or already up to date
      1 — one or more `git pull --ff-only` failed
      2 — `.env` config error (missing keys, bad paths, not a repo)
    """
    try:
        results = refresh_all()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    except RefreshError as exc:
        _print_results(exc.results)
        print(f"\n{exc}", file=sys.stderr)
        return 1
    _print_results(results)
    return 0
