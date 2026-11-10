"""
Custom widgets for the MEOWBOARD interface.

ToggleSwitch        - large animated ON/OFF switch
SegmentedControl    - pill selector with a sliding highlight
PulseDot            - status dot that pulses on activity
KeyboardVisualizer  - real key layout coloured by each key's pitch (per personality) that lights up
                      when keys are played
"""
import math
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QToolTip, QWidget

from ..config.settings import PITCH_MAX, PITCH_MIN

# ---------------------------------------------------------------- palette
BG_CARD = QColor("#151821")
BORDER = QColor("#242938")
TEXT = QColor("#e8eaf2")
MUTED = QColor("#7b8396")
ACCENT = QColor("#a78bfa")
ACCENT_2 = QColor("#f0abfc")
GOOD = QColor("#34d399")
WARN = QColor("#fbbf24")
BAD = QColor("#f87171")
OFF = QColor("#3a4052")


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
        int(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


# ---------------------------------------------------------------- ToggleSwitch

class ToggleSwitch(QAbstractButton):
    """Large rounded ON/OFF switch with an animated knob. Click/Space toggles; emits toggled(bool)."""

    def __init__(self, checked: bool = True, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(132, 60)
        self.setFocusPolicy(Qt.StrongFocus)
        self._t = 1.0 if checked else 0.0
        super().setChecked(checked)
        self._anim = QPropertyAnimation(self, b"position", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self.toggled.connect(self._animate)

    def _get_pos(self) -> float:
        return self._t

    def _set_pos(self, v: float):
        self._t = v
        self.update()

    position = Property(float, _get_pos, _set_pos)

    def _animate(self, checked: bool):
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def set_checked_silently(self, checked: bool):
        """Sync with external state without emitting toggled."""
        if self.isChecked() == checked:
            return
        self.blockSignals(True)
        super().setChecked(checked)
        self.blockSignals(False)
        self._animate(checked)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        radius = r.height() / 2
        # glow when on
        if self._t > 0.01:
            glow = QColor(ACCENT)
            glow.setAlpha(int(55 * self._t))
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), radius + 2, radius + 2)
        grad = QLinearGradient(r.topLeft(), r.topRight())
        grad.setColorAt(0, _mix(OFF, QColor("#8b5cf6"), self._t))
        grad.setColorAt(1, _mix(OFF, QColor("#ec4899"), self._t))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(r, radius, radius)

        knob_d = r.height() - 10
        x0, x1 = r.left() + 5, r.right() - 5 - knob_d
        kx = x0 + (x1 - x0) * self._t
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(kx, r.top() + 5, knob_d, knob_d))

        f = QFont(self.font())
        f.setBold(True)
        f.setPointSizeF(10.5)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, int(235 * self._t)))
        p.drawText(QRectF(r.left() + 16, r.top(), r.width() - knob_d - 24, r.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, "ON")
        p.setPen(QColor(200, 205, 220, int(235 * (1 - self._t))))
        p.drawText(QRectF(r.left() + knob_d + 14, r.top(), r.width() - knob_d - 24, r.height()),
                   Qt.AlignVCenter | Qt.AlignRight, "OFF")
        if self.hasFocus():
            p.setPen(QPen(ACCENT_2, 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), radius, radius)


# ---------------------------------------------------------------- SegmentedControl

class SegmentedControl(QWidget):
    """Rounded segmented selector. options: [(key, title, subtitle)]. Emits selected(key) on user click."""
    selected = Signal(str)

    def __init__(self, options: Sequence[Tuple[str, str, str]], current: Optional[str] = None,
                 columns: Optional[int] = None, parent=None):
        super().__init__(parent)
        self._options = list(options)
        self._cols = columns or len(self._options)
        self._rows = (len(self._options) + self._cols - 1) // self._cols
        self._index = 0
        if current is not None:
            self._index = max(0, self._keys().index(current)) if current in self._keys() else 0
        self._hover = -1
        self._ix, self._iy = self._cell_xy(self._index)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(52 * self._rows + 6 * (self._rows - 1))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._ax = QPropertyAnimation(self, b"hx", self)
        self._ay = QPropertyAnimation(self, b"hy", self)
        for a in (self._ax, self._ay):
            a.setDuration(200)
            a.setEasingCurve(QEasingCurve.InOutCubic)

    def _keys(self) -> List[str]:
        return [o[0] for o in self._options]

    def _cell_xy(self, i: int) -> Tuple[float, float]:
        return float(i % self._cols), float(i // self._cols)

    def _get_hx(self): return self._ix
    def _set_hx(self, v): self._ix = v; self.update()
    def _get_hy(self): return self._iy
    def _set_hy(self, v): self._iy = v; self.update()
    hx = Property(float, _get_hx, _set_hx)
    hy = Property(float, _get_hy, _set_hy)

    def current(self) -> str:
        return self._options[self._index][0]

    def set_current(self, key: str, animate: bool = True):
        if key not in self._keys():
            return
        self._index = self._keys().index(key)
        tx, ty = self._cell_xy(self._index)
        if animate and self.isVisible():
            for a, start, end in ((self._ax, self._ix, tx), (self._ay, self._iy, ty)):
                a.stop()
                a.setStartValue(start)
                a.setEndValue(end)
                a.start()
        else:
            self._ix, self._iy = tx, ty
        self.update()

    def _cell_rect(self, cx: float, cy: float) -> QRectF:
        gap = 6.0
        w = (self.width() - gap * (self._cols - 1)) / self._cols
        h = (self.height() - gap * (self._rows - 1)) / self._rows
        return QRectF(cx * (w + gap), cy * (h + gap), w, h)

    def _index_at(self, pos) -> int:
        for i in range(len(self._options)):
            x, y = self._cell_xy(i)
            if self._cell_rect(x, y).contains(QPointF(pos)):
                return i
        return -1

    def mouseMoveEvent(self, e):
        i = self._index_at(e.position())
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, _):
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, e):
        i = self._index_at(e.position())
        if i >= 0 and e.button() == Qt.LeftButton:
            self._choose(i)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Right, Qt.Key_Down):
            self._choose((self._index + 1) % len(self._options))
        elif e.key() in (Qt.Key_Left, Qt.Key_Up):
            self._choose((self._index - 1) % len(self._options))
        else:
            super().keyPressEvent(e)

    def _choose(self, i: int):
        if i == self._index:
            return
        self.set_current(self._options[i][0])
        self.selected.emit(self._options[i][0])

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # sliding highlight
        hl = self._cell_rect(self._ix, self._iy)
        grad = QLinearGradient(hl.topLeft(), hl.bottomRight())
        grad.setColorAt(0, QColor("#7c3aed"))
        grad.setColorAt(1, QColor("#c026d3"))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(hl, 14, 14)
        for i, (_k, title, sub) in enumerate(self._options):
            x, y = self._cell_xy(i)
            r = self._cell_rect(x, y)
            sel = (i == self._index)
            if not sel:
                p.setPen(QPen(BORDER, 1))
                p.setBrush(QColor(255, 255, 255, 14 if i == self._hover else 5))
                p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)
            f = QFont(self.font())
            f.setBold(True)
            f.setPointSizeF(10)
            p.setFont(f)
            p.setPen(QColor("#ffffff") if sel else TEXT)
            p.drawText(r.adjusted(0, 8, 0, 0), Qt.AlignHCenter | Qt.AlignTop, title)
            f2 = QFont(self.font())
            f2.setPointSizeF(8.2)
            p.setFont(f2)
            p.setPen(QColor(255, 255, 255, 200) if sel else MUTED)
            p.drawText(r.adjusted(0, 0, 0, -8), Qt.AlignHCenter | Qt.AlignBottom, sub)
        if self.hasFocus():
            p.setPen(QPen(ACCENT_2, 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(self._cell_rect(self._ix, self._iy).adjusted(-1, -1, 1, 1), 15, 15)


# ---------------------------------------------------------------- PulseDot

class PulseDot(QWidget):
    """Status dot with a soft ring that pulses when pulse() is called."""

    def __init__(self, color: QColor = GOOD, size: int = 16, parent=None):
        super().__init__(parent)
        self.setFixedSize(size + 12, size + 12)
        self._color = QColor(color)
        self._size = size
        self._pulse = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def set_color(self, color: QColor):
        if color != self._color:
            self._color = QColor(color)
            self.update()

    def pulse(self):
        self._pulse = 1.0
        if not self._timer.isActive():
            self._timer.start()

    def _tick(self):
        self._pulse *= 0.90
        if self._pulse < 0.02:
            self._pulse = 0.0
            self._timer.stop()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        if self._pulse > 0:
            ring = QColor(self._color)
            ring.setAlpha(int(150 * self._pulse))
            p.setPen(Qt.NoPen)
            p.setBrush(ring)
            rr = self._size / 2 + 6 * self._pulse
            p.drawEllipse(c, rr, rr)
        p.setPen(Qt.NoPen)
        p.setBrush(self._color)
        p.drawEllipse(c, self._size / 2 - 2, self._size / 2 - 2)


# ---------------------------------------------------------------- KeyboardVisualizer

def _k(vk, w=1.0, label=None):
    return (vk, w, label)


_GAP = None  # spacer marker: (None, width, None)
def _gap(w): return (None, w, None)


# Physical layout (rows of (vk, width_in_key_units, label)); gaps use vk=None.
_ROWS: List[List[tuple]] = [
    [_k(0x1B, 1, "Esc"), _gap(1), *[_k(0x70 + i, 1, f"F{i + 1}") for i in range(4)], _gap(.5),
     *[_k(0x74 + i, 1, f"F{i + 5}") for i in range(4)], _gap(.5),
     *[_k(0x78 + i, 1, f"F{i + 9}") for i in range(4)], _gap(.5),
     _k(0x2C, 1, "Prt"), _k(0x91, 1, "Scr"), _k(0x13, 1, "Pau")],
    [_k(0xC0, 1, "`"), *[_k(0x31 + i, 1, str((i + 1) % 10)) for i in range(9)], _k(0x30, 1, "0"),
     _k(0xBD, 1, "-"), _k(0xBB, 1, "="), _k(0x08, 2, "Bksp"), _gap(.5),
     _k(0x2D, 1, "Ins"), _k(0x24, 1, "Hm"), _k(0x21, 1, "PU"), _gap(.5),
     _k(0x90, 1, "Nm"), _k(0x6F, 1, "/"), _k(0x6A, 1, "*"), _k(0x6D, 1, "-")],
    [_k(0x09, 1.5, "Tab"), *[_k(v, 1, c) for v, c in zip(
        (0x51, 0x57, 0x45, 0x52, 0x54, 0x59, 0x55, 0x49, 0x4F, 0x50, 0xDB, 0xDD), "QWERTYUIOP[]")],
     _k(0xDC, 1.5, "\\"), _gap(.5),
     _k(0x2E, 1, "Del"), _k(0x23, 1, "End"), _k(0x22, 1, "PD"), _gap(.5),
     _k(0x67, 1, "7"), _k(0x68, 1, "8"), _k(0x69, 1, "9"), _k(0x6B, 1, "+")],
    [_k(0x14, 1.75, "Caps"), *[_k(v, 1, c) for v, c in zip(
        (0x41, 0x53, 0x44, 0x46, 0x47, 0x48, 0x4A, 0x4B, 0x4C, 0xBA, 0xDE), "ASDFGHJKL;'")],
     _k(0x0D, 2.25, "Enter"), _gap(.5), _gap(3), _gap(.5),
     _k(0x64, 1, "4"), _k(0x65, 1, "5"), _k(0x66, 1, "6")],
    [_k(0xA0, 2.25, "Shift"), *[_k(v, 1, c) for v, c in zip(
        (0x5A, 0x58, 0x43, 0x56, 0x42, 0x4E, 0x4D, 0xBC, 0xBE, 0xBF), "ZXCVBNM,./")],
     _k(0xA1, 2.75, "Shift"), _gap(.5), _gap(1), _k(0x26, 1, "↑"), _gap(1), _gap(.5),
     _k(0x61, 1, "1"), _k(0x62, 1, "2"), _k(0x63, 1, "3")],
    [_k(0xA2, 1.25, "Ctrl"), _k(0x5B, 1.25, "Win"), _k(0xA4, 1.25, "Alt"), _k(0x20, 6.25, "Space"),
     _k(0xA5, 1.25, "Alt"), _k(0x5C, 1.25, "Win"), _k(0x5D, 1.25, "Menu"), _k(0xA3, 1.25, "Ctrl"), _gap(.5),
     _k(0x25, 1, "←"), _k(0x28, 1, "↓"), _k(0x27, 1, "→"), _gap(.5),
     _k(0x60, 2, "0"), _k(0x6E, 1, ".")],
]
_TOTAL_UNITS = max(sum(w for _, w, _ in row) for row in _ROWS)

LOW_COLOR = QColor("#38bdf8")
HIGH_COLOR = QColor("#f472b6")


def pitch_color(pitch: float) -> QColor:
    return _mix(LOW_COLOR, HIGH_COLOR, (pitch - 0.88) / (1.17 - 0.88))


class KeyboardVisualizer(QWidget):
    """Draws the real keyboard; each key is tinted by its pitch and flashes when played."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(215)
        self.setMouseTracking(True)
        self._mapper = None
        self._personality = "NORMAL CAT"
        self._glow: Dict[int, float] = {}
        self._rects: Dict[int, QRectF] = {}
        self._last_name = ""
        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self._decay)

    def set_mapping(self, mapper, personality: str):
        self._mapper = mapper
        self._personality = personality
        self.update()

    def trigger_key_visual(self, profile):
        vk = profile.vk_code
        vk = {0x10: 0xA0, 0x11: 0xA2, 0x12: 0xA4}.get(vk, vk)
        self._glow[vk] = 1.0
        self._last_name = profile.name
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def _decay(self):
        for k in list(self._glow):
            self._glow[k] *= 0.86
            if self._glow[k] < 0.02:
                del self._glow[k]
        if not self._glow:
            self._timer.stop()
        self.update()

    def _pitch(self, vk: int) -> float:
        if self._mapper is None:
            return 1.0
        return self._mapper.pitch_for(vk, self._personality)

    def mouseMoveEvent(self, e):
        for vk, r in self._rects.items():
            if r.contains(e.position()):
                name = self._mapper.get_key_profile(vk).name if self._mapper else str(vk)
                st = 12 * math.log2(self._pitch(vk))
                QToolTip.showText(e.globalPosition().toPoint(), f"{name}   {st:+.2f} semitones", self)
                return
        QToolTip.hideText()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        legend_h = 22
        avail_w, avail_h = self.width(), self.height() - legend_h
        unit = min(avail_w / _TOTAL_UNITS, avail_h / len(_ROWS))
        gap = max(2.0, unit * 0.1)
        ox = (avail_w - unit * _TOTAL_UNITS) / 2
        self._rects = {}
        f = QFont(self.font())
        f.setPointSizeF(max(6.0, unit * 0.27))
        p.setFont(f)
        for ri, row in enumerate(_ROWS):
            x = ox
            y = ri * unit
            for vk, w, label in row:
                if vk is None:
                    x += w * unit
                    continue
                r = QRectF(x + gap / 2, y + gap / 2, w * unit - gap, unit - gap)
                self._rects[vk] = r
                base = pitch_color(self._pitch(vk))
                g = self._glow.get(vk, 0.0)
                fill = QColor(base)
                fill.setAlpha(int(70 + 170 * g))
                p.setPen(QPen(QColor(base.red(), base.green(), base.blue(), int(110 + 145 * g)), 1))
                p.setBrush(fill)
                rad = unit * 0.22
                p.drawRoundedRect(r, rad, rad)
                p.setPen(QColor(255, 255, 255, int(150 + 105 * g)))
                p.drawText(r, Qt.AlignCenter, label or "")
                x += w * unit
        # legend: low -> high pitch
        ly = self.height() - legend_h + 8
        lw = min(220.0, avail_w * 0.4)
        lx = (avail_w - lw) / 2
        grad = QLinearGradient(lx, 0, lx + lw, 0)
        grad.setColorAt(0, LOW_COLOR)
        grad.setColorAt(1, HIGH_COLOR)
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(lx, ly, lw, 5), 2.5, 2.5)
        lf = QFont(self.font())
        lf.setPointSizeF(8)
        p.setFont(lf)
        p.setPen(MUTED)
        p.drawText(QRectF(lx - 70, ly - 6, 64, 16), Qt.AlignRight | Qt.AlignVCenter, "lower")
        p.drawText(QRectF(lx + lw + 6, ly - 6, 64, 16), Qt.AlignLeft | Qt.AlignVCenter, "higher")
