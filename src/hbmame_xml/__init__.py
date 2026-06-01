"""
hbmame_xml - Convert HBMAME source code listings into standalone MAME hash XML files.

This package parses HBMAME C++ driver source files (e.g. src/hbmame/drivers/neogeohb.cpp)
and converts their ROM_START / GAME definitions into a MAME softwarelist XML file
suitable for use as a standalone hash file (e.g. neogeo.xml).

Typical usage (CLI):

    python -m hbmame_xml --source ~/build/hbmame-HEAD --system neogeo --output neogeo.xml
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
