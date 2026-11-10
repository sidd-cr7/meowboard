"""
Generates high-resolution cat-themed application and tray icons for MEOWBOARD.
"""
from pathlib import Path
import sys
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QImage,
    QPixmap,
    QIcon,
    QLinearGradient,
    QRadialGradient,
    QFont,
    QPen,
    QGuiApplication,
)


def create_cat_image(size: int = 256, active: bool = True) -> QImage:
    """Draws a sleek, modern cat emblem with glowing accents on a QImage."""
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)

    center_x = size / 2.0
    center_y = size / 2.0
    radius = size * 0.44

    # Background circle with subtle gradient
    bg_grad = QLinearGradient(0, 0, size, size)
    if active:
        bg_grad.setColorAt(0.0, QColor("#1e1b2e"))
        bg_grad.setColorAt(1.0, QColor("#13111c"))
    else:
        bg_grad.setColorAt(0.0, QColor("#222226"))
        bg_grad.setColorAt(1.0, QColor("#141416"))

    painter.setBrush(bg_grad)
    border_pen = QPen(QColor("#a855f7" if active else "#52525b"), max(2.0, size * 0.025))
    painter.setPen(border_pen)
    painter.drawEllipse(QRectF(center_x - radius, center_y - radius, radius * 2, radius * 2))

    # Cat Silhouette
    cat_path = QPainterPath()

    # Head and Ears
    head_top = size * 0.38
    head_bottom = size * 0.72
    head_left = size * 0.28
    head_right = size * 0.72

    # Left Ear
    cat_path.moveTo(size * 0.32, head_top + size * 0.05)
    cat_path.lineTo(size * 0.25, size * 0.22)  # Ear tip left
    cat_path.lineTo(size * 0.44, head_top - size * 0.02)

    # Forehead dip
    cat_path.quadTo(center_x, head_top, size * 0.56, head_top - size * 0.02)

    # Right Ear
    cat_path.lineTo(size * 0.75, size * 0.22)  # Ear tip right
    cat_path.lineTo(size * 0.68, head_top + size * 0.05)

    # Cheek right
    cat_path.quadTo(head_right + size * 0.04, center_y + size * 0.06, size * 0.65, head_bottom)

    # Chin
    cat_path.quadTo(center_x, head_bottom + size * 0.05, size * 0.35, head_bottom)

    # Cheek left
    cat_path.quadTo(head_left - size * 0.04, center_y + size * 0.06, size * 0.32, head_top + size * 0.05)

    cat_grad = QLinearGradient(0, size * 0.2, 0, size * 0.8)
    if active:
        cat_grad.setColorAt(0.0, QColor("#c084fc"))
        cat_grad.setColorAt(1.0, QColor("#7e22ce"))
    else:
        cat_grad.setColorAt(0.0, QColor("#71717a"))
        cat_grad.setColorAt(1.0, QColor("#3f3f46"))

    painter.setBrush(cat_grad)
    painter.setPen(Qt.NoPen)
    painter.drawPath(cat_path)

    # Glowing Cat Eyes
    eye_color = QColor("#38bdf8" if active else "#9ca3af")
    painter.setBrush(eye_color)

    # Left Eye (almond slant)
    left_eye = QPainterPath()
    left_eye.moveTo(size * 0.37, size * 0.47)
    left_eye.quadTo(size * 0.43, size * 0.43, size * 0.47, size * 0.47)
    left_eye.quadTo(size * 0.42, size * 0.52, size * 0.37, size * 0.47)
    painter.drawPath(left_eye)

    # Right Eye
    right_eye = QPainterPath()
    right_eye.moveTo(size * 0.53, size * 0.47)
    right_eye.quadTo(size * 0.57, size * 0.43, size * 0.63, size * 0.47)
    right_eye.quadTo(size * 0.58, size * 0.52, size * 0.53, size * 0.47)
    painter.drawPath(right_eye)

    # Nose (tiny inverted triangle)
    nose_path = QPainterPath()
    nose_path.moveTo(size * 0.48, size * 0.56)
    nose_path.lineTo(size * 0.52, size * 0.56)
    nose_path.lineTo(center_x, size * 0.59)
    nose_path.closeSubpath()
    painter.setBrush(QColor("#f472b6" if active else "#a1a1aa"))
    painter.drawPath(nose_path)

    # Whiskers
    whisker_pen = QPen(QColor(255, 255, 255, 140 if active else 50), max(1.2, size * 0.012))
    painter.setPen(whisker_pen)
    # Left whiskers
    painter.drawLine(QPointF(size * 0.42, size * 0.58), QPointF(size * 0.22, size * 0.55))
    painter.drawLine(QPointF(size * 0.42, size * 0.60), QPointF(size * 0.20, size * 0.62))
    painter.drawLine(QPointF(size * 0.42, size * 0.62), QPointF(size * 0.24, size * 0.69))
    # Right whiskers
    painter.drawLine(QPointF(size * 0.58, size * 0.58), QPointF(size * 0.78, size * 0.55))
    painter.drawLine(QPointF(size * 0.58, size * 0.60), QPointF(size * 0.80, size * 0.62))
    painter.drawLine(QPointF(size * 0.58, size * 0.62), QPointF(size * 0.76, size * 0.69))

    painter.end()
    return image


def create_cat_pixmap(size: int = 256, active: bool = True) -> QPixmap:
    img = create_cat_image(size, active)
    return QPixmap.fromImage(img)


def ensure_app_icons(icons_dir: Path) -> dict:
    """Generates and saves .png and .ico icon files."""
    # Ensure QGuiApplication exists if needed
    _app = QGuiApplication.instance()
    _created_app = False
    if _app is None:
        _app = QGuiApplication(sys.argv[:1])
        _created_app = True

    icons_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "app_png": icons_dir / "meowboard.png",
        "app_ico": icons_dir / "meowboard.ico",
        "tray_active": icons_dir / "tray_active.png",
        "tray_inactive": icons_dir / "tray_inactive.png",
    }

    img_app = create_cat_image(size=256, active=True)
    img_app.save(str(paths["app_png"]), "PNG")
    img_app.save(str(paths["app_ico"]), "ICO")

    img_tray_act = create_cat_image(size=64, active=True)
    img_tray_act.save(str(paths["tray_active"]), "PNG")

    img_tray_inact = create_cat_image(size=64, active=False)
    img_tray_inact.save(str(paths["tray_inactive"]), "PNG")

    return paths
