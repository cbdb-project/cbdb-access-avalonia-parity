"""Tests for cbdb_parity.config — the .env loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from cbdb_parity.config import (
    REFRESH_KEYS,
    REQUIRED_KEYS,
    Config,
    ConfigError,
    load_config,
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip real env vars so a stray real .env can't bleed into tests."""
    for key in REQUIRED_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_load_config_success(fake_env: Path) -> None:
    cfg = load_config(fake_env)
    assert isinstance(cfg, Config)
    assert cfg.datadump_dir.is_dir()
    assert cfg.cbdb_user_mdb.is_file()
    assert cfg.build_output_dir.is_dir()


def test_load_config_missing_env_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.env")


def test_load_config_missing_key(fake_env: Path) -> None:
    """A .env that omits a required key must fail with that key named."""
    content = fake_env.read_text(encoding="utf-8")
    fake_env.write_text(
        "\n".join(line for line in content.splitlines() if not line.startswith("AVALONIA_REPO=")),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="AVALONIA_REPO"):
        load_config(fake_env)


def test_load_config_bad_dir(fake_env: Path, tmp_path: Path) -> None:
    """A .env pointing at a non-existent directory must surface that path."""
    bogus = tmp_path / "definitely-not-here"
    content = fake_env.read_text(encoding="utf-8")
    rewritten = []
    for line in content.splitlines():
        if line.startswith("AVALONIA_REPO="):
            rewritten.append(f"AVALONIA_REPO={bogus}")
        else:
            rewritten.append(line)
    fake_env.write_text("\n".join(rewritten) + "\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="AVALONIA_REPO"):
        load_config(fake_env)


def test_load_config_bad_mdb_file(fake_env: Path, tmp_path: Path) -> None:
    """CBDB_USER_MDB pointing at a missing file must fail."""
    bogus = tmp_path / "not-a-file.mdb"
    content = fake_env.read_text(encoding="utf-8")
    rewritten = []
    for line in content.splitlines():
        if line.startswith("CBDB_USER_MDB="):
            rewritten.append(f"CBDB_USER_MDB={bogus}")
        else:
            rewritten.append(line)
    fake_env.write_text("\n".join(rewritten) + "\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="CBDB_USER_MDB"):
        load_config(fake_env)


def test_build_output_dir_is_created_if_missing(tmp_path: Path) -> None:
    """BUILD_OUTPUT_DIR is the only writable scratch path; harness creates it."""
    base = tmp_path / "fake"
    base.mkdir()
    dirs = {
        "DATADUMP_DIR": base / "datadump",
        "ACCESS_TESTS_REPO": base / "cbdb-user-mdb-tests",
        "AVALONIA_REPO": base / "cbdb-desktop-app",
        "ONLINE_SERVER_REPO": base / "cbdb-online-main-server",
        "ACCESS_MYSQL_TRANSFER_REPO": base / "accessAndMySQLTransfer",
        "MYSQL2ACCESS_DIR": base / "mysql2access",
    }
    for p in dirs.values():
        p.mkdir(parents=True)
    for k in (
        "ACCESS_TESTS_REPO",
        "AVALONIA_REPO",
        "ONLINE_SERVER_REPO",
        "ACCESS_MYSQL_TRANSFER_REPO",
    ):
        (dirs[k] / ".git").mkdir()
    user_mdb = base / "CBDB_BJ_User.mdb"
    user_mdb.write_bytes(b"")

    build_dir = base / "build-not-yet-created"
    assert not build_dir.exists()

    env = tmp_path / ".env"
    lines = [f"CBDB_USER_MDB={user_mdb}", f"BUILD_OUTPUT_DIR={build_dir}"]
    lines += [f"{k}={v}" for k, v in dirs.items()]
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cfg = load_config(env)
    assert build_dir.is_dir()
    assert cfg.build_output_dir == build_dir


def test_refresh_targets_lists_exactly_the_four_git_repos(fake_env: Path) -> None:
    """The refresher must touch the 4 git repos and only those."""
    cfg = load_config(fake_env)
    targets = cfg.refresh_targets()
    assert set(targets.keys()) == set(REFRESH_KEYS)
    assert "MYSQL2ACCESS_DIR" not in targets
    assert "CBDB_USER_MDB" not in targets
    assert "DATADUMP_DIR" not in targets
    assert "BUILD_OUTPUT_DIR" not in targets


def test_env_sample_keys_match_required_keys() -> None:
    """`.env.sample` must list exactly the keys cbdb_parity.config requires.

    This is the canary that catches a `.env.sample` ↔ config.py drift.
    """
    sample = Path(__file__).resolve().parent.parent / ".env.sample"
    declared = set()
    for raw in sample.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            declared.add(line.split("=", 1)[0])

    assert declared == set(REQUIRED_KEYS), (
        f".env.sample keys diverged from REQUIRED_KEYS.\n"
        f"  In sample but not required: {declared - set(REQUIRED_KEYS)}\n"
        f"  Required but not in sample: {set(REQUIRED_KEYS) - declared}"
    )


def test_config_is_frozen(fake_env: Path) -> None:
    """Config is immutable; attempted mutation must raise."""
    cfg = load_config(fake_env)
    with pytest.raises((AttributeError, TypeError)):
        cfg.datadump_dir = Path("/tmp")  # type: ignore[misc]


def test_load_config_ignores_shell_var_when_file_has_key(
    fake_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-existing shell-exported value must NOT win over the .env file.

    Justification: a developer who switches between two checkouts will have
    stale paths exported in their shell. The .env file is the source of
    truth; load_config reads via dotenv_values() and never consults
    os.environ for the eight schema keys.
    """
    stale = Path(__file__).resolve()  # exists but isn't the dir we want
    monkeypatch.setenv("DATADUMP_DIR", str(stale))
    cfg = load_config(fake_env)
    assert cfg.datadump_dir != stale
    assert cfg.datadump_dir.is_dir()


def test_load_config_ignores_shell_var_when_file_lacks_key(
    fake_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key absent from .env must fail even if the shell has it exported.

    This is the regression for the bug where load_dotenv(override=True)
    would still leave shell-exported keys in os.environ, masking a
    legitimately missing .env entry. Fixed by reading the file only.
    """
    content = fake_env.read_text(encoding="utf-8")
    fake_env.write_text(
        "\n".join(line for line in content.splitlines() if not line.startswith("AVALONIA_REPO=")),
        encoding="utf-8",
    )
    # Shell still has the key — should be ignored.
    monkeypatch.setenv("AVALONIA_REPO", str(Path(__file__).resolve().parent))
    with pytest.raises(ConfigError, match="AVALONIA_REPO"):
        load_config(fake_env)


def test_load_config_accepts_git_worktree_style_dot_git_file(
    fake_env: Path, tmp_path: Path
) -> None:
    """A REFRESH_KEYS target whose `.git` is a FILE (git worktree /
    submodule) must be accepted, not rejected. Locks the contract that
    `Path.exists()` covers both file and directory cases.
    """
    worktree = tmp_path / "worktree-style-checkout"
    worktree.mkdir()
    # Real worktree `.git` files contain `gitdir: /some/path`.
    (worktree / ".git").write_text("gitdir: /fake/path/to/main/.git/worktrees/x\n", encoding="utf-8")

    content = fake_env.read_text(encoding="utf-8")
    rewritten = []
    for line in content.splitlines():
        if line.startswith("AVALONIA_REPO="):
            rewritten.append(f"AVALONIA_REPO={worktree}")
        else:
            rewritten.append(line)
    fake_env.write_text("\n".join(rewritten) + "\n", encoding="utf-8")

    cfg = load_config(fake_env)
    assert cfg.avalonia_repo == worktree.resolve()


def test_load_config_refresh_target_not_a_git_repo(
    fake_env: Path, tmp_path: Path
) -> None:
    """A REFRESH_KEYS target that's a directory but not a git repo must be
    rejected at config-load time. Otherwise the per-run refresher fails
    later with a cryptic git error that doesn't name the env key.
    """
    not_a_repo = tmp_path / "plain-folder"
    not_a_repo.mkdir()
    content = fake_env.read_text(encoding="utf-8")
    rewritten = []
    for line in content.splitlines():
        if line.startswith("AVALONIA_REPO="):
            rewritten.append(f"AVALONIA_REPO={not_a_repo}")
        else:
            rewritten.append(line)
    fake_env.write_text("\n".join(rewritten) + "\n", encoding="utf-8")

    with pytest.raises(ConfigError, match=r"AVALONIA_REPO.*not a git repo"):
        load_config(fake_env)


def test_load_config_resolves_relative_paths_against_env_dir(tmp_path: Path) -> None:
    """A relative path in .env is anchored at the .env file's directory,
    not at the process cwd, so callers from different cwds get the same
    answer.
    """
    base = tmp_path / "fake"
    base.mkdir()
    rel_targets = {
        "DATADUMP_DIR": "datadump",
        "ACCESS_TESTS_REPO": "cbdb-user-mdb-tests",
        "AVALONIA_REPO": "cbdb-desktop-app",
        "ONLINE_SERVER_REPO": "cbdb-online-main-server",
        "ACCESS_MYSQL_TRANSFER_REPO": "accessAndMySQLTransfer",
        "MYSQL2ACCESS_DIR": "mysql2access",
        "BUILD_OUTPUT_DIR": "build",
    }
    for v in rel_targets.values():
        (base / v).mkdir(parents=True)
    # REFRESH_KEYS dirs need a .git/ to pass git-repo validation
    for k in (
        "ACCESS_TESTS_REPO",
        "AVALONIA_REPO",
        "ONLINE_SERVER_REPO",
        "ACCESS_MYSQL_TRANSFER_REPO",
    ):
        (base / rel_targets[k] / ".git").mkdir()
    (base / "user.mdb").write_bytes(b"")

    env = base / ".env"
    lines = ["CBDB_USER_MDB=user.mdb"]
    lines += [f"{k}={v}" for k, v in rel_targets.items()]
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Run with cwd somewhere completely unrelated.
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    import os as _os
    saved = _os.getcwd()
    try:
        _os.chdir(other_cwd)
        cfg = load_config(env)
    finally:
        _os.chdir(saved)

    # All paths must resolve under `base`, not under `other_cwd`.
    assert cfg.datadump_dir == (base / "datadump").resolve()
    assert cfg.cbdb_user_mdb == (base / "user.mdb").resolve()
    assert cfg.build_output_dir == (base / "build").resolve()


def test_load_config_build_output_pointing_at_file_raises(
    fake_env: Path, tmp_path: Path
) -> None:
    """If BUILD_OUTPUT_DIR points at an existing file (a typo like
    `...\\cbdb.sqlite`), the caller must see a clean ConfigError naming the
    key — not a raw FileExistsError from mkdir.
    """
    bogus_file = tmp_path / "this-is-a-file.txt"
    bogus_file.write_text("oops", encoding="utf-8")
    content = fake_env.read_text(encoding="utf-8")
    rewritten = []
    for line in content.splitlines():
        if line.startswith("BUILD_OUTPUT_DIR="):
            rewritten.append(f"BUILD_OUTPUT_DIR={bogus_file}")
        else:
            rewritten.append(line)
    fake_env.write_text("\n".join(rewritten) + "\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="BUILD_OUTPUT_DIR"):
        load_config(fake_env)


def test_load_config_does_not_create_scratch_on_validation_failure(
    fake_env: Path, tmp_path: Path
) -> None:
    """If any DIR/FILE key fails validation, BUILD_OUTPUT_DIR must NOT be created.

    Otherwise a typo'd .env leaves orphaned dirs behind on every invocation.
    """
    bogus_dir = tmp_path / "nope"
    will_create = tmp_path / "scratch-must-not-appear"
    content = fake_env.read_text(encoding="utf-8")
    rewritten = []
    for line in content.splitlines():
        if line.startswith("AVALONIA_REPO="):
            rewritten.append(f"AVALONIA_REPO={bogus_dir}")
        elif line.startswith("BUILD_OUTPUT_DIR="):
            rewritten.append(f"BUILD_OUTPUT_DIR={will_create}")
        else:
            rewritten.append(line)
    fake_env.write_text("\n".join(rewritten) + "\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(fake_env)
    assert not will_create.exists(), "scratch dir leaked despite validation failure"


def test_load_config_default_discovers_env_from_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With env_path=None, load_config walks up from cwd to find .env.
    This must work without relying on the package's __file__ location.
    """
    base = tmp_path / "fake-repo"
    base.mkdir()
    dirs = {
        "DATADUMP_DIR": base / "datadump",
        "ACCESS_TESTS_REPO": base / "cbdb-user-mdb-tests",
        "AVALONIA_REPO": base / "cbdb-desktop-app",
        "ONLINE_SERVER_REPO": base / "cbdb-online-main-server",
        "ACCESS_MYSQL_TRANSFER_REPO": base / "accessAndMySQLTransfer",
        "MYSQL2ACCESS_DIR": base / "mysql2access",
        "BUILD_OUTPUT_DIR": base / "build",
    }
    for p in dirs.values():
        p.mkdir(parents=True)
    for k in (
        "ACCESS_TESTS_REPO",
        "AVALONIA_REPO",
        "ONLINE_SERVER_REPO",
        "ACCESS_MYSQL_TRANSFER_REPO",
    ):
        (dirs[k] / ".git").mkdir()
    user_mdb = base / "user.mdb"
    user_mdb.write_bytes(b"")

    env = base / ".env"
    lines = [f"CBDB_USER_MDB={user_mdb}"]
    lines += [f"{k}={v}" for k, v in dirs.items()]
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Chdir into a deep subdir of the fake repo so find_dotenv has to walk up.
    deep = base / "a" / "b" / "c"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)

    cfg = load_config()  # no env_path: must use find_dotenv
    assert cfg.datadump_dir == dirs["DATADUMP_DIR"].resolve()


def test_unquoted_backslash_paths_round_trip_literally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lock the python-dotenv contract: unquoted Windows backslash paths in
    `.env` survive untouched. Empirically verified at write-time on
    python-dotenv 1.2.2; this test exists to catch a future dotenv change
    that would silently corrupt Windows paths.
    """
    monkeypatch.delenv("DATADUMP_DIR", raising=False)

    base = tmp_path / "fake"
    base.mkdir()
    datadump_path = base / r"sub\with\backslashes"
    datadump_path.mkdir(parents=True)
    dirs = {
        "ACCESS_TESTS_REPO": base / "cbdb-user-mdb-tests",
        "AVALONIA_REPO": base / "cbdb-desktop-app",
        "ONLINE_SERVER_REPO": base / "cbdb-online-main-server",
        "ACCESS_MYSQL_TRANSFER_REPO": base / "accessAndMySQLTransfer",
        "MYSQL2ACCESS_DIR": base / "mysql2access",
        "BUILD_OUTPUT_DIR": base / "build",
    }
    for p in dirs.values():
        p.mkdir(parents=True)
    for k in (
        "ACCESS_TESTS_REPO",
        "AVALONIA_REPO",
        "ONLINE_SERVER_REPO",
        "ACCESS_MYSQL_TRANSFER_REPO",
    ):
        (dirs[k] / ".git").mkdir()
    user_mdb = base / "CBDB_BJ_User.mdb"
    user_mdb.write_bytes(b"")

    # Write the .env with UNQUOTED backslash paths, exactly as users would.
    env = tmp_path / ".env"
    lines = [
        f"DATADUMP_DIR={datadump_path}",
        f"CBDB_USER_MDB={user_mdb}",
    ]
    lines += [f"{k}={v}" for k, v in dirs.items()]
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cfg = load_config(env)
    # If dotenv ever starts honouring \t / \n / etc., this assertion will
    # break and the test name will tell future-us exactly what changed.
    assert cfg.datadump_dir == datadump_path
    assert str(cfg.datadump_dir).count("\\") >= 2  # at least two literal backslashes preserved
