"""
Data models for parsed HBMAME source code.

These dataclasses represent the structural information extracted from a C++
driver source file. They are intentionally simple and JSON-serialisable so that
the same intermediate representation can later be re-rendered to any output
format (MAME hash XML, plain text, etc).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Core data classes
# ---------------------------------------------------------------------------


@dataclass
class RomEntry:
    """A single ROM_LOAD / ROM_CONTINUE / ROMX_LOAD entry.

    ``loadflag`` is the MAME XML attribute, e.g. "load16_word_swap", "load16_byte",
    "load32_byte", "load32_word_swap", or "continue". ``None`` means a plain 8-bit
    load (no loadflag attribute should be emitted).
    """

    name: Optional[str] = None
    offset: int = 0
    size: int = 0
    crc: Optional[str] = None
    sha1: Optional[str] = None
    loadflag: Optional[str] = None
    status: Optional[str] = None  # e.g. "baddump"

    def is_continue(self) -> bool:
        return self.loadflag == "continue"


@dataclass
class DataArea:
    """A ROM_REGION: a contiguous memory region containing one or more ROMs.

    ``width`` and ``endianness`` are optional XML attributes derived from the
    ROMREGION_* flags (e.g. ``width=16``, ``endianness="big"`` for the 68K
    maincpu region on Neo Geo).
    """

    name: str
    size: int
    width: Optional[int] = None
    endianness: Optional[str] = None
    roms: List[RomEntry] = field(default_factory=list)

    def total_rom_size(self) -> int:
        """Sum of all ROM_LOAD sizes in this area (CONTINUEs don't add new bytes)."""
        return sum(r.size for r in self.roms if not r.is_continue())


@dataclass
class Software:
    """A single <software> element.

    ``cloneof`` is the short name of the parent software in the same list, or
    ``None`` for a parent set.
    """

    name: str
    description: str = ""
    year: Optional[int] = None
    publisher: str = ""
    info: List[Tuple[str, str]] = field(default_factory=list)
    cloneof: Optional[str] = None
    dataareas: List[DataArea] = field(default_factory=list)
    serial: Optional[str] = None
    release_date: Optional[str] = None
    # Region flags from source for the maincpu region
    maincpu_width: Optional[int] = None
    maincpu_endianness: Optional[str] = None

    def has_roms(self) -> bool:
        return any(area.roms for area in self.dataareas)


@dataclass
class GameEntry:
    """A parsed GAME() macro: the metadata side of a romset."""

    name: str  # short name
    parent: str  # parent short name, or a sentinel like "neogeo" / "neogeo_noslot"
    year: int
    manufacturer: str
    description: str
    driver: str  # the machine/driver this game uses
    flags: str = ""

    def is_parent_set(self, root_sentinels: List[str]) -> bool:
        """True when the parent field is a driver root (not a real game)."""
        return self.parent in root_sentinels


@dataclass
class RomBlock:
    """A parsed ROM_START() / ROM_END block.

    Maps the short ROM_START name to the structured dataareas. Note that the
    GAME() name may differ from the ROM_START name in edge cases (it usually
    doesn't, but we keep the link explicit in :class:`Software`).
    """

    name: str
    dataareas: List[DataArea] = field(default_factory=list)
