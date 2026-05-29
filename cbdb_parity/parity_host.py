"""Python wrapper around the Cbdb.App.ParityHost .NET console.

The harness invokes the host via `subprocess` for each request:
JSON-serialise the request → stdin, JSON-parse the response from
stdout. Cold-start cost is ~500ms-1s per call; the NDJSON daemon
mode that amortises that comes in a later commit (Phase 5a-5 per
WORK_PLAN.md).

Per `WORK_PLAN.md §Phase 5a` the contract:
  - AVALONIA_REPO env var must be set so MSBuild's
    cross-repo ProjectReference resolves. We export it from
    `cfg.avalonia_repo` so callers don't need to pre-load .env.
  - UTF-8 byte pipes both directions; we never let the subprocess
    default to the Windows OEM code page (which would mojibake
    the CJK fields in CBDB rows).
  - Errors arrive on stderr as `{"error": ..., "stack": ...}`
    plus a non-zero exit code; we re-raise as `ParityHostError`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


class ParityHostError(RuntimeError):
    """Raised when the ParityHost subprocess returns a non-zero exit.

    The .NET side writes `{"error","stack"}` to stderr. We surface
    `.error` as `str(exc)` and `.stack` for callers that want the
    underlying CLR trace.
    """

    def __init__(self, message: str, stack: str | None = None) -> None:
        super().__init__(message)
        self.stack = stack


_REPO_ROOT = Path(__file__).resolve().parent.parent
_HOST_PROJECT = _REPO_ROOT / "parity_host" / "Cbdb.App.ParityHost" / "Cbdb.App.ParityHost.csproj"


def _dotnet_path() -> str:
    """Locate the dotnet CLI executable.

    On the user's Windows machine `dotnet` is at the well-known
    Program Files location even when not on PATH; on POSIX hosts
    we expect it on PATH. Resolved at call time so a missing
    install gives a clear error instead of a cryptic FileNotFoundError
    deep inside subprocess.
    """
    on_path = shutil.which("dotnet")
    if on_path:
        return on_path
    pf = Path(r"C:\Program Files\dotnet\dotnet.exe")
    if pf.is_file():
        return str(pf)
    raise FileNotFoundError(
        "dotnet CLI not found on PATH or at C:/Program Files/dotnet/. "
        "Install .NET 8 SDK (see parity_host/README.md)."
    )


def _to_jsonable(obj: Any) -> Any:
    """Coerce dataclass / sequence / dict inputs to JSON-safe types.

    Tuples become lists, dataclasses become dicts, everything else
    passes through. The ParityHost wire format is snake_case (set
    via JsonNamingPolicy.SnakeCaseLower on the .NET side), so our
    Python dataclass attribute names — already snake_case by
    convention — go on the wire verbatim.
    """
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    return obj


def invoke_parity_host(
    service: str,
    sqlite_path: Path,
    request: Any,
    *,
    avalonia_repo: Path,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """Invoke the ParityHost console for one request/response cycle.

    Parameters
    ----------
    service: which dispatch branch to run (e.g. "entry").
    sqlite_path: path to the cbdb.sqlite the upstream service reads.
    request: dataclass / dict / list / scalar. Serialised to JSON
        via `_to_jsonable`.
    avalonia_repo: path to the cbdb-desktop-app checkout. Exported
        as AVALONIA_REPO into the subprocess environment.
    timeout_seconds: cold-start is ~1s, queries return in <100ms
        on the canonical dataset, so 60s is comfortable for one-shot
        mode. Daemon mode (Phase 5a-5) drops this dramatically.

    Returns
    -------
    Parsed JSON response (dict, list, or scalar).

    Raises
    ------
    ParityHostError if the host exits non-zero.
    TimeoutExpired if the host hangs longer than timeout_seconds.
    FileNotFoundError if dotnet isn't installed.
    """
    payload = json.dumps(_to_jsonable(request), ensure_ascii=False).encode("utf-8")

    # Inherit the existing process env and overlay AVALONIA_REPO.
    # Always re-export because the harness may have loaded a new
    # .env between calls.
    env = dict(os.environ)
    env["AVALONIA_REPO"] = str(avalonia_repo)
    # Force the .NET console to a known UTF-8 console on Windows
    # too. Belt-and-braces with the C# side's
    # Console.OutputEncoding = UTF8Encoding(false).
    env.setdefault("DOTNET_CLI_UI_LANGUAGE", "en")

    cmd = [
        _dotnet_path(),
        "run",
        "--project", str(_HOST_PROJECT),
        "--no-build",       # caller is responsible for `dotnet build`
        "--",
        service, str(sqlite_path),
    ]
    proc = subprocess.run(
        cmd,
        input=payload,
        capture_output=True,
        env=env,
        timeout=timeout_seconds,
    )
    if proc.returncode != 0:
        # Try to parse the error payload; if stderr isn't valid JSON
        # (e.g. dotnet crashed before our handler ran), fall back to
        # the raw bytes.
        stderr_text = proc.stderr.decode("utf-8", errors="replace")
        try:
            err_payload = json.loads(stderr_text)
            raise ParityHostError(
                err_payload.get("error", stderr_text),
                stack=err_payload.get("stack"),
            )
        except (json.JSONDecodeError, AttributeError):
            raise ParityHostError(stderr_text)
    return json.loads(proc.stdout.decode("utf-8"))


def build_parity_host(avalonia_repo: Path) -> None:
    """Run `dotnet build` once so the wrapper can use --no-build.

    Side-effect: writes to parity_host/.../bin/Debug/net8.0/. Idempotent;
    a no-op when the host is up-to-date. We isolate this from
    `invoke_parity_host` because building is far slower than running
    and most call sites want to amortise the build across many
    invocations.
    """
    env = dict(os.environ)
    env["AVALONIA_REPO"] = str(avalonia_repo)
    subprocess.run(
        [_dotnet_path(), "build", str(_HOST_PROJECT), "--nologo"],
        check=True,
        capture_output=True,
        env=env,
    )


def invoke_person_accessor_via_host(
    service: str,
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_repo: Path,
    timeout_seconds: float = 60.0,
) -> list[dict[str, Any]]:
    """Shortcut for the 11 PersonBrowser per-person accessors.

    Each takes `{person_id}` on the wire and returns a JSON list
    of records. Wraps `invoke_parity_host` so each Tier 2 mirror
    module's `*_via_host` helper is one line.

    `service` is the dispatch keyword (e.g. "addresses",
    "altnames", "writings"). The corresponding mirror module
    documents the C# method this dispatches to (e.g.
    `SqlitePersonBrowserService.GetAddressesAsync`).
    """
    response = invoke_parity_host(
        service,
        sqlite_path,
        {"person_id": person_id},
        avalonia_repo=avalonia_repo,
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(response, list):
        raise TypeError(
            f"expected list response from '{service}' dispatch, "
            f"got {type(response).__name__}"
        )
    return response


__all__ = [
    "ParityHostError",
    "build_parity_host",
    "invoke_parity_host",
    "invoke_person_accessor_via_host",
]
