from __future__ import annotations

import re
from pathlib import Path

from zpljet import __version__


def test_version_matches_pyproject() -> None:
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    match = re.search(r'^version = "(.+)"$', pyproject.read_text(), re.MULTILINE)
    assert match is not None
    assert __version__ == match.group(1)
