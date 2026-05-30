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

import collections
import json
import os
import shutil
import subprocess
import threading
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
        except (json.JSONDecodeError, AttributeError) as exc:
            # `from exc` preserves the JSON-decode failure context so
            # callers debugging "what did the host actually emit" see
            # both the raw stderr_text and why parsing it failed.
            raise ParityHostError(stderr_text) from exc
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


class ParityHostDaemon:
    """Phase 7h — long-lived ParityHost subprocess that amortises
    the ~1s `dotnet run` cold-start over many calls. Use as a
    context manager:

        with ParityHostDaemon(avalonia_repo=cfg.avalonia_repo) as host:
            rows = host.invoke("addresses", sqlite_path, {"person_id": 1762})
            ...

    The wire format (see `parity_host/Cbdb.App.ParityHost/Program.cs`
    `RunDaemonAsync`):

      - request frames: one JSON line in
        `{"service": str, "sqlite_path": str, "request": <any>}`
      - response frames: one JSON line per request, either
        `{"ok": <response document>}` or `{"error": str, "stack": str}`

    Failure semantics: a single frame's failure produces an error
    response and `invoke` raises `ParityHostError`; the daemon keeps
    serving. If the daemon process exits unexpectedly mid-frame
    (`readline` returns EOF with no response), `invoke` raises
    `ParityHostError("daemon died after N frames")` carrying stderr.
    Re-create the context manager to start a fresh subprocess.
    """

    def __init__(
        self,
        *,
        avalonia_repo: Path,
        startup_timeout_seconds: float = 30.0,
        per_call_timeout_seconds: float = 60.0,
        shutdown_timeout_seconds: float = 5.0,
    ) -> None:
        self._avalonia_repo = avalonia_repo
        self._startup_timeout = startup_timeout_seconds
        self._per_call_timeout = per_call_timeout_seconds
        self._shutdown_timeout = shutdown_timeout_seconds
        self._proc: subprocess.Popen[bytes] | None = None
        self._frames_served = 0
        # Codex 7h round flagged a deadlock: nothing was draining
        # stderr during normal operation, so a child that writes
        # enough stderr fills its 64KB pipe buffer and blocks
        # before it can flush the NDJSON response. Always drain
        # stderr in a background thread that runs from __enter__
        # to __exit__; it stores everything in a bounded deque
        # for postmortem.
        self._stderr_lines: collections.deque[bytes] = collections.deque(
            maxlen=1024
        )
        self._stderr_thread: threading.Thread | None = None
        self._stderr_done = threading.Event()

    def __enter__(self) -> ParityHostDaemon:
        env = dict(os.environ)
        env["AVALONIA_REPO"] = str(self._avalonia_repo)
        env.setdefault("DOTNET_CLI_UI_LANGUAGE", "en")
        cmd = [
            _dotnet_path(),
            "run",
            "--project", str(_HOST_PROJECT),
            "--no-build",
            "--",
            "--daemon",
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            bufsize=0,
        )
        # Start the stderr drain thread BEFORE returning so we
        # never have a window where the daemon has spawned but
        # nobody's reading stderr.
        self._stderr_done.clear()
        self._stderr_thread = threading.Thread(
            target=self._stderr_drain_loop,
            name="ParityHostDaemon-stderr",
            daemon=True,
        )
        self._stderr_thread.start()
        return self

    def __exit__(self, exc_type, exc_value, tb) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            # Close stdin → daemon's ReadLineAsync returns null →
            # graceful exit 0.
            if proc.stdin is not None:
                try:
                    proc.stdin.close()
                except OSError:
                    pass
            try:
                proc.wait(timeout=self._shutdown_timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            # Signal the stderr drain thread to finish and let it
            # flush whatever final bytes the child wrote. Without
            # this join, codex 7h round flagged we'd lose the only
            # useful crash context.
            self._stderr_done.set()
            if self._stderr_thread is not None:
                self._stderr_thread.join(timeout=self._shutdown_timeout)
        finally:
            self._proc = None
            self._stderr_thread = None

    def _stderr_drain_loop(self) -> None:
        """Background thread body. Reads stderr lines until EOF or
        until the context manager signals shutdown. Bounded to
        1024 lines (~64 KB worst case) so a runaway child can't
        OOM us.
        """
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            for raw in iter(proc.stderr.readline, b""):
                self._stderr_lines.append(raw)
                # The shutdown signal lets __exit__ stop us
                # promptly even if the child is still writing.
                if self._stderr_done.is_set() and not raw:
                    break
        except (OSError, ValueError):
            # Pipe closed unexpectedly — nothing to do; the
            # captured lines we already have are still readable
            # via _captured_stderr().
            pass

    def _captured_stderr(self) -> str:
        return b"".join(self._stderr_lines).decode("utf-8", errors="replace")

    def invoke(
        self,
        service: str,
        sqlite_path: Path,
        request: Any,
    ) -> Any:
        """Send one request frame, return the parsed response.

        Raises `ParityHostError` on per-frame failure, daemon
        death, or per-call timeout. The context manager remains
        usable after a per-frame error (daemon keeps running);
        after daemon death or a timeout, the manager should be
        closed and re-opened.
        """
        proc = self._proc
        if proc is None or proc.stdin is None or proc.stdout is None:
            raise RuntimeError(
                "ParityHostDaemon used outside its `with` block, or "
                "the subprocess failed to start."
            )

        frame = {
            "service": service,
            "sqlite_path": str(sqlite_path),
            "request": _to_jsonable(request),
        }
        line = json.dumps(frame, ensure_ascii=False) + "\n"
        try:
            proc.stdin.write(line.encode("utf-8"))
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            stderr_text = self._captured_stderr()
            raise ParityHostError(
                f"daemon died after {self._frames_served} frames "
                f"(pipe broken on write): {stderr_text}",
                stack=stderr_text,
            ) from exc

        # Codex 7h round: enforce per-call timeout via a helper
        # thread; subprocess pipes on Windows don't support
        # `select()`. The helper reads one line; the main thread
        # joins it with the timeout, raising ParityHostError on
        # expiry instead of hanging pytest forever.
        result: dict[str, Any] = {"line": b"", "err": None}
        def _read() -> None:
            try:
                result["line"] = proc.stdout.readline()
            except Exception as exc:
                result["err"] = exc
        reader = threading.Thread(
            target=_read,
            name="ParityHostDaemon-readline",
            daemon=True,
        )
        reader.start()
        reader.join(timeout=self._per_call_timeout)
        if reader.is_alive():
            stderr_text = self._captured_stderr()
            raise ParityHostError(
                f"daemon per-call timeout after "
                f"{self._per_call_timeout}s "
                f"(service={service!r}, frames_served="
                f"{self._frames_served}). stderr: {stderr_text}",
                stack=stderr_text,
            )
        if result["err"] is not None:
            stderr_text = self._captured_stderr()
            raise ParityHostError(
                f"daemon stdout read raised "
                f"{type(result['err']).__name__}: "
                f"{result['err']}. stderr: {stderr_text}",
                stack=stderr_text,
            ) from result["err"]

        raw = result["line"]
        if not raw:
            stderr_text = self._captured_stderr()
            raise ParityHostError(
                f"daemon died after {self._frames_served} frames "
                f"(EOF on stdout): {stderr_text}",
                stack=stderr_text,
            )

        self._frames_served += 1
        try:
            response = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ParityHostError(
                f"daemon emitted a non-JSON line after "
                f"{self._frames_served} frames: {raw!r}"
            ) from exc

        if "error" in response:
            raise ParityHostError(
                response.get("error", "<unknown daemon error>"),
                stack=response.get("stack"),
            )
        if "ok" not in response:
            raise ParityHostError(
                f"daemon response missing both 'ok' and 'error' keys: "
                f"{response!r}"
            )
        return response["ok"]


__all__ = [
    "ParityHostDaemon",
    "ParityHostError",
    "build_parity_host",
    "invoke_parity_host",
    "invoke_person_accessor_via_host",
]
