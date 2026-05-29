"""Phase 5e — Python wrappers for the three lookup / group surfaces
that became tractable once the host could dispatch them directly:

  - DynastyLookup (`dynasty_lookup`) → DynastyOption[]
  - PlaceLookup   (`place_lookup`)  → PlaceOption[]
  - GroupPeople   (`group_people`)  → GroupPeopleQueryResult

These are read-only options builders the Avalonia UI uses to
populate dropdowns and assemble multi-person composite reports.
There is no Access-side analogue for them today, so Phase 5e
ships smoke tests (host returns a list/dict of the documented
shape) rather than pair tests; a future commit can add Access
bridges if a parity question is raised about them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cbdb_parity._person_accessor_host import resolve_avalonia_repo
from cbdb_parity.parity_host import invoke_parity_host


def dynasty_lookup(
    sqlite_path: Path,
    *,
    avalonia_repo: Path | None = None,
    avalonia_data_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Run `SqliteDynastyLookupService.GetDynastiesAsync` via the host.
    Returns a list of `DynastyOption` (dynasty_id, name, name_chn,
    start_year, end_year).
    """
    repo = resolve_avalonia_repo(
        avalonia_repo=avalonia_repo,
        avalonia_data_dir=avalonia_data_dir,
    )
    response = invoke_parity_host(
        "dynasty_lookup", sqlite_path, {}, avalonia_repo=repo,
    )
    if not isinstance(response, list):
        raise TypeError(
            f"dynasty_lookup returned {type(response).__name__}; expected list."
        )
    return response


def place_lookup(
    sqlite_path: Path,
    *,
    avalonia_repo: Path | None = None,
    avalonia_data_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Run `SqlitePlaceLookupService.GetPlacesAsync` via the host."""
    repo = resolve_avalonia_repo(
        avalonia_repo=avalonia_repo,
        avalonia_data_dir=avalonia_data_dir,
    )
    response = invoke_parity_host(
        "place_lookup", sqlite_path, {}, avalonia_repo=repo,
    )
    if not isinstance(response, list):
        raise TypeError(
            f"place_lookup returned {type(response).__name__}; expected list."
        )
    return response


ADDRESS_MODE_ALL = 1
ADDRESS_MODE_INDEX = 2


@dataclass(frozen=True, slots=True)
class GroupPeopleQueryOptions:
    """Wire-compatible mirror of `Cbdb.App.Core.GroupPeopleQueryOptions`.

    `address_mode` carries the integer value of upstream
    `GroupPeopleAddressMode` (1 = AllAddresses, 2 = IndexAddresses).
    Use the module constants `ADDRESS_MODE_ALL` / `ADDRESS_MODE_INDEX`
    for readability.
    """

    include_status: bool = False
    include_office: bool = False
    include_entry: bool = False
    include_texts: bool = False
    include_addresses: bool = False
    address_mode: int = ADDRESS_MODE_ALL


def group_people(
    sqlite_path: Path,
    person_ids: list[int],
    options: GroupPeopleQueryOptions,
    *,
    avalonia_repo: Path | None = None,
    avalonia_data_dir: Path | None = None,
) -> dict[str, Any]:
    """Run `SqliteGroupPeopleService.QueryAsync` via the host."""
    repo = resolve_avalonia_repo(
        avalonia_repo=avalonia_repo,
        avalonia_data_dir=avalonia_data_dir,
    )
    response = invoke_parity_host(
        "group_people", sqlite_path,
        {"person_ids": list(person_ids), "options": options},
        avalonia_repo=repo,
    )
    if not isinstance(response, dict):
        raise TypeError(
            f"group_people returned {type(response).__name__}; expected dict."
        )
    return response


__all__ = [
    "ADDRESS_MODE_ALL",
    "ADDRESS_MODE_INDEX",
    "GroupPeopleQueryOptions",
    "dynasty_lookup",
    "group_people",
    "place_lookup",
]
