"""
MAME hash XML generator

Takes the parsed :mod:`hbmame_xml.models` (RomBlock, GameEntry, Software,
DataArea, RomEntry) and emits a MAME-compatible softwarelist XML file.

Two output modes are supported:

* :func:`render_softwarelist` - the canonical monolithic
  ``<softwarelist>`` containing every romset.  This is the format used
  by MAME's own ``hash/`` directory.

* :func:`render_software_element` - just a single ``<software>...</software>``
  block, with no XML declaration, no DOCTYPE, and no
  ``<softwarelist>`` wrapper.  This is what each per-romset file in
  the ``<system>/<char>/<romset>.xml`` directory tree contains -
  the file is intended to be picked up by the monolithic
  ``<system>.xml`` when MAME reads the hash directory.
"""

from __future__ import annotations

import html
from typing import Dict, Iterable, List, Optional, Tuple

from .models import DataArea, GameEntry, RomBlock, RomEntry, Software
from .systems import System


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------


def _hex(value: int) -> str:
    """Format an integer as 0x... lowercase, no leading zeros (other than 0x)."""
    if value < 0:
        # Negative sizes don't make sense; clamp to 0 to keep the XML valid.
        value = 0
    return f"0x{value:x}"


def _attr(name: str, value: str) -> str:
    """Escape an XML attribute and return ``name="value"``."""
    return f'{name}="{html.escape(value, quote=True)}"'


def _sort_dataareas(areas: List[DataArea]) -> List[DataArea]:
    """Return dataareas in the canonical MAME order.

    For Neo Geo (and most systems), the canonical order is:
        maincpu, fixed, audiocpu, ymsnd:adpcma, ymsnd:adpcmb, sprites, mcu
    Other regions are appended at the end, sorted by name.
    """
    canon = {
        "maincpu": 0,
        "fixed": 1,
        "audiocpu": 2,
        "ymsnd:adpcma": 3,
        "ymsnd:adpcmb": 4,
        "sprites": 5,
        "mcu": 6,
    }
    def key(area: DataArea) -> Tuple[int, str]:
        return (canon.get(area.name, 100), area.name)
    return sorted(areas, key=key)


# ---------------------------------------------------------------------------
# Filename / path helpers for the per-romset directory output
# ---------------------------------------------------------------------------


# Anything outside [0-9A-Za-z] gets routed to this subdirectory to keep
# the tree filesystem-safe.
_NON_ALNUM_DIR = "_"


def first_char_dir(romset_name: str) -> str:
    """Return the subdirectory name to use for a per-romset file.

    The first character of *romset_name* is uppercased; if it is not
    alphanumeric, ``_`` is used instead so the tree remains
    filesystem-safe on every OS.
    """
    if not romset_name:
        return _NON_ALNUM_DIR
    ch = romset_name[0].upper()
    if "0" <= ch <= "9" or "A" <= ch <= "Z":
        return ch
    return _NON_ALNUM_DIR


def per_romset_path(romset_name: str) -> str:
    """Return the *relative* path for a romset's standalone XML file.

    Layout: ``<first_char_dir>/<romset_name>.xml``.  The result is
    relative to the system root directory; callers are expected to
    join it with the system directory themselves.
    """
    return f"{first_char_dir(romset_name)}/{romset_name}.xml"


# ---------------------------------------------------------------------------
# Element renderers
# ---------------------------------------------------------------------------


def _render_rom(rom: RomEntry) -> str:
    """Render a <rom .../> element."""
    attrs: List[str] = []
    if rom.loadflag:
        attrs.append(_attr("loadflag", rom.loadflag))
    if rom.status:
        attrs.append(_attr("status", rom.status))
    if rom.name is not None:
        attrs.append(_attr("name", rom.name))
    attrs.append(_attr("offset", _hex(rom.offset)))
    if rom.size or rom.loadflag == "continue":
        attrs.append(_attr("size", _hex(rom.size)))
    if rom.crc:
        attrs.append(_attr("crc", rom.crc))
    if rom.sha1:
        attrs.append(_attr("sha1", rom.sha1))
    return f"\t\t<rom {' '.join(attrs)} />"


def _render_dataarea(area: DataArea) -> List[str]:
    """Render a <dataarea>...</dataarea> block as a list of lines."""
    out: List[str] = []
    attrs = [_attr("name", area.name)]
    if area.width:
        attrs.append(_attr("width", str(area.width)))
    if area.endianness:
        attrs.append(_attr("endianness", area.endianness))
    attrs.append(_attr("size", _hex(area.size)))
    out.append(f"\t\t<dataarea {' '.join(attrs)}>")
    for rom in area.roms:
        out.append(_render_rom(rom))
    out.append("\t\t</dataarea>")
    return out


