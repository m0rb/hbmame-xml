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

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set


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


def discover_machines(source_root: Path) -> Dict[str, System]:
    """Scan every HBMAME driver file and build a System per machine.

    Returns a dict mapping each machine driver name (e.g. ``cps2``,
    ``pgm_arm_type1_sim``, ``qsound``, ``pacman``, …) to a ``System``.
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

    result: Dict[str, System] = {}
    for machine in sorted(machines):
        short_names = machines[machine]
        root_sentinels: Set[str] = {machine, "0"}
        for sn, info in short_names.items():
            par = info["parent"]
            if par == info["short"] or par == machine:
                root_sentinels.add(sn)
        # Filter source files: only include files that have at least one GAME()
        # macro with this machine type
        filtered_files = []
        for fpath in sorted(driver_files[machine]):
            full_path = source_root / fpath
            if not full_path.is_file():
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
                filtered_files.append(fpath)
        result[machine] = System(
            name=machine,
            description=f"{machine.title()} cartridges",
            part_name="cart",
            source_files=filtered_files,
            root_parent_sentinels=list(root_sentinels | {machine, "0"}),
        )
    return result