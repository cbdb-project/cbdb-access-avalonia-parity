# Cbdb.App.ParityHost

A small .NET 8 console that invokes the **real upstream
`Cbdb.App.Data` services** (from `cbdb-desktop-app`) on demand,
so the parity harness can compare against the canonical C# code
path instead of mirroring it in Python.

See `WORK_PLAN.md §Phase 5` for the full rationale and roadmap.

## Build / run

`AVALONIA_REPO` must be set before any `dotnet build` / `dotnet run`.
The Python harness does this automatically (via `python-dotenv`); for
manual builds, set it once in your shell:

**PowerShell**

```pwsh
$env:AVALONIA_REPO = 'C:/Users/<you>/Documents/GitHub/cbdb-desktop-app'
dotnet build .\Cbdb.App.ParityHost\Cbdb.App.ParityHost.csproj
dotnet run --project .\Cbdb.App.ParityHost
```

**bash**

```bash
export AVALONIA_REPO=/c/Users/<you>/Documents/GitHub/cbdb-desktop-app
dotnet build ./Cbdb.App.ParityHost/Cbdb.App.ParityHost.csproj
dotnet run --project ./Cbdb.App.ParityHost
```

If you forget to set `AVALONIA_REPO`, the build fails fast with a
clear error from `Directory.Build.props`.

## Scope (read first)

This project is part of `cbdb-access-avalonia-parity` — a detection
harness. We **do not commit code to `cbdb-desktop-app`**. The .csproj
files in this directory reference upstream via
`<ProjectReference Include="$(AvaloniaRepo)/…">` — a `git pull` in
the upstream tree picks up changes on the next `dotnet build` here.
See the top-level `AGENTS.md` and `WORK_PLAN.md §0` for the full
scope contract.

## Current state (scaffold)

The current `Program.cs` is a smoke binary: prints "scaffold OK",
echoes its args, exercises UTF-8 on a Chinese string, and touches
two upstream types (`EntryQueryRequest`, `SqliteEntryQueryService`)
to prove the cross-repo ProjectReference links. Real dispatch
(JSON request → service call → JSON response) lands in the next
commit.
