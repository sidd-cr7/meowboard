import os
import sys

import pytest

os.environ.setdefault("SDL_AUDIODRIVER", "dummy")   # in-process audio is silent; the real app uses the real device
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from audit.harness import Harness  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture(scope="session")
def harness(qapp):
    h = Harness()
    assert h.focus(), "audit window could not take keyboard focus - aborting before any key injection"
    yield h
    h.close()
