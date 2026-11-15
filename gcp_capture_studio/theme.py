"""Tema visual: cores, folha de estilos e ícones vetoriais embutidos."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).parent / "assets"

BG = "#0e1522"
SURFACE = "#162031"
CARD = "#1c2940"
CARD_HI = "#24344f"
BORDER = "#2b3a54"
TEXT = "#e9eff8"
MUTED = "#93a3ba"
ACCENT = "#63c1ee"
ACCENT_HI = "#8ad4f5"
VIOLET = "#7c5cff"
REC = "#ef4444"
REC_HI = "#f87171"
OK = "#34d399"
WARN = "#f59e0b"

FONT = '"Inter", "Noto Sans", "Segoe UI", "Helvetica Neue", sans-serif'

_ICONS = {
    "monitor": '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
    "window": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/>',
    "region": '<path d="M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2M20 16v2a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-2"/>',
    "mic": '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3zM19 10v2a7 7 0 0 1-14 0v-2M12 19v3"/>',
    "speaker": '<path d="M11 5 6 9H2v6h4l5 4V5zM15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14"/>',
    "webcam": '<path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2"/>',
    "settings": '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
    "heart": '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8l1 1.1L12 21.2l7.8-7.7 1-1.1a5.5 5.5 0 0 0 0-7.8z"/>',
    "x": '<path d="M18 6 6 18M6 6l12 12"/>',
    "minus": '<path d="M5 12h14"/>',
    "pause": '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
    "stop": '<rect x="5" y="5" width="14" height="14" rx="2.5"/>',
    "play": '<path d="M6 3l14 9-14 9V3z"/>',
    "trash": '<path d="M3 6h18M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    "cursor": '<path d="M4 3l7 17 2.5-7.5L21 10 4 3z"/>',
    "pen": '<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>',
    "highlighter": '<path d="M9 11l-6 6v3h9l3-3M22 12l-4.6 4.6a2 2 0 0 1-2.8 0l-5.2-5.2a2 2 0 0 1 0-2.8L14 4"/>',
    "arrow": '<path d="M5 19 19 5M9 5h10v10"/>',
    "line": '<path d="M5 19 19 5"/>',
    "rect": '<rect x="3" y="5" width="18" height="14" rx="2"/>',
    "ellipse": '<ellipse cx="12" cy="12" rx="9" ry="7"/>',
    "text": '<path d="M4 7V4h16v3M9 20h6M12 4v16"/>',
    "blur": '<path d="M12 2.7l5.7 5.6a8 8 0 1 1-11.4 0L12 2.7z"/>',
    "undo": '<path d="M3 7v6h6M3 13a9 9 0 1 0 3-7.7L3 8"/>',
    "redo": '<path d="M21 7v6h-6M21 13a9 9 0 1 1-3-7.7L21 8"/>',
    "magnifier": '<circle cx="11" cy="11" r="8"/><path d="M21 21l-4.3-4.3M11 8v6M8 11h6"/>',
    "spotlight": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/>',
    "highlight": '<circle cx="12" cy="12" r="9"/><path d="M9 8l3 8 1.2-3.2L16 12 9 8z"/>',
    "click": '<path d="M9 9l5 12 1.8-5.2L21 14 9 9zM7.2 2.2 8 5.1M5.1 8l-2.9-.8M14 4.1 12 6M6 12l-1.9 2"/>',
    "external": '<path d="M7 17 17 7M8 7h9v9"/>',
    "copy": '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "folder": '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
    "film": '<rect x="2" y="2" width="20" height="20" rx="2.2"/><path d="M7 2v20M17 2v20M2 12h20M2 7h5M2 17h5M17 17h5M17 7h5"/>',
    "keyboard": '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M6 9h.01M10 9h.01M14 9h.01M18 9h.01M7 15h10"/>',
    "zoom": '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
    "refresh": '<path d="M21 2v6h-6M3 22v-6h6M21 8a9 9 0 0 0-15.5-3.4L3 8M3 16a9 9 0 0 0 15.5 3.4L21 16"/>',
    "grip": '<path d="M9 5h.01M9 12h.01M9 19h.01M15 5h.01M15 12h.01M15 19h.01" stroke-width="3"/>',
    "tools": '<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/><path d="M3 7h6M6 4v6"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    "gpu": '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/>',
}


def svg(name: str, color: str = TEXT, stroke: float = 2.0) -> bytes:
    body = _ICONS[name]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    ).encode()


def pixmap(name: str, color: str = TEXT, size: int = 20, stroke: float = 2.0) -> QPixmap:
    scale = 2
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    QSvgRenderer(QByteArray(svg(name, color, stroke))).render(painter, QRectF(0, 0, size * scale, size * scale))
    painter.end()
    pm.setDevicePixelRatio(scale)
    return pm


def icon(name: str, color: str = TEXT, size: int = 20, active: str | None = None) -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Normal, QIcon.Off)
    if active:
        ic.addPixmap(pixmap(name, active, size), QIcon.Normal, QIcon.On)
        ic.addPixmap(pixmap(name, active, size), QIcon.Active, QIcon.On)
    return ic


def logo_pixmap(size: int = 48) -> QPixmap:
    scale = 2
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    QSvgRenderer(str(ASSETS / "logo.svg")).render(painter, QRectF(0, 0, size * scale, size * scale))
    painter.end()
    pm.setDevicePixelRatio(scale)
    return pm


def app_icon() -> QIcon:
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(s, s)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        QSvgRenderer(str(ASSETS / "logo.svg")).render(painter, QRectF(0, 0, s, s))
        painter.end()
        ic.addPixmap(pm)
    return ic


def rec_tray_icon(recording: bool, paused: bool = False) -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(str(ASSETS / "logo.svg")).render(p, QRectF(0, 0, 64, 64))
    if recording:
        p.setPen(QColor("#ffffff"))
        p.setBrush(QColor(WARN if paused else REC))
        p.drawEllipse(QRectF(36, 36, 26, 26))
    p.end()
    return QIcon(pm)


def alpha(color: str, a: float) -> str:
    c = QColor(color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{a})"


STYLESHEET = f"""
* {{ font-family: {FONT}; font-size: 13px; color: {TEXT}; outline: none; }}
QToolTip {{ background: #0a101b; color: {TEXT}; border: 1px solid {BORDER}; padding: 5px 8px; border-radius: 6px; }}
QDialog, QWidget#root {{ background: {BG}; }}
QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-size: 20px; font-weight: 700; }}
QLabel[role="h2"] {{ font-size: 15px; font-weight: 650; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="small"] {{ color: {MUTED}; font-size: 11.5px; }}
QLabel[role="eyebrow"] {{ color: {ACCENT}; font-size: 10.5px; font-weight: 700; letter-spacing: 1.6px; }}
QLabel[role="link"] {{ color: {ACCENT}; }}
QFrame[role="card"] {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame[role="panel"] {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 18px; }}
QFrame[role="sep"] {{ background: {BORDER}; max-height: 1px; min-height: 1px; border: none; }}

QPushButton {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 9px; padding: 8px 14px; font-weight: 600; }}
QPushButton:hover {{ background: {CARD_HI}; border-color: #3a4d6e; }}
QPushButton:pressed {{ background: #18243a; }}
QPushButton:disabled {{ color: #5d6b82; background: #141d2c; border-color: #1f2b40; }}
QPushButton[role="primary"] {{ background: {ACCENT}; color: #08202e; border: none; font-weight: 700; }}
QPushButton[role="primary"]:hover {{ background: {ACCENT_HI}; }}
QPushButton[role="danger"] {{ background: {REC}; color: white; border: none; font-weight: 700; }}
QPushButton[role="danger"]:hover {{ background: {REC_HI}; }}
QPushButton[role="ghost"] {{ background: transparent; border: none; padding: 6px; border-radius: 8px; }}
QPushButton[role="ghost"]:hover {{ background: {alpha(TEXT, 0.08)}; }}
QPushButton[role="link"] {{ background: transparent; border: none; color: {ACCENT}; padding: 2px 0; font-weight: 600; text-align: left; }}
QPushButton[role="link"]:hover {{ color: {ACCENT_HI}; }}

QPushButton[role="mode"] {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; padding: 12px 10px; font-weight: 600; color: {MUTED}; }}
QPushButton[role="mode"]:hover {{ background: {CARD}; color: {TEXT}; }}
QPushButton[role="mode"]:checked {{ background: {alpha(ACCENT, 0.13)}; border: 1.5px solid {ACCENT}; color: {TEXT}; }}

QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 6px; }}
QToolButton:hover {{ background: {alpha(TEXT, 0.08)}; }}
QToolButton:checked {{ background: {alpha(ACCENT, 0.18)}; border-color: {alpha(ACCENT, 0.65)}; }}
QToolButton:disabled {{ background: transparent; }}

QComboBox {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 10px; min-height: 20px; }}
QComboBox:hover {{ border-color: #3a4d6e; }}
QComboBox:disabled {{ color: #5d6b82; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: none; width: 0; height: 0; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid {MUTED}; margin-right: 8px; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; selection-background-color: {alpha(ACCENT, 0.22)}; selection-color: {TEXT}; outline: none; }}
QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 2px 8px; border-radius: 6px; color: {TEXT}; }}
QComboBox QAbstractItemView::item:hover, QComboBox QAbstractItemView::item:selected {{ background: {alpha(ACCENT, 0.22)}; color: {TEXT}; }}
QComboBox QAbstractItemView::item:disabled {{ color: #5d6b82; }}
QComboBoxPrivateContainer {{ background: {SURFACE}; border: 1px solid {BORDER}; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QKeySequenceEdit {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 10px; selection-background-color: {alpha(ACCENT, 0.4)}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}
QPlainTextEdit {{ background: #0a101b; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px; font-family: monospace; font-size: 11px; color: {MUTED}; }}

QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
QSlider::handle:horizontal:hover {{ background: {ACCENT_HI}; }}
QSlider::sub-page:horizontal:disabled {{ background: #3a4d6e; }}

QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 34px; height: 18px; border-radius: 9px; background: {BORDER}; border: none; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 9px 16px; margin-right: 2px; border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}

QScrollArea {{ background: transparent; border: none; }}
QTextBrowser, QTextEdit {{ background: {CARD}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px; }}
QProgressBar {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 6px; height: 10px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #33445f; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #46597a; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; height: 0; width: 0; }}

QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 7px 22px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {alpha(ACCENT, 0.2)}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}
"""


def dark_palette() -> QPalette:
    """Paleta escura do aplicativo. Tudo o que a folha de estilos não alcança (lista flutuante das
    caixas de seleção, menus, diálogos do Qt) usa a paleta; sem ela, num sistema com tema claro
    essas partes ficam com fundo branco e o texto claro do tema some."""
    pal = QPalette()
    roles = {
        QPalette.Window: BG, QPalette.WindowText: TEXT, QPalette.Base: SURFACE, QPalette.AlternateBase: CARD,
        QPalette.Text: TEXT, QPalette.Button: CARD, QPalette.ButtonText: TEXT, QPalette.BrightText: "#ffffff",
        QPalette.ToolTipBase: "#0a101b", QPalette.ToolTipText: TEXT, QPalette.PlaceholderText: MUTED,
        QPalette.Highlight: ACCENT, QPalette.HighlightedText: "#08202e", QPalette.Link: ACCENT, QPalette.LinkVisited: VIOLET,
        QPalette.Light: CARD_HI, QPalette.Midlight: CARD, QPalette.Mid: BORDER, QPalette.Dark: "#0a101b", QPalette.Shadow: "#000000",
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor("#5d6b82"))
    return pal


def icon_size(n: int) -> QSize:
    return QSize(n, n)