def _render_software(
    software: Software,
    system: System,
) -> List[str]:
    """Render a single <software>...</software> block (no outer wrapper)."""
    out: List[str] = []
    attrs = [_attr("name", software.name)]
    if software.cloneof:
        attrs.append(_attr("cloneof", software.cloneof))
    out.append(f"<software {' '.join(attrs)}>")

    # Header metadata.  <description> comes first to match upstream MAME.
    out.append(f"\t<description>{html.escape(software.description or '')}</description>")
    if software.year is not None:
        out.append(f"\t<year>{software.year}</year>")
    if software.publisher:
        out.append(f"\t<publisher>{html.escape(software.publisher)}</publisher>")

    # <info name=... value=.../>
    for k, v in software.info:
        out.append(f"\t<info name=\"{html.escape(k)}\" value=\"{html.escape(v)}\" />")
    for entry in system.default_info:
        if not any(k == entry.get("name") for k, _ in software.info):
            out.append(
                f'\t<info name="{html.escape(entry.get("name", ""))}" '
                f'value="{html.escape(entry.get("value", ""))}" />'
            )

    # <sharedfeat name=... value=.../>
    for entry in system.default_sharedfeat:
        out.append(
            f'\t<sharedfeat name="{html.escape(entry.get("name", ""))}" '
            f'value="{html.escape(entry.get("value", ""))}" />'
        )

    # <part>...</part>
    part_attrs = [_attr("name", system.part_name)]
    if system.interface:
        part_attrs.append(_attr("interface", system.interface))
    out.append(f"\t<part {' '.join(part_attrs)}>")
    for area in _sort_dataareas(software.dataareas):
        out.extend(_render_dataarea(area))
    out.append("\t</part>")

    out.append("</software>")
    return out


# ---------------------------------------------------------------------------
# Top-level renderers
# ---------------------------------------------------------------------------


def render_softwarelist(
    system: System,
    software_list: Iterable[Software],
) -> str:
    """Render a complete MAME softwarelist XML file (one per system) as a string."""
    lines: List[str] = []
    lines.append('<?xml version="1.0"?>')
    lines.append('<!DOCTYPE softwarelist SYSTEM "softwarelist.dtd">')
    lines.append(
        f'<softwarelist name="{html.escape(system.name)}" '
        f'description="{html.escape(system.description)}">'
    )
    # Software entries sorted by name for stable, diff-friendly output.
    for sw in sorted(software_list, key=lambda s: s.name):
        lines.extend(_render_software(sw, system))
    lines.append("</softwarelist>")
    return "\n".join(lines) + "\n"


def render_software_element(software: Software, system: System) -> str:
    """Render a single ``<software>`` element (no outer XML/DOCTYPE/wrapper).

    This is the format used for per-romset files in the
    ``<system>/<char>/<romset>.xml`` directory tree: just the
    ``<software>...</software>`` block and a trailing newline.  These
    files are intended to be picked up by the corresponding
    ``<system>.xml`` when MAME reads the hash directory, so they
    intentionally do not include the outer ``<softwarelist>`` wrapper
    or the XML/DOCTYPE preamble - those live in the monolithic file.
    """
    return "\n".join(_render_software(software, system)) + "\n"


# Backwards-compatible alias.  Older code (and the previous version of
# this module) called this :func:`render_software` and expected a
# ``<softwarelist>`` wrapper.  The new name is more accurate; the
# alias keeps the old call sites working.
def render_software(system: System, software: Software) -> str:
    """Deprecated: use :func:`render_software_element`.

    This now returns a bare ``<software>`` element (no wrapper), which
    is what the per-romset directory writer expects.  The *system*
    argument is retained for source-compatibility only and is unused.
    """
    return render_software_element(software, system)


# ---------------------------------------------------------------------------
# Build a Software from a RomBlock + GameEntry
# ---------------------------------------------------------------------------


def build_software(
    rom_block: RomBlock,
    game: Optional[GameEntry],
    system: System,
) -> Software:
    """Assemble a :class:`Software` from a parsed :class:`RomBlock` and
    optional :class:`GameEntry`.

    If a game entry is available its metadata (description, year,
    publisher, parent) is used; otherwise the description and year default
    to a placeholder.  Dataareas and ROMs come from the RomBlock.
    """
    if game is not None:
        description = game.description
        year = game.year
        publisher = game.manufacturer
        parent = game.parent
        cloneof: Optional[str] = None
        if parent not in system.root_parent_sentinels and parent != rom_block.name:
            cloneof = parent
    else:
        description = rom_block.name
        year = None
        publisher = ""
        cloneof = None

    info: List[Tuple[str, str]] = []
    if game is not None and game.driver and game.driver not in system.root_parent_sentinels:
        # Preserve the parent game name as an info entry, useful for
        # debugging generated output.
        info.append(("source", game.driver))

    # Pull the maincpu width/endianness (used by the MAME XML renderer
    # via DataArea attrs, but we also expose it on Software for callers).
    maincpu_area = next((d for d in rom_block.dataareas if d.name == "maincpu"), None)

    return Software(
        name=rom_block.name,
        description=description,
        year=year,
        publisher=publisher,
        info=info,
        cloneof=cloneof,
        dataareas=list(rom_block.dataareas),
        maincpu_width=maincpu_area.width if maincpu_area else None,
        maincpu_endianness=maincpu_area.endianness if maincpu_area else None,
    )
