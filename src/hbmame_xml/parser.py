"""
C++ source code parser for HBMAME driver listings.

MAME / HBMAME driver code has a very regular structure:

    ROM_START( <short_name> )
        ROM_REGION( <size>, "<region_name>", <flags> )
        ROM_LOAD( "<file>", <offset>, <size>, CRC(<hex>) SHA1(<hex>) )
        ROM_LOAD16_WORD_SWAP( "<file>", <offset>, <size>, CRC(<hex>) SHA1(<hex>) )
        ROM_LOAD16_BYTE( "<file>", <offset>, <size>, CRC(<hex>) SHA1(<hex>) )
        ROM_LOAD32_BYTE( "<file>", <offset>, <size>, CRC(<hex>) SHA1(<hex>) )
        ROM_LOAD32_WORD_SWAP( "<file>", <offset>, <size>, CRC(<hex>) SHA1(<hex>) )
        ROMX_LOAD( "<file>", <offset>, <size>, CRC(<hex>) SHA1(<hex>), <flags> )
        ROM_CONTINUE( <offset>, <size> )
        ...
    ROM_END

    GAME( <year>, <short_name>, <parent>, <driver>, <inputs>, <state>,
          <init>, <rot>, "<manufacturer>", "<description>", <flags> )

The parser does NOT need to handle arbitrary C++. It strips comments, finds
these well-known macros using a small scanner, and uses a parenthesis-aware
argument extractor. The argument extractor walks the source character by
character from the position right after the opening paren of a macro call,
tracking nesting depth and string-literal state, until the matching close
paren is found. This is more robust than regex (which can't handle
arbitrarily nested parentheses) and more portable than depending on a full
C++ parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from .models import DataArea, GameEntry, RomBlock, RomEntry


# ---------------------------------------------------------------------------
# Pre-processing
# ---------------------------------------------------------------------------


def strip_cpp_comments(text: str) -> str:
    """Remove // ... and /* ... */ comments while preserving string literals.

    Newlines from removed line comments are kept so line numbers stay sane.
    """
    out: List[str] = []
    i = 0
    n = len(text)
    in_block = False
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_block:
            if c == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            if c == "\n":
                out.append("\n")
            i += 1
            continue
        if c == "/" and nxt == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        if c == '"':
            out.append(c)
            i += 1
            while i < n:
                ch = text[i]
                out.append(ch)
                if ch == "\\" and i + 1 < n:
                    out.append(text[i + 1])
                    i += 2
                elif ch == '"':
                    i += 1
                    break
                else:
                    i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def build_macro_table(text: str) -> dict[str, int]:
    """Extract ``#define NAME VALUE`` from a source file and build a symbol table.

    Supports hex (0x...), octal (0...), and decimal values.
    """
    table: dict[str, int] = {}
    for m in re.finditer(
        rb"#\s*define\s+([A-Z_][A-Z0-9_]*)\s+(0x[0-9a-fA-F]+|[0-9]+)",
        text.encode("utf-8"),
    ):
        name = m.group(1).decode()
        raw = m.group(2).decode().lower()
        try:
            if raw.startswith("0x"):
                table[name] = int(raw, 16)
            else:
                table[name] = int(raw, 10)
        except ValueError:
            continue
    return table


def resolve_int(token: str, macros: dict[str, int]) -> int:
    """Parse an integer token possibly referring to a ``#define`` constant."""
    token = token.strip()
    # Strip trailing type suffixes
    m = re.match(r"^(0[xX][0-9a-fA-F]+|[0-9]+)", token)
    if m:
        tok = m.group(1)
        if tok.lower().startswith("0x"):
            return int(tok, 16)
        if tok.startswith("0") and len(tok) > 1 and all(c in "01234567" for c in tok):
            return int(tok, 8)
        return int(tok, 10)
    # Try symbol table lookup
    m2 = re.match(r"^([A-Z_][A-Z0-9_]*)$", token)
    if m2 and m2.group(1) in macros:
        return macros[m2.group(1)]
    raise ValueError(f"Cannot resolve integer token: {token!r}")


# ---------------------------------------------------------------------------
# Macro scanner
# ---------------------------------------------------------------------------


@dataclass
class MacroCall:
    """A located macro invocation in preprocessed source text."""

    name: str
    body: str
    start: int
    end: int

    def __repr__(self) -> str:
        head = self.body[:60].replace("\n", " ")
        return f"MacroCall({self.name}, {head}...)"


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


