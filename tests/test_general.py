#!/usr/bin/env python3
"""
General tests for hbmame-xml parser and converter - not system specific.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import hbmame_xml.parser as prs
import hbmame_xml.systems as systems
import hbmame_xml.convert as convert


class TestCommentStripping(unittest.TestCase):
    """Tests for comment stripping functionality."""

    def test_block_comment_removal(self):
        """Test that /* */ comments are removed."""
        input_text = "ROM_LOAD(/* this is a comment */\"test.bin\")"
        expected = "ROM_LOAD(\"test.bin\")"
        self.assertEqual(expected, prs.strip_cpp_comments(input_text))

    def test_line_comment_removal(self):
        """Test that // comments are removed."""
        input_text = "ROM_LOAD(\"test.bin\") // this is a line comment"
        expected = "ROM_LOAD(\"test.bin\") "
        self.assertEqual(expected, prs.strip_cpp_comments(input_text))

    def test_string_preservation(self):
        """Test that strings containing comment markers are preserved."""
        input_text = 'ROM_LOAD("test/*comment*.bin")'
        expected = 'ROM_LOAD("test/*comment*.bin")'
        self.assertEqual(expected, prs.strip_cpp_comments(input_text))


class TestMacroResolution(unittest.TestCase):
    """Tests for macro resolution functionality."""

    def test_simple_macro(self):
        """Test that simple #define macros are resolved."""
        source = """
#define CODE_SIZE 0x400000
ROM_REGION(CODE_SIZE, "maincpu", 0)
"""
        macros = prs.build_macro_table(source)
        self.assertIn("CODE_SIZE", macros)
        self.assertEqual(0x400000, macros["CODE_SIZE"])

    def test_hex_macro(self):
        """Test that hexadecimal macros are resolved."""
        source = """
#define QSOUND_SIZE 0x50000
ROM_REGION(QSOUND_SIZE, "audiocpu", 0)
"""
        macros = prs.build_macro_table(source)
        self.assertIn("QSOUND_SIZE", macros)
        self.assertEqual(0x50000, macros["QSOUND_SIZE"])

    def test_decimal_macro(self):
        """Test that decimal macros are resolved."""
        source = """
#define TILE_SIZE 1024
ROM_REGION(TILE_SIZE, "gfx", 0)
"""
        macros = prs.build_macro_table(source)
        self.assertIn("TILE_SIZE", macros)
        self.assertEqual(1024, macros["TILE_SIZE"])

    def test_multiple_macros(self):
        """Test that multiple macros are resolved correctly."""
        source = """
#define ROM1_SIZE 0x1000
#define ROM2_SIZE 0x2000
#define ROM3_SIZE 0x3000

ROM_REGION(ROM1_SIZE, "maincpu", 0)
ROM_REGION(ROM2_SIZE, "gfx1", 0)
ROM_REGION(ROM3_SIZE, "gfx2", 0)
"""
        macros = prs.build_macro_table(source)
        self.assertEqual(0x1000, macros["ROM1_SIZE"])
        self.assertEqual(0x2000, macros["ROM2_SIZE"])
        self.assertEqual(0x3000, macros["ROM3_SIZE"])


class TestParseMacros(unittest.TestCase):
    """Tests for macro parsing functionality."""

    def test_parse_define_macros(self):
        """Test that #define macros are extracted from source code."""
        source = """
// some comments
#define GAME_VERSION 2024
#define ROM_SIZE 0x100000
#define MANUFACTURER "Test Company"
        """
        macros = prs.build_macro_table(source)
        self.assertIn("GAME_VERSION", macros)
        self.assertEqual(2024, macros["GAME_VERSION"])
        self.assertIn("ROM_SIZE", macros)
        self.assertEqual(0x100000, macros["ROM_SIZE"])


class TestArgSplitting(unittest.TestCase):
    """Tests for top-level argument splitting."""

    def test_simple_arguments(self):
        """Test that simple arguments are split correctly."""
        args = prs.split_top_level_args('0, "test", 123, abc')
        self.assertEqual(["0", '"test"', "123", "abc"], args)

    def test_nested_arguments(self):
        """Test that arguments with nested parentheses are handled."""
        args = prs.split_top_level_args('(a+b), "test(c)", 123')
        self.assertEqual(["(a+b)", '"test(c)"', "123"], args)

    def test_quoted_arguments_with_commas(self):
        """Test that quoted strings containing commas are handled."""
        args = prs.split_top_level_args('"a,b,c", 123, "d,e,f"')
        self.assertEqual(['"a,b,c"', "123", '"d,e,f"'], args)


class TestROMRegionParsing(unittest.TestCase):
    """Tests for ROM region parsing."""

    def test_parse_rom_region(self):
        """Test that ROM_REGION macros are parsed correctly."""
        source = "ROM_REGION(0x100000, \"maincpu\", 0)"
        macros = {}
        calls = prs.find_macro_calls(source, ["ROM_REGION"])
        self.assertEqual(1, len(calls))
        from hbmame_xml.parser import _parse_rom_region
        size, name, flags, _ = _parse_rom_region(calls[0].body, macros)
        self.assertEqual(0x100000, size)
        self.assertEqual("maincpu", name)
        self.assertEqual("0", flags)


