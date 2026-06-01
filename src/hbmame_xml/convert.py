"""
Top-level conversion logic and CLI entry point.

This module ties together the parser, system configurations, and the XML
generator.  As a library you can call :func:`convert_system` to get the
generated XML string for a built-in (or custom) system.  As a script
``python -m hbmame_xml.convert`` provides a CLI for local development.

Output layout (per system)::

    <output-dir>/
    +-- machine-xml/
    |   +-- <system>.xml                # monolithic softwarelist (all romsets)
    `-- romset-xml/
        `-- <system>/
            +-- A/<romset>.xml          # one bare <software> per file
            +-- B/<romset>.xml          # (no XML preamble, no DOCTYPE)
            +-- ...
            `-- Z/<romset>.xml

When ``--system all`` is used, the discover module scans all driver files
in ``src/hbmame/drivers/*.cpp`` and generates outputs for every machine.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from .generator import (
    build_software,
    per_romset_path,
    render_software_element,
    render_softwarelist,
)
from .models import Software
from .parser import parse_game_macros, parse_rom_blocks, strip_cpp_comments, build_macro_table
from .systems import System, get_system, list_systems, discover_machines

MACHINE_XML_DIR = "machine-xml"
ROMSET_XML_DIR = "romset-xml"


def _read_and_parse(
    path: Path,
    global_macros: dict[str, int],
    allowed_rom_names: List[str],
) -> Tuple[List, List]:
    if not path.is_file():
        return [], []
    text = path.read_text(encoding="utf-8", errors="replace")
    clean = strip_cpp_comments(text)
    macros = build_macro_table(text)
    macros.update(global_macros)
    from .parser import _parse_rom_block_body, _extract_rom_blocks, parse_rom_block
    blocks = []
    for b in _extract_rom_blocks(clean):
        try:
            if b.name not in allowed_rom_names:
                continue
            blk = parse_rom_block(b.text, b.name, macros)
            blocks.append(blk)
        except Exception:
            continue
    games = parse_game_macros(clean)
    return blocks, games


def _apply_system_fixes(rom_block, system: System):
    if system.fix_maincpu:
        for area in rom_block.dataareas:
            if area.name == "maincpu":
                if area.width is None:
                    area.width = 16
                if area.endianness is None:
                    area.endianness = "big"
                break
    return rom_block


def _has_roms(rom_block):
    for area in rom_block.dataareas:
        for rom in area.roms:
            if not rom.is_continue():
                return True
    return False


def convert_system(
    system: System,
    source_root: Path,
    *,
    include_empty: bool = False,
) -> Tuple[str, List[Software]]:
    all_roms: dict[str, Software] = {}
    all_games: dict = {}
    global_macros: dict[str, int] = {}

    # Step 1: collect all #define macros from all source files for this system
    for relpath in system.source_files:
        path = source_root / relpath
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        m = build_macro_table(text)
        global_macros.update(m)

    # Step 2: collect GAME() macros from all source files, but only those
    # whose machine field matches this system.  This prevents shared files
    # (like mnw.cpp) from leaking ROM_START blocks from other systems.
    allowed_rom_names = []
    for relpath in system.source_files:
        path = source_root / relpath
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        clean = strip_cpp_comments(text)
        games = parse_game_macros(clean)
        for g in games:
            all_games.setdefault(g.name, g)
            if g.driver == system.name:
                allowed_rom_names.append(g.name)

    # Step 3: parse each file using the global macro table, only keeping
    # ROM_START blocks with names that match our allowed_rom_names
    for relpath in system.source_files:
        path = source_root / relpath
        roms, games = _read_and_parse(path, global_macros, allowed_rom_names)
        for r in roms:
            if r.name in all_roms:
                continue
            all_roms[r.name] = _apply_system_fixes(r, system)

    software_list: List[Software] = []
    for name, rom_block in all_roms.items():
        if not include_empty and not _has_roms(rom_block):
            continue
        game = all_games.get(name)
        software_list.append(build_software(rom_block, game, system))
    return render_softwarelist(system, software_list), software_list


def write_outputs(
    system: System,
    output_dir: Path,
    software_list: List[Software],
    *,
    skip_monolithic: bool = False,
    skip_per_romset: bool = False,
) -> Tuple[Optional[Path], List[Path]]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    monopath: Optional[Path] = None
    per_paths: List[Path] = []

    if not skip_monolithic:
        machine_dir = output_dir / MACHINE_XML_DIR
        machine_dir.mkdir(parents=True, exist_ok=True)
        monopath = machine_dir / f"{system.name}.xml"
        monopath.write_text(
            render_softwarelist(system, software_list), encoding="utf-8"
        )

    if not skip_per_romset:
        system_dir = output_dir / ROMSET_XML_DIR / system.name
        for sw in software_list:
            rel = per_romset_path(sw.name)
            target = system_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                render_software_element(sw, system), encoding="utf-8"
            )
            per_paths.append(target)
    return monopath, per_paths


def _make_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hbmame-xml",
        description="Convert HBMAME source into MAME hash XML files.",
    )
    p.add_argument(
        "--source", "-s",
        type=Path,
        default=Path(os.environ.get(
            "HBMAME_SRC", "hbmame"
        )),
    )
    p.add_argument(
        "--system", "-S",
        default="neogeo",
        help="Target system / softwarelist, or 'all' for full HBMAME scan.",
    )
    p.add_argument(
        "--output-dir", "-o",
        type=Path,
        default=Path("."),
    )
    p.add_argument("--no-monolithic", action="store_true")
    p.add_argument("--no-per-romset", action="store_true")
    p.add_argument("--list-systems", action="store_true")
    p.add_argument("--include-empty", action="store_true")
    p.add_argument("--verbose", "-v", action="store_true")
    return p


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _make_argparser().parse_args(argv)

    if args.list_systems:
        for name in list_systems():
            s = get_system(name)
            print(f"{name}: {s.description or ''}")
        return 0

    if not args.source.is_dir():
        print(f"error: HBMAME source dir {args.source} not found.", file=sys.stderr)
        return 2

    # Determine which systems to convert
    if args.system == "all":
        machines = discover_machines(args.source)
        systems_to_convert = [machines[k] for k in sorted(machines)]
        if args.verbose:
            print(
                f"auto-discovered {len(systems_to_convert)} machines",
                file=sys.stderr,
            )
    else:
        # Try built-in systems first, then auto-discovered ones.
        try:
            systems_to_convert = [get_system(args.system)]
        except KeyError:
            machines = discover_machines(args.source)
            if args.system in machines:
                systems_to_convert = [machines[args.system]]
            else:
                print(
                    f"error: unknown system {args.system!r}",
                    file=sys.stderr,
                )
                return 2

    total_mono = 0
    total_rom = 0
    for system in systems_to_convert:
        if args.verbose:
            print(
                f"\n--- {system.name} ({len(system.source_files)} src files) ---",
                file=sys.stderr,
            )
            for rel in system.source_files:
                full = args.source / rel
                print(
                    f"  {'OK' if full.is_file() else 'MISSING':>7} {rel}",
                    file=sys.stderr,
                )

        _, software_list = convert_system(
            system,
            args.source,
            include_empty=args.include_empty,
        )
        if not software_list:
            if args.verbose:
                print(f"  -> no romsets found, skipping", file=sys.stderr)
            continue

        monopath, per_paths = write_outputs(
            system,
            args.output_dir,
            software_list,
            skip_monolithic=args.no_monolithic,
            skip_per_romset=args.no_per_romset,
        )
        total_mono += 1 if monopath else 0
        total_rom += len(per_paths)

        if args.verbose:
            print(f"  -> {len(software_list):>4} romsets", file=sys.stderr)
            if monopath:
                print(
                    f"     machine-xml/{system.name}.xml "
                    f"({monopath.stat().st_size:,} bytes)",
                    file=sys.stderr,
                )
            if per_paths:
                print(
                    f"     romset-xml/{system.name}/  ({len(per_paths)} files)",
                    file=sys.stderr,
                )

    if args.verbose:
        print(
            f"\nTotal: {total_mono} machine XMLs, {total_rom} romset files",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())