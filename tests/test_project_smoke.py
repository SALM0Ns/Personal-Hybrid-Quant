"""Repository-level smoke tests that require no third-party dependencies."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_quant_package_imports() -> None:
    import quant

    assert quant.__doc__


def test_project_targets_python_312_or_newer() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]

    assert project["requires-python"] == ">=3.12"
    assert sys.version_info >= (3, 12)