class TestROMConversion(unittest.TestCase):
    """Tests for ROM conversion functionality."""

    def test_convert_with_define_macros(self):
        """Test that ROM_REGION calls with macros are parsed correctly."""
        source = """
#define CODE_SIZE 0x400000
ROM_START(testgame)
    ROM_REGION(CODE_SIZE, "maincpu", 0)
    ROM_LOAD("test.bin", 0x0000, CODE_SIZE, CRC(1234abcd) SHA1(5678efgh))
ROM_END
        """
        blocks = prs.parse_rom_blocks(source)
        self.assertEqual(1, len(blocks))
        self.assertEqual("testgame", blocks[0].name)
        self.assertEqual(1, len(blocks[0].dataareas))
        dataarea = blocks[0].dataareas[0]
        self.assertEqual("maincpu", dataarea.name)
        self.assertEqual(0x400000, dataarea.size)
        self.assertEqual(1, len(dataarea.roms))
        self.assertEqual("test.bin", dataarea.roms[0].name)


class TestSystemDiscovery(unittest.TestCase):
    """Tests for system discovery functionality."""

    def test_discover_machines(self):
        """Test that machines can be discovered from HBMAME drivers."""
        # This test will fail if HBMAME source is not available
        # But it should handle the case gracefully
        from hbmame_xml.systems import SYSTEMS
        self.assertIn("neogeo", SYSTEMS)
        self.assertEqual("SNK Neo-Geo cartridges", SYSTEMS["neogeo"].description)


class TestPerRomsetPath(unittest.TestCase):
    """Tests for per-romset path calculation."""

    def test_alpha_character(self):
        """Test path calculation for games starting with alphabetic characters."""
        from hbmame_xml.generator import per_romset_path
        self.assertEqual("A/aliencha.xml", per_romset_path("aliencha"))
        self.assertEqual("B/baddudes.xml", per_romset_path("baddudes"))
        self.assertEqual("Z/zeroteam.xml", per_romset_path("zeroteam"))

    def test_numeric_character(self):
        """Test path calculation for games starting with numeric characters."""
        from hbmame_xml.generator import per_romset_path
        self.assertEqual("1/1942.xml", per_romset_path("1942"))
        self.assertEqual("0/005.bin.xml", per_romset_path("005.bin"))

    def test_special_character(self):
        """Test path calculation for games starting with special characters."""
        from hbmame_xml.generator import per_romset_path
        self.assertEqual("_/_96in1.xml", per_romset_path("_96in1"))
        self.assertEqual("_/-test.xml", per_romset_path("-test"))


class TestCLI(unittest.TestCase):
    """Tests for the command-line interface."""

    def test_default_source_argument(self):
        """Test that default source argument is correctly set."""
        parser = convert._make_argparser()
        args = parser.parse_args([])
        self.assertEqual("hbmame", str(args.source))

    def test_source_argument(self):
        """Test that -s/--source arguments are parsed correctly."""
        parser = convert._make_argparser()
        args = parser.parse_args(["--source", "/custom/path"])
        self.assertEqual("/custom/path", str(args.source))
        args = parser.parse_args(["-s", "/another/path"])
        self.assertEqual("/another/path", str(args.source))

    def test_system_argument(self):
        """Test that system arguments are parsed correctly."""
        parser = convert._make_argparser()
        args = parser.parse_args(["--system", "cps2"])
        self.assertEqual("cps2", args.system)
        args = parser.parse_args(["-S", "qsound"])
        self.assertEqual("qsound", args.system)

    def test_output_dir_argument(self):
        """Test that output directory arguments are parsed correctly."""
        parser = convert._make_argparser()
        args = parser.parse_args(["--output-dir", "./output"])
        self.assertEqual(Path("./output"), args.output_dir)
        args = parser.parse_args(["-o", "../build"])
        self.assertEqual(Path("../build"), args.output_dir)


class TestXMLGeneration(unittest.TestCase):
    """Tests for XML generation."""

    def test_basic_structure(self):
        """Test that generated XML has basic structure."""
        from hbmame_xml.models import GameEntry, RomBlock, DataArea, RomEntry
        from hbmame_xml.systems import System
        from hbmame_xml.generator import build_software, render_software_element

        block = RomBlock(
            "testgame",
            dataareas=[
                DataArea(
                    "maincpu",
                    0x100000,
                    roms=[
                        RomEntry("test.bin", 0x0, 0x80000, crc="1234abcd", sha1="5678efgh")
                    ]
                )
            ]
        )

        system = System("testsys", "Test System")
        game = GameEntry("testgame", "", 2024, "Test Company", "Test Game", driver="testsys")
        software = build_software(block, game, system)
        result = render_software_element(software, system)

        self.assertIn("<software name=\"testgame\">", result)
        self.assertIn("<description>Test Game</description>", result)
        self.assertIn("<year>2024</year>", result)
        self.assertIn("<publisher>Test Company</publisher>", result)
        self.assertIn("<rom name=\"test.bin\"", result)


if __name__ == "__main__":
    unittest.main()