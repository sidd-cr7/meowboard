"""A focus-grabbing Qt window that receives (and counts) real keystrokes injected by the audit."""
import time
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QVBoxLayout, QWidget

from . import winio


class Harness(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MEOWBOARD AUDIT HARNESS - do not type here")
        self.resize(520, 160)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("MEOWBOARD audit is injecting test keystrokes into this window."))
        self.edit = QLineEdit()
        lay.addWidget(self.edit)
        self.downs = []     # native VKs of received key presses (including auto-repeat)
        self.ups = []
        self.edit.installEventFilter(self)
        self.capture = False   # when True the filter swallows keys after counting (no text growth)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.KeyPress:
            self.downs.append(ev.nativeVirtualKey())
            return self.capture
        if t == QEvent.KeyRelease:
            self.ups.append(ev.nativeVirtualKey())
            return self.capture
        return False

    @property
    def hwnd(self) -> int:
        return int(self.winId())

    def pump(self, seconds=0.0):
        end = time.time() + seconds
        QApplication.processEvents()
        while time.time() < end:
            QApplication.processEvents()
            time.sleep(0.003)

    def focus(self) -> bool:
        self.show()
        self.raise_()
        self.activateWindow()
        self.edit.setFocus()
        self.pump(0.1)
        ok = winio.force_foreground(self.hwnd)
        self.edit.setFocus()
        self.pump(0.1)
        return ok