def find_macro_calls(text: str, names: Iterable[str]) -> List[MacroCall]:
    name_set = set(names)
    name_alt = "|".join(re.escape(n) for n in names)
    pat = re.compile(r"\b(" + name_alt + r")\s*\(")
    out: List[MacroCall] = []
    for m in pat.finditer(text):
        name = m.group(1)
        if name not in name_set:
            continue
        open_pos = m.end() - 1
        try:
            close_pos = _find_matching_paren(text, open_pos)
        except ValueError:
            continue
        body = text[open_pos + 1 : close_pos]
        out.append(MacroCall(name=name, body=body, start=m.start(), end=close_pos + 1))
    return out


# ---------------------------------------------------------------------------
# Argument list splitting
# ---------------------------------------------------------------------------


def split_top_level_args(s: str) -> List[str]:
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


# ---------------------------------------------------------------------------
# Numeric literal parsing
# ---------------------------------------------------------------------------


def parse_int(s: str) -> int:
    s = s.strip()
    m = re.match(r"^([0-9a-fA-FxX]+)", s)
    if not m:
        raise ValueError(f"Cannot parse integer: {s!r}")
    tok = m.group(1)
    if tok.lower().startswith("0x"):
        return int(tok, 16)
    if tok.startswith("0") and len(tok) > 1 and tok[1:].isdigit():
        return int(tok, 8)
    return int(tok, 10)


# ---------------------------------------------------------------------------
# ROM macro parsing
# ---------------------------------------------------------------------------


ROM_LOAD_MACROS = {
    "ROM_LOAD": None,
    "ROM_LOAD16_BYTE": "load16_byte",
    "ROM_LOAD16_WORD_SWAP": "load16_word_swap",
    "ROM_LOAD32_BYTE": "load32_byte",
    "ROM_LOAD32_WORD_SWAP": "load32_word_swap",
    "ROMX_LOAD": None,
}

ROM_REGION_MACROS = [
    "ROM_REGION",
    "ROM_REGION16_BE",
    "ROM_REGION16_LE",
    "ROM_REGION32_BE",
    "ROM_REGION32_LE",
]

ALL_ROM_MACROS = list(ROM_LOAD_MACROS) + [
    "ROM_CONTINUE",
    "ROM_RELOAD",
] + ROM_REGION_MACROS


_NEOSET_BIOS_FILES = {
    "sp-s2.sp1", "sp-s.sp1", "sp-45.sp1", "sp-s3.sp1",
    "sp-u2.sp1", "sp-e.sp1", "sp1-u2", "sp1-u4.bin", "sp1-u3.bin",
    "sp-j2.sp1", "sp1.jipan.1024", "japan-j3.bin", "sp1-j3.bin",
    "sp-j3.sp1", "sp-1v1_3db8c.bin", "vs-bios.rom",
    "neo-epo.bin", "neo-po.bin", "neodebug.rom",
    "uni-bios_4_0.rom", "uni-bios_3_3.rom", "uni-bios_3_2.rom",
    "uni-bios_3_1.rom", "uni-bios_3_0.rom", "uni-bios_2_3.rom",
    "uni-bios_2_3o.rom", "uni-bios_2_2.rom", "uni-bios_2_1.rom",
    "uni-bios_2_0.rom", "uni-bios_1_3.rom", "uni-bios_1_2.rom",
    "uni-bios_1_2o.rom", "uni-bios_1_1.rom", "uni-bios_1_0.rom",
    "sfix.sfix", "sm1.sm1", "000-lo.lo",
}

_BIOS_REGION_NAMES = {"mainbios", "audiobios", "fixedbios", "zoomy"}


def _is_bios_file(name: str) -> bool:
    return name in _NEOSET_BIOS_FILES


def _is_bios_region(name: str) -> bool:
    return name in _BIOS_REGION_NAMES


def _extract_string_literal(arg: str) -> str:
    s = arg.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return bytes(s[1:-1], "utf-8").decode("unicode_escape")
    return s


