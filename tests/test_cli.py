"""Exercise the installed application independently of the source directory."""

import os
from pathlib import Path
import subprocess
import sys


def test_installed_command_can_initialize_and_inspect(tmp_path: Path) -> None:
    for command in ("init", "status"):
        result = subprocess.run(
            [sys.executable, "-m", "energy_pipeline.cli", command],
            cwd=tmp_path, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
    assert (tmp_path / "data/energy.sqlite3").exists()
    assert "api_cursor: 0" in result.stderr


def test_missing_key_fails_without_creating_database(tmp_path: Path) -> None:
    environment = dict(os.environ)
    environment.pop("ENERGY_API_KEY", None)
    result = subprocess.run(
        [sys.executable, "-m", "energy_pipeline.cli", "collect"],
        cwd=tmp_path, env=environment, capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "Set ENERGY_API_KEY" in result.stderr
    assert not (tmp_path / "data").exists()
