"""Dark, minimal, cat-inspired Qt stylesheet for MEOWBOARD."""

FONT_STACK = '"Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif'

DARK_THEME_QSS = f"""
* {{
    font-family: {FONT_STACK};
    font-size: 13px;
    color: #e8eaf2;
}}
QMainWindow, QWidget#Root {{
    background-color: #0d0f14;
}}
QLabel {{ background: transparent; }}

QFrame[class="Card"] {{
    background-color: #151821;
    border: 1px solid #242938;
    border-radius: 18px;
}}

QLabel[class="Brand"] {{
    font-size: 26px;
    font-weight: 800;
    letter-spacing: 3px;
    color: #f5f3ff;
}}
QLabel[class="Tagline"] {{ color: #7b8396; font-size: 12px; }}
QLabel[class="Section"] {{
    color: #7b8396;
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 1.6px;
}}
QLabel[class="Stat"] {{ font-size: 18px; font-weight: 700; }}
QLabel[class="StatCaption"] {{ color: #7b8396; font-size: 10px; letter-spacing: 1.2px; font-weight: 600; }}
QLabel[class="Activity"] {{ font-size: 16px; font-weight: 700; }}
QLabel[class="Muted"] {{ color: #7b8396; font-size: 12px; }}
QLabel[class="Value"] {{ color: #c4b5fd; font-weight: 700; font-size: 14px; }}

QPushButton[class="Primary"] {{
    background-color: #7c3aed;
    border: none;
    border-radius: 14px;
    padding: 10px 22px;
    font-weight: 700;
    color: white;
}}
QPushButton[class="Primary"]:hover {{ background-color: #8b5cf6; }}
QPushButton[class="Primary"]:pressed {{ background-color: #6d28d9; }}
QPushButton[class="Primary"]:focus {{ border: 2px solid #f0abfc; }}
QPushButton[class="Ghost"] {{
    background: transparent;
    border: 1px solid #2d3347;
    border-radius: 10px;
    padding: 4px 12px;
    color: #c4b5fd;
    font-size: 12px;
}}
QPushButton[class="Ghost"]:hover {{ background-color: #1d2230; }}

QSlider::groove:horizontal {{
    height: 8px; background: #232838; border-radius: 4px;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #8b5cf6, stop:1 #ec4899);
    border-radius: 4px;
}}
QSlider::handle:horizontal {{
    background: #ffffff; width: 20px; height: 20px; margin: -6px 0; border-radius: 10px;
}}
QSlider::handle:horizontal:hover {{ background: #f5f3ff; }}

QCheckBox {{ spacing: 8px; color: #9aa3b8; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 6px; border: 1px solid #2d3347; background: #151821;
}}
QCheckBox::indicator:checked {{ background: #7c3aed; border-color: #7c3aed; }}

QToolTip {{
    background-color: #1d2230; color: #e8eaf2; border: 1px solid #2d3347; padding: 4px 8px; border-radius: 6px;
}}
QMenu {{
    background-color: #151821; border: 1px solid #242938; border-radius: 10px; padding: 6px;
}}
QMenu::item {{ padding: 7px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background-color: #7c3aed; }}
QMenu::separator {{ height: 1px; background: #242938; margin: 5px 8px; }}
"""
