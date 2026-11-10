"""pytest で動かすときの準備（tools/ と tests/ を import できるように・後片付け）。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    helpers.cleanup()
