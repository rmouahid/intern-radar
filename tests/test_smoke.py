import tomllib
from pathlib import Path

import intern_radar


def test_package_version_matches_pyproject():
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    version = tomllib.loads(pyproject.read_text())["tool"]["poetry"]["version"]
    assert intern_radar.__version__ == version
