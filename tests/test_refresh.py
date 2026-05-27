"""Tests for cbdb_parity.refresh — the cross-repo refresher."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cbdb_parity.config import REFRESH_KEYS, load_config
from cbdb_parity.refresh import (
    RefreshError,
    RefreshResult,
    refresh_all,
    refresh_one,
)


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class _FakeRunner:
    """Records calls and returns canned responses per (cmd-tuple) prefix."""

    def __init__(self) -> None:
        self.calls: list[tuple[Path, tuple[str, ...]]] = []
        self.responses: dict[tuple[str, ...], subprocess.CompletedProcess[str]] = {}
        self.default: subprocess.CompletedProcess[str] = _completed(0, "Already up to date.\n")

    def respond(self, args: tuple[str, ...], result: subprocess.CompletedProcess[str]) -> None:
        self.responses[args] = result

    def __call__(self, path: Path, args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        self.calls.append((path, args))
        return self.responses.get(args, self.default)


def test_refresh_one_success_already_up_to_date(tmp_path: Path) -> None:
    runner = _FakeRunner()
    runner.respond(("rev-parse", "HEAD"), _completed(0, "abc123def456\n"))
    runner.respond(("pull", "--ff-only"), _completed(0, "Already up to date.\n"))

    r = refresh_one("X", tmp_path, runner=runner)
    assert r.ok
    assert r.head_before == "abc123def456"
    assert r.head_after == "abc123def456"
    assert not r.updated
    assert "up to date" in r.message.lower()


def test_refresh_one_success_fast_forwarded(tmp_path: Path) -> None:
    """Different SHAs before vs after the pull → r.updated == True."""
    head_responses = iter(["aaaa1111\n", "bbbb2222\n"])

    def runner(path: Path, args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        if args == ("rev-parse", "HEAD"):
            return _completed(0, next(head_responses))
        return _completed(0, "Fast-forwarded.\n")

    r = refresh_one("Y", tmp_path, runner=runner)
    assert r.ok
    assert r.head_before == "aaaa1111"
    assert r.head_after == "bbbb2222"
    assert r.updated


def test_refresh_one_handles_missing_git_binary(tmp_path: Path) -> None:
    """If the git executable isn't on PATH, refresh_one must return a
    failed RefreshResult — NOT propagate FileNotFoundError out of the
    'never raises' contract."""
    def runner(path: Path, args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(2, "no such file", "git")

    r = refresh_one("V", tmp_path, runner=runner)
    assert not r.ok
    assert r.head_before == "(unknown)"
    assert "git executable" in r.message.lower()


def test_refresh_one_handles_generic_oserror_from_subprocess(tmp_path: Path) -> None:
    """Any OSError from launching git (PermissionError, interrupted system
    call, etc.) must be caught and surfaced as a failed RefreshResult, not
    propagated — otherwise refresh_all would abort early and skip the
    remaining repos."""
    def runner(path: Path, args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        raise PermissionError(13, "Permission denied", "git")

    r = refresh_one("U", tmp_path, runner=runner)
    assert not r.ok
    assert "permissionerror" in r.message.lower()


def test_refresh_all_continues_after_oserror_from_one_repo(fake_env: Path) -> None:
    """A PermissionError on AVALONIA_REPO must not stop the other 3 from
    being attempted; the final RefreshError must still carry all 4 results."""
    cfg = load_config(fake_env)
    bad_path = cfg.refresh_targets()["AVALONIA_REPO"]

    def runner(path: Path, args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        if path == bad_path:
            raise PermissionError(13, "Permission denied", "git")
        if args == ("rev-parse", "HEAD"):
            return _completed(0, "1234\n")
        return _completed(0, "Already up to date.\n")

    with pytest.raises(RefreshError) as excinfo:
        refresh_all(cfg, runner=runner)
    assert len(excinfo.value.results) == len(REFRESH_KEYS)
    assert {r.key for r in excinfo.value.results if not r.ok} == {"AVALONIA_REPO"}


def test_refresh_one_failure_non_ff(tmp_path: Path) -> None:
    runner = _FakeRunner()
    runner.respond(("rev-parse", "HEAD"), _completed(0, "cafe1234\n"))
    runner.respond(
        ("pull", "--ff-only"),
        _completed(1, stdout="", stderr="fatal: Not possible to fast-forward, aborting.\n"),
    )

    r = refresh_one("Z", tmp_path, runner=runner)
    assert not r.ok
    assert "fast-forward" in r.message.lower()
    assert r.head_before == "cafe1234"


def test_refresh_one_failure_unreadable_head(tmp_path: Path) -> None:
    """If `git rev-parse HEAD` fails (e.g. corrupt repo), the head sha is
    reported as '(unknown)' but the pull is still attempted."""
    runner = _FakeRunner()
    runner.respond(("rev-parse", "HEAD"), _completed(128, stderr="fatal: not a git repo"))
    runner.respond(("pull", "--ff-only"), _completed(128, stderr="fatal: not a git repo"))

    r = refresh_one("W", tmp_path, runner=runner)
    assert not r.ok
    assert r.head_before == "(unknown)"
    assert r.head_after == "(unknown)"


def test_refresh_all_calls_each_refresh_key_once_in_order(fake_env: Path) -> None:
    cfg = load_config(fake_env)
    runner = _FakeRunner()
    runner.respond(("rev-parse", "HEAD"), _completed(0, "deadbeef\n"))
    runner.respond(("pull", "--ff-only"), _completed(0, "Already up to date.\n"))

    results = refresh_all(cfg, runner=runner)
    assert len(results) == len(REFRESH_KEYS)
    assert [r.key for r in results] == list(REFRESH_KEYS)  # deterministic order
    assert all(r.ok for r in results)

    targets = cfg.refresh_targets()
    pull_call_paths = [c[0] for c in runner.calls if c[1] == ("pull", "--ff-only")]
    assert pull_call_paths == [targets[k] for k in REFRESH_KEYS]


def test_refresh_all_aborts_with_one_failure_but_runs_all(fake_env: Path) -> None:
    """A flaky AVALONIA_REPO must not stop ONLINE_SERVER_REPO from being
    attempted. All four must run; THEN raise."""
    cfg = load_config(fake_env)
    cfg_targets = cfg.refresh_targets()

    failing_path = cfg_targets["AVALONIA_REPO"]

    def runner(path: Path, args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        if args == ("rev-parse", "HEAD"):
            return _completed(0, "1234\n")
        if args == ("pull", "--ff-only") and path == failing_path:
            return _completed(1, stderr="fatal: divergent")
        return _completed(0, "Already up to date.\n")

    seen_paths: list[Path] = []
    orig = runner

    def tracking(path: Path, args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        if args == ("pull", "--ff-only"):
            seen_paths.append(path)
        return orig(path, args)

    with pytest.raises(RefreshError, match="AVALONIA_REPO") as excinfo:
        refresh_all(cfg, runner=tracking)

    # All four pulls must have been attempted, not short-circuited.
    assert len(seen_paths) == len(REFRESH_KEYS)
    # RefreshError carries the full results list including the successes.
    assert hasattr(excinfo.value, "results")
    assert len(excinfo.value.results) == len(REFRESH_KEYS)
    ok_keys = {r.key for r in excinfo.value.results if r.ok}
    fail_keys = {r.key for r in excinfo.value.results if not r.ok}
    assert fail_keys == {"AVALONIA_REPO"}
    assert "AVALONIA_REPO" not in ok_keys


def test_refresh_all_only_touches_refresh_keys(fake_env: Path) -> None:
    """The two Desktop paths and the data paths must NEVER be invoked."""
    cfg = load_config(fake_env)
    runner = _FakeRunner()
    runner.respond(("rev-parse", "HEAD"), _completed(0, "abcd\n"))
    runner.respond(("pull", "--ff-only"), _completed(0, "Already up to date.\n"))

    refresh_all(cfg, runner=runner)
    touched_paths = {p for p, _ in runner.calls}

    # Forbidden — these are non-git or data paths
    forbidden = {
        cfg.mysql2access_dir,
        cfg.cbdb_user_mdb,
        cfg.datadump_dir,
        cfg.build_output_dir,
    }
    assert touched_paths.isdisjoint(forbidden)


def test_refresh_result_updated_property() -> None:
    r_same = RefreshResult("K", Path("/x"), True, "aaa", "aaa", "up to date")
    r_diff = RefreshResult("K", Path("/x"), True, "aaa", "bbb", "fast-forwarded")
    r_fail = RefreshResult("K", Path("/x"), False, "aaa", "aaa", "fatal")
    assert not r_same.updated
    assert r_diff.updated
    assert not r_fail.updated
