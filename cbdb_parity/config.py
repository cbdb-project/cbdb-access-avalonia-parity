"""Load and validate the `.env` keys defined in `.env.sample`.

Every harness entrypoint goes through `load_config()` so a missing or
mistyped env key fails loud and early instead of producing silent wrong
behaviour downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values, find_dotenv

# Single source of truth for the path-typed env-key set. Matches the
# corresponding entries in `.env.sample` exactly. MariaDB connection keys
# (string / int / bool) are NOT in this tuple — see MARIADB_REQUIRED_KEYS.
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

# Top-tier build cache switch. When `1` (default) AND both .build
# products exist AND build_manifest.json records them with matching
# paths, `build_all` short-circuits right after the refresh step:
# no Datadump scan, no MariaDB connect, no builder run. When `0`,
# the full pipeline runs every time (downstream MariaDB / manifest
# layers still cache by SHA, so a same-SHA run still finishes
# quickly, but the cost of touching Datadump + connecting to MariaDB
# is paid every time).
_USE_CACHE_KEY: str = "CBDB_PARITY_USE_CACHE"
_USE_CACHE_DEFAULT: str = "1"

# MariaDB intermediate cache (Phase 1.6 / WORK_PLAN §4d). Required when
# `Config.has_mariadb` is consulted; absence of these keys is NOT an
# error at load_config() time because the Datadump-direct fallback path
# (source='datadump') still works without them. Callers that actually
# want to use the MariaDB cache check `cfg.mariadb` is not None.
MARIADB_REQUIRED_KEYS: tuple[str, ...] = (
    "MARIADB_HOST",
    "MARIADB_PORT",
    "MARIADB_USER",
    "MARIADB_PASSWORD",
    "MARIADB_DATABASE",
)

# Optional MariaDB knobs with safe defaults if absent from .env.
MARIADB_OPTIONAL_KEYS: tuple[tuple[str, str], ...] = (
    ("MARIADB_CONTAINER_NAME", "cbdb-parity-mariadb"),
    ("MARIADB_FORCE_REIMPORT", "0"),
    ("MARIADB_AUTO_LAUNCH", "0"),
)

# Top-tier cache switch is documented in .env.sample as an optional
# key with default `1`. Listed here so the `.env.sample` ↔ config
# drift canary in test_config.py picks it up.
OPTIONAL_KEYS_WITH_DEFAULTS: tuple[tuple[str, str], ...] = (
    (_USE_CACHE_KEY, _USE_CACHE_DEFAULT),
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
class MariaDbConfig:
    """Resolved MariaDB connection / behaviour config (Phase 1.6 §4d).

    Present on `Config.mariadb` only when all 5 required MARIADB_* keys
    are set in `.env`. Callers that want the MariaDB cache check for
    `cfg.mariadb is not None` and surface a clean error to the user if
    not configured rather than connecting with half-resolved defaults.
    """

    host: str
    port: int
    user: str
    password: str
    database: str
    container_name: str
    force_reimport: bool
    auto_launch: bool


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
    mariadb: MariaDbConfig | None = None
    use_cache: bool = True

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

    # MariaDB validation runs BEFORE mkdir() so a typo in any MARIADB_*
    # key fails the load WITHOUT mutating the filesystem — preserves
    # the documented "failing load_config() leaves the FS untouched"
    # invariant (codex P2).
    mariadb_cfg = _load_mariadb_config(file_values)
    use_cache = _parse_bool(
        (file_values.get(_USE_CACHE_KEY) or _USE_CACHE_DEFAULT),
        key=_USE_CACHE_KEY,
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
        mariadb=mariadb_cfg,
        use_cache=use_cache,
    )


def _parse_bool(raw: str, *, key: str) -> bool:
    """Parse a 0/1/true/false/yes/no value from `.env`. Reject anything else.

    The .env semantics are explicit on purpose — silent coercion (e.g.
    treating an empty string as False) would mask typos that change
    pipeline behaviour. The exact accepted vocabulary mirrors what
    `dotenv` itself documents.
    """
    val = (raw or "").strip().lower()
    if val in {"1", "true", "yes", "on"}:
        return True
    if val in {"0", "false", "no", "off", ""}:
        return False
    raise ConfigError(
        f"{key}={raw!r} is not a valid boolean (use 0/1, true/false, yes/no)"
    )


def _load_mariadb_config(file_values: dict[str, str | None]) -> MariaDbConfig | None:
    """Resolve `MARIADB_*` keys to a MariaDbConfig, or None if absent.

    Returning None when the keys are missing keeps the Datadump-direct
    fallback path workable on hosts without Docker; callers that want
    the MariaDB cache layer check for None and raise a clear error
    pointing at `.env.sample`.

    Validation is all-or-nothing: any of the five required keys missing
    OR present-but-blank → `mariadb=None` on the returned Config (NOT
    an error). A partially-filled MariaDB section (e.g. host set, port
    blank) raises ConfigError to catch typos that would otherwise yield
    a confusing connection failure deeper in the pipeline.
    """
    raw: dict[str, str] = {
        k: (file_values.get(k) or "").strip() for k in MARIADB_REQUIRED_KEYS
    }
    filled = [k for k, v in raw.items() if v]
    if not filled:
        return None
    if len(filled) < len(MARIADB_REQUIRED_KEYS):
        missing = [k for k in MARIADB_REQUIRED_KEYS if not raw[k]]
        raise ConfigError(
            ".env partially specifies the MariaDB cache (Phase 1.6 §4d): "
            f"set keys {filled!r}, missing keys {missing!r}. "
            "Either fill in all 5 required MARIADB_* keys (see .env.sample) "
            "or remove the partial ones entirely to disable the cache."
        )

    try:
        port = int(raw["MARIADB_PORT"])
    except ValueError as exc:
        raise ConfigError(
            f"MARIADB_PORT={raw['MARIADB_PORT']!r} is not an integer"
        ) from exc

    optional_resolved: dict[str, str] = {}
    for key, default in MARIADB_OPTIONAL_KEYS:
        optional_resolved[key] = (file_values.get(key) or "").strip() or default

    return MariaDbConfig(
        host=raw["MARIADB_HOST"],
        port=port,
        user=raw["MARIADB_USER"],
        password=raw["MARIADB_PASSWORD"],
        database=raw["MARIADB_DATABASE"],
        container_name=optional_resolved["MARIADB_CONTAINER_NAME"],
        force_reimport=_parse_bool(
            optional_resolved["MARIADB_FORCE_REIMPORT"], key="MARIADB_FORCE_REIMPORT"
        ),
        auto_launch=_parse_bool(
            optional_resolved["MARIADB_AUTO_LAUNCH"], key="MARIADB_AUTO_LAUNCH"
        ),
    )
