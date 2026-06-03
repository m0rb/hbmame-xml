# hbmame-xml

This project converts machine entries and romsets from [HBMAME](https://github.com/Robbbert/hbmame)
into monolithic per-machine and standalone romset MAME hash XML files.

`hbmame-xml` parses the C++ driver source that defines romsets in MAME/HBMAME
(`ROM_START(...) ... ROM_END` blocks and `GAME(...)` metadata macros) and
emits a MAME-compatible `<softwarelist>` XML file that can be used as a
standalone hash file for dump verification.

It is designed to run on a GitHub Actions runner.

The generated artifacts are committed back to this repository and
(optionally) a PR is opened.

## What it does

Given the HBMAME source tree, for each `<system>` (auto-discovered from
the driver files, with hardware variants merged — see **Driver
grouping** below) the converter produces two outputs:

1.  **Monolithic softwarelist** (under `machine-xml/`) — The canonical,
    single-file MAME hash format with the full XML/DOCTYPE preamble and a
    `<softwarelist>` wrapper.  All romsets in one file, sorted by name.

2.  **Per-romset directory tree** (under `romset-xml/`) — One bare
    `<software>` element per file, with **no** XML preamble and **no**
    `<softwarelist>` wrapper, organised as:

    `romset-xml/<system>/<char>/<romset>.xml`

    `<char>` is the uppercased first character of the romset name, or
    `_` if the first character is not alphanumeric.  This layout keeps
    any single directory small enough to browse.

Under the hood the converter:

1. Walks the configured list of C++ source files (e.g.
   `src/hbmame/drivers/neogeohb.cpp` and the upstream MAME
   `src/mame/drivers/neogeo.cpp` family).
2. Strips comments, then locates every `ROM_START(name) ... ROM_END`
   block and every `GAME(...)` macro using a parenthesis-aware scanner
   (handles arbitrarily nested parens, strings, and C++ templates).
3. Splits each macro into a structured representation
   (`RomBlock` / `DataArea` / `RomEntry` / `GameEntry`).
4. Matches `GAME(name)` entries to `ROM_START(name)` blocks by their
   short name.  For duplicate definitions (MAME upstream vs. HBMAME
   slot-less variants), the first definition seen wins, so the
   upstream MAME definitions take precedence.  A romset is only kept
   for a system when the system *claims* that game's machine driver
   (see **Driver grouping** below), so a romset can never land in more
   than one softwarelist.  A run aborts with a non-zero exit if any
   romset is ever claimed by two systems.
5. Renders one `<software>` element per romset, with proper
   `<part interface="neo_cart">`, `<dataarea width="16"
   endianness="big">`, `<rom loadflag="load16_word_swap" .../>` and
   `<rom loadflag="continue" .../>` markup.
6. Skips per-cart content that lives in BIOS regions
   (`mainbios`, `audiobios`, `fixedbios`, `zoomy`) and BIOS files
   (the various `sp-s2.sp1`, `uni-bios_*.rom`, `sfix.sfix`,
   `sm1.sm1`, ...).  The cartridge hash file only describes the
   cart-side content.

## Driver grouping

Each `GAME()` macro names the C++ *machine driver* it runs on (its 4th
argument), e.g. `neogeo_noslot`, `neogeo_kog`, `pgm_arm_type1`.  Many of
those drivers are just hardware-config variants (different CPU clock,
input layout, protection chip, ...) of a single logical system, and in
real MAME they all share one softwarelist.

`--system all` would otherwise emit one softwarelist per driver, which
fragments e.g. Neo Geo across `neogeo_noslot`, `neogeo_dial`,
`neogeo_kog`, `neogeo_mj`, ... — eight separate lists.  To avoid that,
driver names are folded into a **canonical** softwarelist name before any
output is written.

The mapping lives in [`config/driver_groups.toml`](config/driver_groups.toml):

```toml
[groups]
neogeo    = ["neogeo"]      # neogeo, neogeo_noslot, neogeo_kog, neogeo_mj, ...
pgm       = ["pgm"]         # pgm + pgm_arm_type*, pgm_asic3, ...
cps1      = ["cps1"]        # cps1_10MHz, cps1_12MHz
system16b = ["system16b"]   # system16b + _fd1094 / _i8751
# ...
```

Each entry maps a canonical name to the driver-name **prefixes** that
belong to it.  A driver `d` folds into canonical `C` when, for one of C's
prefixes `p`, `d == p` or `d.startswith(p + "_")`.  The longest matching
prefix wins, so you can carve out sub-families without swallowing
unrelated siblings (e.g. group `sega_system32` without merging
`sega_aburner2`).  Any driver matching no prefix keeps its own name as
its own softwarelist, so adding a brand-new HBMAME system needs no edits
here unless it ships several driver variants.

To merge a new family, just add a line to the `[groups]` table.  The file
is the single source of truth for both `--system all` and a single
`--system <name>` run.  (`HBMAME_XML_CONFIG` can point at an alternate
config file; if the file is missing the converter falls back to a
built-in default copy of the same map.)

## Repository layout

```
machine-xml/                    # monolithic softwarelist(s), one per system
├── neogeo.xml                  #   all neogeo romsets (4900+), variants merged
├── pgm.xml                     #   pgm + all pgm_* driver variants
├── ...                         #   (one file per canonical system)
└── ...

romset-xml/                     # per-romset directory tree
├── neogeo/
│   ├── A/
│   │   ├── abyssal.xml
│   │   ├── abyssal1.xml
│   │   └── ...
│   ├── B/
│   │   ├── b2b.xml
│   │   ├── badapple.xml
│   │   └── ...
│   ├── ...
│   └── Z/
│       ├── zedblade.xml
│       ├── zintrick.xml
│       └── ...
└── ...

src/hbmame_xml/                 # Python package (no third-party deps)
├── __init__.py
├── __main__.py                 #  `python -m hbmame_xml` entry point
├── convert.py                  #  CLI + convert_system()
├── generator.py                #  render_softwarelist / render_software_element
├── models.py                   #  dataclasses: Software, DataArea, ...
├── parser.py                   #  C++ comment stripper + macro scanner
└── systems.py                  #  per-system configurations (NEOGEO, ...)

tests/test_neogeo.py            #  20 unit + end-to-end tests
.github/workflows/convert.yml   #  GitHub Actions workflow
.gitignore
README.md
```

## Local usage

The Python package is the same one used by the GitHub workflow.

```bash
# Default: read HBMAME from $HBMAME_SRC or hbmame,
# write machine-xml/ and romset-xml/ to the current directory.
PYTHONPATH=src python3 -m hbmame_xml --verbose

# Or explicitly:
PYTHONPATH=src python3 -m hbmame_xml \
  --source hbmame \
  --system neogeo \
  --output-dir . \
  --verbose
```

Other CLI options:

| Flag                     | Description |
| ------------------------ | ----------- |
| `--source` / `-s`        | Path to the HBMAME working tree (default: `$HBMAME_SRC` or `hbmame`) |
| `--system`               | Target system/softwarelist (default: `neogeo`) |
| `--output-dir` / `-o`    | Directory to write `machine-xml/` and `romset-xml/` into (default: CWD) |
| `--no-monolithic`        | Skip writing `machine-xml/<system>.xml`; only emit per-romset files |
| `--no-per-romset`        | Skip writing `romset-xml/<system>/` tree; only emit monolithic XML |
| `--list-systems`         | List known systems and exit |
| `--include-empty`        | Include ROM_START blocks with no ROM_LOAD entries (normally skipped) |
| `--verbose` / `-v`       | Print progress to stderr |

## Library usage

```python
from pathlib import Path
from hbmame_xml.systems import get_system
from hbmame_xml.convert import convert_system, write_outputs
from hbmame_xml.generator import render_softwarelist, render_software_element

system = get_system("neogeo")

# Build the software list once:
xml, software_list = convert_system(system, Path("hbmame"))

# Write both machine-xml/ and romset-xml/ to disk:
write_outputs(system, Path("."), software_list)

# Or get the strings separately:
monolithic = render_softwarelist(system, software_list)
per_romset = {
    sw.name: render_software_element(sw, system) for sw in software_list
}
```

## Adding / tuning systems

Most systems need **no** code at all: `--system all` auto-discovers every
machine driver in the HBMAME tree and emits a softwarelist per canonical
name.  There are two things you may want to do:

1.  **Merge driver variants** of one system into a single list — edit
    [`config/driver_groups.toml`](config/driver_groups.toml) and add a
    `canonical = ["prefix", ...]` line (see **Driver grouping** above).
    No Python changes required.

2.  **Curate rendering details** for a system (its `<part interface=...>`,
    `default_sharedfeat`, `fix_maincpu`, a nicer description, extra
    upstream MAME source files, ...) — add a `System` instance in
    `src/hbmame_xml/systems.py` and register it in `SYSTEMS`:

    ```python
    CPS1 = System(
        name="cps1",
        description="Capcom CPS-1 cartridges",
        part_name="cart",
        interface="cps1_cart",
        source_files=["src/mame/drivers/cps1.cpp"],
        root_parent_sentinels=["cps1", "cps_state"],
        default_sharedfeat=[],
    )
    SYSTEMS["cps1"] = CPS1
    ```

    During `--system all`, a curated `System` is automatically merged with
    the discovered drivers for that canonical name: the curated rendering
    attributes win, while discovered source files and parent sentinels are
    merged in.  The workflow already runs `--system all`, so no per-system
    job is needed.

The parser itself is generic; the only per-system knobs are the driver
grouping config and the optional curated `System` overrides.

## Running the tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The end-to-end tests need a real HBMAME working tree at
`$HBMAME_SRC` or `hbmame`; they are skipped if that is
not available.

## License

The XML files generated from HBMAME's own source code listings are
derived from the HBMAME project, which is licensed under the BSD
3-clause "New" or "Revised" License and the MAME project's overall
license terms.  The Python code in this repository is provided under
the same terms (see the `COPYING` file in
[Robbbert/hbmame](https://github.com/Robbbert/hbmame) for details).