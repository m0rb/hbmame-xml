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

Given the HBMAME source tree, for each `<system>` (currently just
`neogeo`) the converter produces two outputs:

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
   upstream MAME definitions take precedence.
5. Renders one `<software>` element per romset, with proper
   `<part interface="neo_cart">`, `<dataarea width="16"
   endianness="big">`, `<rom loadflag="load16_word_swap" .../>` and
   `<rom loadflag="continue" .../>` markup.
6. Skips per-cart content that lives in BIOS regions
   (`mainbios`, `audiobios`, `fixedbios`, `zoomy`) and BIOS files
   (the various `sp-s2.sp1`, `uni-bios_*.rom`, `sfix.sfix`,
   `sm1.sm1`, ...).  The cartridge hash file only describes the
   cart-side content.

## Repository layout

```
machine-xml/                    # monolithic softwarelist(s)
├── neogeo.xml                  #   1.2 MB, all 713 romsets
├── ...                         #   (more systems in future)
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
# Default: read HBMAME from $HBMAME_SRC or ~/build/hbmame-HEAD,
# write machine-xml/ and romset-xml/ to the current directory.
PYTHONPATH=src python3 -m hbmame_xml --verbose

# Or explicitly:
PYTHONPATH=src python3 -m hbmame_xml \
  --source ~/build/hbmame-HEAD \
  --system neogeo \
  --output-dir . \
  --verbose
```

Other CLI options:

| Flag                     | Description |
| ------------------------ | ----------- |
| `--source` / `-s`        | Path to the HBMAME working tree (default: `$HBMAME_SRC` or `~/build/hbmame-HEAD`) |
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
xml, software_list = convert_system(system, Path("~/build/hbmame-HEAD"))

# Write both machine-xml/ and romset-xml/ to disk:
write_outputs(system, Path("."), software_list)

# Or get the strings separately:
monolithic = render_softwarelist(system, software_list)
per_romset = {
    sw.name: render_software_element(sw, system) for sw in software_list
}
```

## Adding new systems

To support another HBMAME system (e.g. `cps1`, `cps2`, `neogeocd`):

1.  Add a new `System` instance in `src/hbmame_xml/systems.py`:

    ```python
    CPS1 = System(
        name="cps1",
        description="Capcom CPS-1 cartridges",
        part_name="cart",
        interface="cps1_cart",
        source_files=[
            "src/mame/drivers/cps1.cpp",
            "src/hbmame/drivers/cps1.cpp",
            "src/hbmame/drivers/cps1bl_5205.cpp",
            "src/hbmame/drivers/cps1mis.cpp",
        ],
        root_parent_sentinels=["cps1", "cps_state"],
        default_sharedfeat=[],
    )
    SYSTEMS["cps1"] = CPS1
    ```

2.  Add a job (or extend the existing one) in
    `.github/workflows/convert.yml` to write `cps1.xml` and the
    `cps1/<char>/<romset>.xml` tree.

The parser is generic; the only per-system config is the list of
source files and which `GAME()` "parent" values denote a parent set
vs. a clone.

## Running the tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The end-to-end tests need a real HBMAME working tree at
`$HBMAME_SRC` or `~/build/hbmame-HEAD`; they are skipped if that is
not available.

## License

The XML files generated from HBMAME's own source code listings are
derived from the HBMAME project, which is licensed under the BSD
3-clause "New" or "Revised" License and the MAME project's overall
license terms.  The Python code in this repository is provided under
the same terms (see the `COPYING` file in
[Robbbert/hbmame](https://github.com/Robbbert/hbmame) for details).