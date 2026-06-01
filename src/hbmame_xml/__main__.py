"""Allow ``python -m hbmame_xml`` to invoke the CLI."""

from .convert import main

raise SystemExit(main())