def _extract_hash(
    args: List[str], hash_index: int, macros: Optional[dict[str, int]] = None
) -> Tuple[Optional[str], Optional[str]]:
    crc: Optional[str] = None
    sha1: Optional[str] = None
    joined = " ".join(args[hash_index:])

    # Handle CRCs as hex numbers e.g. CRC(0x12345678) or CRC(12345678)
    for m in re.finditer(r"\bCRC\s*\(\s*([0-9a-fA-FxX]+)\s*\)", joined):
        val = m.group(1).lower()
        if val.startswith("0x"):
            val = val[2:]
        # Pad to 8 hex digits
        val = val.zfill(8)
        crc = val
    for m in re.finditer(r"\bSHA1\s*\(\s*([0-9a-fA-FxX]+)\s*\)", joined):
        sha1 = m.group(1).lower()
        if sha1.startswith("0x"):
            sha1 = sha1[2:]

    if crc is None and sha1 is None:
        m = re.search(r"\b(?:ROM_)?HASH\s*\((.*)\)", joined, flags=re.DOTALL)
        if m:
            inner = m.group(1)
            for mm in re.finditer(r"\bCRC\s*\(\s*([0-9a-fA-FxX]+)\s*\)", inner):
                val = mm.group(1).lower()
                if val.startswith("0x"):
                    val = val[2:]
                val = val.zfill(8)
                crc = val
            for mm in re.finditer(r"\bSHA1\s*\(\s*([0-9a-fA-FxX]+)\s*\)", inner):
                sha1 = mm.group(1).lower()
    return crc, sha1


def _decode_load_flags(flags_str: str) -> Optional[str]:
    s = flags_str
    has_word = "ROM_GROUPWORD" in s
    has_byte = "ROM_GROUPBYTE" in s
    has_reverse = "ROM_REVERSE" in s
    skip = 0
    m = re.search(r"ROM_SKIP\s*\(\s*(\d+)\s*\)", s)
    if m:
        skip = int(m.group(1))
    if has_byte and skip == 3:
        return "load32_byte"
    if has_word and has_reverse and skip == 2:
        return "load32_word_swap"
    if has_word and has_reverse:
        return "load16_word_swap"
    if skip == 1:
        return "load16_byte"
    if skip == 3:
        return "load32_byte"
    if has_word and not has_reverse:
        return "load16_word"
    return None


def _parse_rom_load(
    body: str, macro: str, macros: dict[str, int]
) -> RomEntry:
    args = split_top_level_args(body)
    if len(args) < 4:
        raise ValueError(f"{macro} expects >=4 arguments, got {len(args)}: {body!r}")

    name = _extract_string_literal(args[0])
    offset = resolve_int(args[1], macros)
    size = resolve_int(args[2], macros)

    if macro == "ROMX_LOAD" and len(args) >= 5:
        loadflag = _decode_load_flags(args[4])
        crc, sha1 = _extract_hash(args, 3, macros)
    else:
        loadflag = ROM_LOAD_MACROS[macro]
        crc, sha1 = _extract_hash(args, 3, macros)

    status: Optional[str] = None
    if "ROM_BADDUMP" in body:
        status = "baddump"

    if _is_bios_file(name):
        return RomEntry(
            name=name,
            offset=offset,
            size=size,
            crc=crc,
            sha1=sha1,
            loadflag="__bios_skip__",
            status=status,
        )

    return RomEntry(
        name=name,
        offset=offset,
        size=size,
        crc=crc,
        sha1=sha1,
        loadflag=loadflag,
        status=status,
    )


def _parse_rom_region(
    body: str, macros: dict[str, int]
) -> Tuple[int, str, str, str]:
    args = split_top_level_args(body)
    if len(args) < 2:
        raise ValueError(f"ROM_REGION expects >=2 args, got {len(args)}: {body!r}")
    size = resolve_int(args[0], macros)
    name = _extract_string_literal(args[1])
    flags = args[2] if len(args) >= 3 else "0"
    return size, name, flags, ""


def _parse_rom_continue(
    body: str, macros: dict[str, int]
) -> Tuple[int, int]:
    args = split_top_level_args(body)
    if len(args) < 2:
        raise ValueError(f"ROM_CONTINUE expects 2 args, got {len(args)}: {body!r}")
    return resolve_int(args[0], macros), resolve_int(args[1], macros)


# ---------------------------------------------------------------------------
# ROM_START/ROM_END block extraction + parse
# ---------------------------------------------------------------------------


@dataclass
class _RawBlock:
    name: str
    text: str


_ROM_START_PAT = re.compile(r"\bROM_START\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)")
_ROM_END_PAT = re.compile(r"\bROM_END\b")


