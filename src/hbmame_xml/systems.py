"""
System-specific configurations and auto-discovery of HBMAME machines.

A "system" here means a target MAME softwarelist (e.g. ``neogeo``). Each
System describes which HBMAME source files to scan, how to map GAME()
driver names to cloneof relationships, and the <part> / <interface>
attributes for the resulting <software> elements.

The special system name ``"all"`` runs auto-discovery: every driver file
in ``src/hbmame/drivers/*.cpp`` is scanned, and one softwarelist is
generated per unique driver name (the ``machine`` field of ``GAME()``).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

try:  # Python 3.11+
    import tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback for <3.11
    tomllib = None  # type: ignore


@dataclass
class System:
    """Configuration for one target MAME softwarelist."""

    name: str
    description: str = ""
    part_name: str = "cart"
    interface: Optional[str] = None
    source_files: List[str] = field(default_factory=list)
    root_parent_sentinels: List[str] = field(default_factory=list)
    extra_bios_files: List[str] = field(default_factory=list)
    default_info: List[Dict[str, str]] = field(default_factory=list)
    default_sharedfeat: List[Dict[str, str]] = field(default_factory=list)
    comment_info_patterns: List = field(default_factory=list)
    treat_as_parents: List[str] = field(default_factory=list)
    fix_maincpu: bool = False
    # Set of GAME() machine-driver names this softwarelist claims.  When
    # non-empty it is authoritative; otherwise membership falls back to the
    # canonical grouping config (see ``config/driver_groups.toml``).  This is
    # what keeps each romset in exactly one softwarelist (e.g. it stops
    # neogeo sets from leaking into playch10).
    claimed_drivers: Set[str] = field(default_factory=set)

    def claims(self, driver: str) -> bool:
        """True when *driver* (a GAME() machine field) belongs to this list.

        Membership is governed by the canonical grouping so that variant
        drivers (``neogeo_kog``, ``pgm_arm_type1``, ...) and any driver name
        that only appears in upstream MAME files still map to the right
        softwarelist.  ``claimed_drivers`` is an extra explicit allow-list.
        This is what keeps each romset in exactly one softwarelist.
        """
        if canonical_system_name(driver) == self.name:
            return True
        return driver in self.claimed_drivers


# ---------------------------------------------------------------------------
# Driver grouping config (config/driver_groups.toml)
# ---------------------------------------------------------------------------

# Built-in fallback used when the TOML config is missing or tomllib is
# unavailable.  Keep in sync with config/driver_groups.toml.
_DEFAULT_DRIVER_GROUPS: Dict[str, List[str]] = {
    "neogeo": ["neogeo"],
    "pgm": ["pgm"],
    "cps1": ["cps1"],
    "system16b": ["system16b"],
    "playch10": ["playch10"],
    "f3": ["f3"],
    "cv1k": ["cv1k"],
    "mcr": ["mcr"],
    "williams": ["williams"],
    "tunit": ["tunit"],
    "wunit": ["wunit"],
    "yunit": ["yunit"],
    "mhavocpe": ["mhavocpe"],
}


def _default_config_path() -> Path:
    """Locate ``config/driver_groups.toml`` relative to the repo root.

    Honours ``HBMAME_XML_CONFIG`` for an explicit override.  ``systems.py``
    lives at ``<root>/src/hbmame_xml/systems.py`` so the repo root is two
    parents up from this file's directory.
    """
    env = os.environ.get("HBMAME_XML_CONFIG")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "config" / "driver_groups.toml"


_DRIVER_GROUPS_CACHE: Optional[Dict[str, List[str]]] = None


def load_driver_groups(path: Optional[Path] = None) -> Dict[str, List[str]]:
    """Load the canonical -> [prefixes] grouping map.

    Falls back to :data:`_DEFAULT_DRIVER_GROUPS` if the file is absent or
    cannot be parsed.  Result is cached for the default path.
    """
    global _DRIVER_GROUPS_CACHE
    use_cache = path is None
    if use_cache and _DRIVER_GROUPS_CACHE is not None:
        return _DRIVER_GROUPS_CACHE

    cfg_path = path or _default_config_path()
    groups: Dict[str, List[str]] = dict(_DEFAULT_DRIVER_GROUPS)
    if tomllib is not None and cfg_path.is_file():
        try:
            with cfg_path.open("rb") as fh:
                data = tomllib.load(fh)
            raw = data.get("groups", {})
            if isinstance(raw, dict):
                groups = {
                    str(canon): [str(p) for p in (prefixes or [])]
                    for canon, prefixes in raw.items()
                }
        except (OSError, ValueError):
            groups = dict(_DEFAULT_DRIVER_GROUPS)

    if use_cache:
        _DRIVER_GROUPS_CACHE = groups
    return groups


def canonical_system_name(
    driver: str, groups: Optional[Dict[str, List[str]]] = None
) -> str:
    """Map a GAME() machine-driver name to its canonical softwarelist name.

    A driver ``d`` folds into canonical ``C`` when one of C's prefixes ``p``
    satisfies ``d == p`` or ``d.startswith(p + "_")``.  The longest matching
    prefix wins, so sub-families can be carved out.  Drivers matching no
    prefix are returned unchanged (they remain their own softwarelist).
    """
    if groups is None:
        groups = load_driver_groups()
    best_canon = driver
    best_len = -1
    for canon, prefixes in groups.items():
        for p in prefixes:
            if (driver == p or driver.startswith(p + "_")) and len(p) > best_len:
                best_canon = canon
                best_len = len(p)
    return best_canon


# ---------------------------------------------------------------------------
# Built-in systems
# ---------------------------------------------------------------------------

NEOGEO = System(
    name="neogeo",
    description="SNK Neo-Geo cartridges",
    part_name="cart",
    interface="neo_cart",
    source_files=[
        "src/mame/drivers/neogeo.cpp",
        "src/mame/drivers/neogeo_noslot.cpp",
        "src/mame/drivers/neogeo1.cpp",
        "src/hbmame/drivers/neogeo.cpp",
        "src/hbmame/drivers/neogeo1.cpp",
        "src/hbmame/drivers/neogeo_noslot.cpp",
        "src/hbmame/drivers/neogeohb.cpp",
    ],
    root_parent_sentinels=["neogeo", "neogeo_noslot", "neogeo_state"],
    default_sharedfeat=[{"name": "compatibility", "value": "MVS,AES"}],
    fix_maincpu=True,
)

SYSTEMS: Dict[str, System] = {"neogeo": NEOGEO}


def get_system(name: str) -> System:
    if name not in SYSTEMS:
        raise KeyError(f"Unknown system {name!r}. Known: {', '.join(SYSTEMS)}")
    return SYSTEMS[name]


def list_systems() -> List[str]:
    return list(SYSTEMS)


# ---------------------------------------------------------------------------
# Auto-discover all machines in HBMAME driver files
# ---------------------------------------------------------------------------


def _find_matching_paren(text: str, open_pos: int) -> int:
    if open_pos >= len(text) or text[open_pos] != "(":
        raise ValueError(f"Expected '(' at {open_pos}")
    depth_paren = 0
    depth_bracket = 0
    depth_brace = 0
    in_string = False
    i = open_pos
    n = len(text)
    while i < n:
        c = text[i]
        if in_string:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == '"':
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
            i += 1
            continue
        if c == "(":
            depth_paren += 1
        elif c == ")":
            depth_paren -= 1
            if depth_paren == 0 and depth_bracket == 0 and depth_brace == 0:
                return i
        elif c == "[":
            depth_bracket += 1
        elif c == "]":
            depth_bracket -= 1
        elif c == "{":
            depth_brace += 1
        elif c == "}":
            depth_brace -= 1
        i += 1
    raise ValueError(f"Unmatched '(' at {open_pos}")


def _extract_string_literal(arg: str) -> str:
    s = arg.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return bytes(s[1:-1], "utf-8").decode("unicode_escape")
    return s


def _split_top_level(s: str) -> List[str]:
    args: List[str] = []
    buf: List[str] = []
    depth_paren = 0
    depth_bracket = 0
    depth_brace = 0
    in_string = False
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if in_string:
            buf.append(c)
            if c == "\\" and i + 1 < n:
                buf.append(s[i + 1])
                i += 2
                continue
            if c == '"':
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
            buf.append(c)
            i += 1
            continue
        if c == "(":
            depth_paren += 1
        elif c == ")":
            depth_paren -= 1
        elif c == "[":
            depth_bracket += 1
        elif c == "]":
            depth_bracket -= 1
        elif c == "{":
            depth_brace += 1
        elif c == "}":
            depth_brace -= 1
        if (
            c == ","
            and depth_paren == 0
            and depth_bracket == 0
            and depth_brace == 0
        ):
            args.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        args.append(tail)
    return args


def _parse_game_args(body: str) -> dict:
    args = _split_top_level(body)
    if len(args) < 10:
        raise ValueError(f"GAME expects >=10 args, got {len(args)}")
    return {
        "short": args[1],
        "parent": args[2],
        "machine": args[3],
        "manufacturer": _extract_string_literal(args[-2]) if len(args) >= 10 else "",
        "description": _extract_string_literal(args[-1]) if len(args) >= 10 else "",
    }


def _merge_preserving_order(*seqs: Iterable[str]) -> List[str]:
    """Concatenate sequences, dropping duplicates, keeping first-seen order."""
    seen: Set[str] = set()
    out: List[str] = []
    for seq in seqs:
        for item in seq:
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


def discover_machines(source_root: Path) -> Dict[str, System]:
    """Scan every HBMAME driver file and build a System per *canonical* group.

    Each GAME() macro names a machine-driver function (e.g. ``neogeo_kog``,
    ``pgm_arm_type1``).  Those driver names are folded into canonical
    softwarelist names via :func:`canonical_system_name` (configured in
    ``config/driver_groups.toml``), so all variants of one system collapse
    into a single ``System``.  Where a canonical name also has a curated
    built-in (e.g. ``neogeo``), the curated rendering attributes are kept and
    its source files / sentinels are merged in.

    Returns a dict mapping each canonical name to its merged ``System``.
    """
    hbmame_dir = source_root / "src/hbmame/drivers"
    if not hbmame_dir.is_dir():
        raise FileNotFoundError(f"HBMAME drivers dir not found: {hbmame_dir}")

    _GAME_PAT = re.compile(r"\bGAME\s*\(")
    machines: Dict[str, Dict[str, dict]] = {}
    driver_files: Dict[str, Set[str]] = {}

    for fpath in sorted(hbmame_dir.glob("*.cpp")):
        rel = f"src/hbmame/drivers/{fpath.name}"
        text = fpath.read_text(encoding="utf-8", errors="replace")
        for m in _GAME_PAT.finditer(text):
            open_pos = m.end() - 1
            try:
                close_pos = _find_matching_paren(text, open_pos)
            except ValueError:
                continue
            args_body = text[open_pos + 1: close_pos]
            try:
                info = _parse_game_args(args_body)
            except ValueError:
                continue
            machine = info["machine"]
            machines.setdefault(machine, {})[info["short"]] = info
            driver_files.setdefault(machine, set()).add(rel)

    groups = load_driver_groups()

    # Accumulate per canonical softwarelist, folding variant drivers together.
    canon_drivers: Dict[str, Set[str]] = {}
    canon_sentinels: Dict[str, Set[str]] = {}
    canon_files: Dict[str, List[str]] = {}

    for machine in sorted(machines):
        canon = canonical_system_name(machine, groups)
        short_names = machines[machine]
        drivers = canon_drivers.setdefault(canon, set())
        drivers.add(machine)
        sentinels = canon_sentinels.setdefault(canon, {canon, "0"})
        sentinels.add(machine)
        for sn, info in short_names.items():
            par = info["parent"]
            if par == info["short"] or par == machine:
                sentinels.add(sn)
        # Filter source files: only include files that have at least one GAME()
        # macro with this machine type
        files = canon_files.setdefault(canon, [])
        for fpath in sorted(driver_files[machine]):
            full_path = source_root / fpath
            if not full_path.is_file() or fpath in files:
                continue
            text = full_path.read_text(encoding="utf-8", errors="replace")
            has_machine_game = False
            for m in _GAME_PAT.finditer(text):
                open_pos = m.end() - 1
                try:
                    close_pos = _find_matching_paren(text, open_pos)
                except ValueError:
                    continue
                args_body = text[open_pos + 1: close_pos]
                try:
                    info = _parse_game_args(args_body)
                except ValueError:
                    continue
                if info["machine"] == machine:
                    has_machine_game = True
                    break
            if has_machine_game:
                files.append(fpath)

    result: Dict[str, System] = {}
    for canon in sorted(canon_drivers):
        drivers = canon_drivers[canon]
        sentinels = canon_sentinels[canon] | drivers | {canon, "0"}
        curated = SYSTEMS.get(canon)
        if curated is not None:
            # Keep the curated rendering config; merge in discovered drivers,
            # source files (curated/upstream first for precedence) and sentinels.
            result[canon] = System(
                name=curated.name,
                description=curated.description,
                part_name=curated.part_name,
                interface=curated.interface,
                source_files=_merge_preserving_order(
                    curated.source_files, sorted(canon_files[canon])
                ),
                root_parent_sentinels=sorted(
                    set(curated.root_parent_sentinels) | sentinels
                ),
                extra_bios_files=list(curated.extra_bios_files),
                default_info=list(curated.default_info),
                default_sharedfeat=list(curated.default_sharedfeat),
                comment_info_patterns=list(curated.comment_info_patterns),
                treat_as_parents=list(curated.treat_as_parents),
                fix_maincpu=curated.fix_maincpu,
                claimed_drivers=set(drivers),
            )
        else:
            result[canon] = System(
                name=canon,
                description=f"{canon.title()} cartridges",
                part_name="cart",
                source_files=sorted(canon_files[canon]),
                root_parent_sentinels=sorted(sentinels),
                claimed_drivers=set(drivers),
            )
    return result