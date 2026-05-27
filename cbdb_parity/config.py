"""Load and validate the eight `.env` keys defined in `.env.sample`.

Every harness entrypoint goes through `load_config()` so a missing or
mistyped env key fails loud and early instead of producing silent wrong
behaviour downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values, find_dotenv

# Single source of truth for the env-key set. Matches `.env.sample` exactly.
# Update both files together if a key is added or renamed.
REQUIRED_KEYS: tuple[str, ...] = (
    "DATADUMP_DIR",
    "CBDB_USER_MDB",
    "ACCESS_TESTS_REPO",
    "AVALONIA_REPO",
    "ONLINE_SERVER_REPO",
    "ACCESS_MYSQL_TRANSFER_REPO",
    "MYSQL2ACCESS_DIR",
    "BUILD_OUTPUT_DIR",
)

# Keys whose values must be existing directories on disk at config-load time.
# A missing dir indicates an `.env` typo or a not-yet-cloned dependency.
DIR_KEYS: frozenset[str] = frozenset({
    "DATADUMP_DIR",
    "ACCESS_TESTS_REPO",
    "AVALONIA_REPO",
    "ONLINE_SERVER_REPO",
    "ACCESS_MYSQL_TRANSFER_REPO",
    "MYSQL2ACCESS_DIR",
})

# Keys whose values must be existing files (not directories).
FILE_KEYS: frozenset[str] = frozenset({
    "CBDB_USER_MDB",
})

# Keys representing scratch / output paths — created on demand if missing.
WRITABLE_KEYS: frozenset[str] = frozenset({
    "BUILD_OUTPUT_DIR",
})

# Subset of REQUIRED_KEYS whose target is a git repo and is refreshed by
# `scripts/refresh_external_repos.py` before every parity run.
REFRESH_KEYS: tuple[str, ...] = (
    "ACCESS_TESTS_REPO",
    "AVALONIA_REPO",
    "ONLINE_SERVER_REPO",
    "ACCESS_MYSQL_TRANSFER_REPO",
)


class ConfigError(RuntimeError):
    """Raised when the env-file fails validation."""


@dataclass(frozen=True, slots=True)
class Config:
    """Resolved, validated environment for a parity run.

    Attribute names mirror the env-key names exactly (lowercased) so that the
    invariant "what's in `.env.sample` is what's on this object" is obvious.
    """

    datadump_dir: Path
    cbdb_user_mdb: Path
    access_tests_repo: Path
    avalonia_repo: Path
    online_server_repo: Path
    access_mysql_transfer_repo: Path
    mysql2access_dir: Path
    build_output_dir: Path

    def refresh_targets(self) -> dict[str, Path]:
        """Return the four git-repo paths that must be `git pull`'d per run.

        Matches `REFRESH_KEYS`; the two non-git Desktop paths are excluded.
        """
        return {
            "ACCESS_TESTS_REPO": self.access_tests_repo,
            "AVALONIA_REPO": self.avalonia_repo,
            "ONLINE_SERVER_REPO": self.online_server_repo,
            "ACCESS_MYSQL_TRANSFER_REPO": self.access_mysql_transfer_repo,
        }


def load_config(env_path: Path | None = None) -> Config:
    """Load `.env`, validate all required keys, return a frozen `Config`.

    `env_path=None` walks up from the current working directory looking
    for the nearest `.env` (via `dotenv.find_dotenv(usecwd=True)`). This
    works for editable installs *and* for non-editable installs where the
    package itself lives under `site-packages/`. Pass a path explicitly
    in tests or non-cwd callers.

    Uses `dotenv_values()` (NOT `load_dotenv`) so the `.env` file is the
    sole source of truth: a key absent from the file is treated as missing
    even if a stale value is exported in the surrounding shell. Nothing
    leaks into `os.environ`.

    Relative paths in `.env` are resolved against the `.env` file's
    directory, not the process cwd, so a caller running from anywhere
    gets the same answer.

    Validation order: missing-keys → path checks → mkdir(scratch). The
    scratch dir is created ONLY after all other validation passes, so a
    failing `load_config()` leaves the filesystem untouched.
    """
    if env_path is None:
        found = find_dotenv(usecwd=True)
        if not found:
            raise ConfigError(
                ".env not found (walked up from cwd). "
                "Copy .env.sample to .env in the repo root and fill in real paths."
            )
        env_path = Path(found)
    env_path = env_path.resolve()

    if not env_path.exists():
        raise ConfigError(
            f".env not found at {env_path}. "
            f"Copy .env.sample to .env and fill in the real local paths."
        )

    file_values: dict[str, str | None] = dotenv_values(env_path)
    anchor = env_path.parent

    missing = [k for k in REQUIRED_KEYS if not (file_values.get(k) or "").strip()]
    if missing:
        raise ConfigError(
            f".env is missing required keys: {', '.join(missing)}. "
            f"See .env.sample for the full schema."
        )

    def _resolve(raw: str) -> Path:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = (anchor / p).resolve()
        return p

    resolved: dict[str, Path] = {k: _resolve(file_values[k]) for k in REQUIRED_KEYS}  # type: ignore[arg-type]

    errors: list[str] = []
    for key in DIR_KEYS:
        if not resolved[key].is_dir():
            errors.append(f"{key} -> {resolved[key]} is not an existing directory")
    for key in FILE_KEYS:
        if not resolved[key].is_file():
            errors.append(f"{key} -> {resolved[key]} is not an existing file")
    # Refresh targets are documented as git repos. Catch the typo where a
    # user points one at an unrelated local folder NOW, instead of letting
    # `git pull` fail with a cryptic error mid-run.
    #
    # `(p / ".git").exists()` returns True whether `.git` is a directory
    # (regular checkout) OR a file (git worktree / submodule pointer).
    # Both cases are accepted; only a missing `.git` is rejected.
    for key in REFRESH_KEYS:
        p = resolved[key]
        if p.is_dir() and not (p / ".git").exists():
            errors.append(f"{key} -> {p} is a directory but not a git repo (missing .git)")
    for key in WRITABLE_KEYS:
        # Pre-validate: if the path already exists but is NOT a directory
        # (typically a mistyped target like ...\cbdb.sqlite), bail out with
        # a ConfigError instead of letting mkdir raise a bare FileExistsError.
        p = resolved[key]
        if p.exists() and not p.is_dir():
            errors.append(f"{key} -> {p} exists but is not a directory")

    if errors:
        raise ConfigError(
            ".env path validation failed:\n  - " + "\n  - ".join(errors)
        )

    for key in WRITABLE_KEYS:
        try:
            resolved[key].mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            # Unmapped drive, permission denied, ENOENT under a parent that
            # itself is gone — surface a ConfigError naming the key instead
            # of a bare OSError that doesn't say which env var caused it.
            raise ConfigError(
                f"{key} -> failed to create {resolved[key]}: {exc}"
            ) from exc

    return Config(
        datadump_dir=resolved["DATADUMP_DIR"],
        cbdb_user_mdb=resolved["CBDB_USER_MDB"],
        access_tests_repo=resolved["ACCESS_TESTS_REPO"],
        avalonia_repo=resolved["AVALONIA_REPO"],
        online_server_repo=resolved["ONLINE_SERVER_REPO"],
        access_mysql_transfer_repo=resolved["ACCESS_MYSQL_TRANSFER_REPO"],
        mysql2access_dir=resolved["MYSQL2ACCESS_DIR"],
        build_output_dir=resolved["BUILD_OUTPUT_DIR"],
    )
