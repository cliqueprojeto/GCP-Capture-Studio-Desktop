"""Componentes reutilizáveis da interface."""
from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QWidget

from .. import theme


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    lb.setWordWrap(wrap)
    return lb


def separator() -> QFrame:
    line = QFrame()
    line.setProperty("role", "sep")
    line.setFixedHeight(1)
    return line


def vline(height: int = 26) -> QFrame:
    line = QFrame()
    line.setFixedSize(1, height)
    line.setStyleSheet(f"background: {theme.BORDER};")
    return line


def button(text: str = "", icon: str | None = None, role: str | None = None, icon_color: str | None = None, size: int = 18) -> QPushButton:
    b = QPushButton(text)
    if role:
        b.setProperty("role", role)
    if icon:
        color = icon_color or ("#08202e" if role == "primary" else "#ffffff" if role == "danger" else theme.ACCENT if role == "link" else theme.TEXT)
        b.setIcon(theme.icon(icon, color, size))
        b.setIconSize(QSize(size, size))
    b.setCursor(Qt.PointingHandCursor)
    return b


def tool_button(icon: str, tip: str, checkable: bool = False, size: int = 20, color: str = theme.TEXT) -> QToolButton:
    b = QToolButton()
    b.setIcon(theme.icon(icon, color, size, active=theme.ACCENT_HI if checkable else None))
    b.setIconSize(QSize(size, size))
    b.setToolTip(tip)
    b.setCheckable(checkable)
    b.setCursor(Qt.PointingHandCursor)
    b.setFocusPolicy(Qt.NoFocus)
    return b


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


class Toggle(QAbstractButton):
    """Interruptor deslizante."""

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(38, 22)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(130)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def get_knob(self) -> float:
        return self._pos

    def set_knob(self, v: float) -> None:
        self._pos = v
        self.update()

    knob = Property(float, get_knob, set_knob)

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        off, on = QColor(theme.BORDER), QColor(theme.ACCENT)
        t = self._pos
        col = QColor(
            int(off.red() + (on.red() - off.red()) * t),
            int(off.green() + (on.green() - off.green()) * t),
            int(off.blue() + (on.blue() - off.blue()) * t),
        )
        if not self.isEnabled():
            col.setAlphaF(0.4)
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 11, 11)
        p.setBrush(QColor("#ffffff"))
        x = 3 + (self.width() - 22) * t
        p.drawEllipse(QRectF(x, 3, 16, 16))


class LevelMeter(QWidget):
    """Medidor de nível de áudio com retenção de pico."""

    def __init__(self, parent=None, height: int = 8):
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setMinimumWidth(60)
        self._level = 0.0
        self._peak = 0.0

    def set_level(self, v: float) -> None:
        v = max(0.0, min(1.0, v))
        self._level = v if v > self._level else self._level * 0.82 + v * 0.18
        self._peak = max(v, self._peak - 0.012)
        self.update()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        rad = self.height() / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.BORDER))
        p.drawRoundedRect(r, rad, rad)
        if self._level > 0.005:
            grad = QLinearGradient(0, 0, self.width(), 0)
            grad.setColorAt(0.0, QColor(theme.OK))
            grad.setColorAt(0.7, QColor(theme.OK))
            grad.setColorAt(0.88, QColor(theme.WARN))
            grad.setColorAt(1.0, QColor(theme.REC))
            p.setBrush(grad)
            p.setClipRect(QRectF(0, 0, self.width() * self._level, self.height()))
            p.drawRoundedRect(r, rad, rad)
            p.setClipping(False)
        if self._peak > 0.02:
            p.setBrush(QColor("#ffffff"))
            x = min(self.width() - 2, self.width() * self._peak)
            p.drawRect(QRectF(x, 0, 2, self.height()))


class Swatch(QAbstractButton):
    """Amostra de cor selecionável."""

    def __init__(self, color: str, size: int = 20, parent=None):
        super().__init__(parent)
        self.color = color
        self.setCheckable(True)
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(color)
        self.setFocusPolicy(Qt.NoFocus)

    def set_color(self, color: str) -> None:
        self.color = color
        self.setToolTip(color)
        self.update()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2.5, 2.5, -2.5, -2.5)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self.color))
        p.drawEllipse(r)
        if self.isChecked():
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        elif QColor(self.color).lightness() < 40:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(theme.BORDER), 1))
            p.drawEllipse(r)


class RecordButton(QAbstractButton):
    """Botão REC circular."""

    def __init__(self, diameter: int = 92, parent=None):
        super().__init__(parent)
        self.setFixedSize(diameter, diameter)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Iniciar gravação")
        self._hover = False

    def enterEvent(self, ev) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, ev) -> None:
        self._hover = False
        self.update()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        enabled = self.isEnabled()
        base = QColor(theme.REC_HI if self._hover else theme.REC) if enabled else QColor("#5b6578")
        halo = QColor(base)
        halo.setAlphaF(0.18 if enabled else 0.1)
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(r)
        inner = r.adjusted(8, 8, -8, -8)
        if self.isDown():
            inner = inner.adjusted(2, 2, -2, -2)
        p.setBrush(base)
        p.drawEllipse(inner)
        p.setPen(QColor("#ffffff"))
        f = self.font()
        f.setPixelSize(int(self.width() * 0.2))
        f.setWeight(f.Weight.Bold)
        f.setLetterSpacing(f.SpacingType.AbsoluteSpacing, 1.2)
        p.setFont(f)
        p.drawText(inner, Qt.AlignCenter, "REC")


class DevFooter(QWidget):
    """Crédito do desenvolvedor com link e botão de apoio."""

    donate = Signal()

    def __init__(self, parent=None, show_donate: bool = True):
        super().__init__(parent)
        from .. import DEVELOPER, DEVELOPER_URL

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(label("Desenvolvido por", "small"))
        link = QPushButton(DEVELOPER)
        link.setProperty("role", "link")
        link.setCursor(Qt.PointingHandCursor)
        link.setToolTip(DEVELOPER_URL)
        link.setStyleSheet("font-size: 11.5px;")
        link.clicked.connect(lambda: open_url(DEVELOPER_URL))
        lay.addWidget(link)
        lay.addStretch(1)
        if show_donate:
            btn = button("Apoie o projeto", "heart", "link", size=14)
            btn.setStyleSheet("font-size: 11.5px;")
            btn.clicked.connect(self.donate.emit)
            lay.addWidget(btn)