def _find_rom_start(
    text: str, pos: int
) -> Optional[Tuple[str, int, int]]:
    m = _ROM_START_PAT.search(text, pos)
    if not m:
        return None
    name = m.group(1)
    open_idx = text.find("(", m.start())
    if open_idx < 0:
        return None
    try:
        close_pos = _find_matching_paren(text, open_idx)
    except ValueError:
        return None
    return name, close_pos + 1, close_pos + 1


def _extract_rom_blocks(text: str) -> List[_RawBlock]:
    blocks: List[_RawBlock] = []
    pos = 0
    while True:
        found = _find_rom_start(text, pos)
        if found is None:
            break
        name, body_start, _ = found
        em = _ROM_END_PAT.search(text, body_start)
        if em is None:
            break
        body = text[body_start : em.start()]
        blocks.append(_RawBlock(name=name, text=body))
        pos = em.end()
    return blocks


def _parse_rom_block_body(
    body: str, macros: dict[str, int]
) -> List[DataArea]:
    dataareas: List[DataArea] = []
    current: Optional[DataArea] = None

    region_names = ROM_REGION_MACROS
    load_names = list(ROM_LOAD_MACROS) + ["ROM_CONTINUE", "ROM_RELOAD"]
    region_calls = {
        (c.start, c.name, c.body) for c in find_macro_calls(body, region_names)
    }
    load_calls = list(find_macro_calls(body, load_names))
    all_calls: List[Tuple[int, str, str]] = []
    for s, n, b in region_calls:
        all_calls.append((s, n, b))
    for c in load_calls:
        all_calls.append((c.start, c.name, c.body))
    all_calls.sort(key=lambda t: t[0])

    for _start, macro, call_body in all_calls:
        if macro in ROM_REGION_MACROS:
            size, name, flags_str, _ = _parse_rom_region(call_body, macros)
            if _is_bios_region(name):
                current = None
                continue
            width: Optional[int] = None
            endianness: Optional[str] = None
            if "ROMREGION_16BIT" in flags_str or "ROMREGION_16BIT" in macro:
                width = 16
            elif "ROMREGION_32BIT" in flags_str or "ROMREGION_32BIT" in macro:
                width = 32
            if "ROMREGION_BE" in flags_str or macro.endswith("_BE"):
                endianness = "big"
            elif "ROMREGION_LE" in flags_str or macro.endswith("_LE"):
                endianness = "little"
            current = DataArea(
                name=name, size=size, width=width, endianness=endianness
            )
            dataareas.append(current)
        elif macro == "ROM_CONTINUE":
            if current is None:
                continue
            off, sz = _parse_rom_continue(call_body, macros)
            current.roms.append(
                RomEntry(name=None, offset=off, size=sz, loadflag="continue")
            )
        elif macro == "ROM_RELOAD":
            continue
        else:
            if current is None:
                continue
            rom = _parse_rom_load(call_body, macro, macros)
            if rom.loadflag == "__bios_skip__":
                continue
            current.roms.append(rom)
    return dataareas


def parse_rom_block(
    body: str, name: str, macros: dict[str, int]
) -> RomBlock:
    return RomBlock(
        name=name, dataareas=_parse_rom_block_body(body, macros)
    )


def parse_rom_blocks(text: str) -> List[RomBlock]:
    macros = build_macro_table(text)
    return [
        parse_rom_block(b.text, b.name, macros)
        for b in _extract_rom_blocks(text)
    ]


# ---------------------------------------------------------------------------
# GAME() parsing
# ---------------------------------------------------------------------------


def _parse_game(body: str) -> GameEntry:
    args = split_top_level_args(body)
    if len(args) < 10:
        raise ValueError(f"GAME() expects >=10 args, got {len(args)}: {body!r}")
    year = parse_int(args[0])
    short = args[1]
    parent = args[2]
    machine = args[3]
    manufacturer = _extract_string_literal(args[8])
    description = _extract_string_literal(args[9])
    flags = args[10] if len(args) >= 11 else ""
    return GameEntry(
        name=short,
        parent=parent,
        year=year,
        manufacturer=manufacturer,
        description=description,
        driver=machine,
        flags=flags,
    )


def parse_game_macros(text: str) -> List[GameEntry]:
    return [_parse_game(c.body) for c in find_macro_calls(text, ["GAME"])]