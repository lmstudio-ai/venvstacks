"""Fixtures and other test elements common to multiple test files."""

import tempfile

import pytest

from pathlib import Path
from typing import Generator


@pytest.fixture
def temp_dir_path() -> Generator[Path, None, None]:
    # Simple temp directory test fixture without the complexities of the pytest fixtures
    with tempfile.TemporaryDirectory() as dir_name:
        yield Path(dir_name)
