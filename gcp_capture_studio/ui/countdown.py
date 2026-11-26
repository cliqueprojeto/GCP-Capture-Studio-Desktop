"""Contagem regressiva antes da gravação e seletor de região/janela."""
from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .. import theme

_TOP = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.X11BypassWindowManagerHint | Qt.Tool


class Countdown(QWidget):
    """Cartão central: "Pressione F10 para parar a gravação" + 3, 2, 1."""

    finished = Signal()
    cancelled = Signal()

    def __init__(self):
        from ..platform.hyprland import managed

        super().__init__(None, managed(_TOP | Qt.WindowDoesNotAcceptFocus))
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("GCP Capture Studio — contagem")
        self.resize(460, 250)
        self.value = 3
        self.stop_key = "F10"
        self.pause_key = "F9"
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)

    def start(self, seconds: int, center: QPoint, stop_key: str, pause_key: str) -> None:
        self.stop_key, self.pause_key = stop_key or "—", pause_key or "—"
        if seconds <= 0:
            QTimer.singleShot(300, self.finished.emit)
            return
        self.value = seconds
        self.move(center - QPoint(self.width() // 2, self.height() // 2))
        from ..platform.hyprland import open_on_screen

        open_on_screen(self)
        self.show()
        self.raise_()
        self.timer.start()

    def _tick(self) -> None:
        self.value -= 1
        if self.value <= 0:
            self.timer.stop()
            self.hide()
            # dá tempo do compositor remover o cartão antes do primeiro quadro
            QTimer.singleShot(140, self.finished.emit)
        else:
            self.update()

    def cancel(self) -> None:
        if self.timer.isActive():
            self.timer.stop()
            self.hide()
            self.cancelled.emit()

    def mousePressEvent(self, _ev) -> None:
        self.cancel()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor(14, 21, 34, 240))
        p.drawRoundedRect(r, 20, 20)
        f = QFont()
        f.setPixelSize(17)
        p.setFont(f)
        text = [("Pressione ", theme.TEXT), (self.stop_key, theme.ACCENT), (" para parar a gravação", theme.TEXT)]
        fm = p.fontMetrics()
        total = sum(fm.horizontalAdvance(t) for t, _ in text)
        x = (self.width() - total) / 2
        for t, col in text:
            p.setPen(QColor(col))
            p.drawText(int(x), 48, t)
            x += fm.horizontalAdvance(t)
        p.setPen(QPen(QColor(theme.ACCENT), 2))
        p.drawLine(40, 68, self.width() - 40, 68)
        f.setPixelSize(104)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(theme.ACCENT))
        p.drawText(QRectF(0, 70, self.width(), 130), Qt.AlignCenter, str(self.value))
        f.setPixelSize(12)
        f.setWeight(QFont.Normal)
        p.setFont(f)
        p.setPen(QColor(theme.MUTED))
        p.drawText(QRectF(0, 208, self.width(), 24), Qt.AlignCenter, f"{self.pause_key} pausa · clique aqui para cancelar")


def screen_label(screen, index: int) -> str:
    """Nome amigável do monitor: "Tela do notebook (eDP-1)" ou "Monitor 2 (HDMI-A-1)"."""
    name = screen.name()
    kind = "Tela do notebook" if name.lower().startswith(("edp", "lvds", "dsi")) else f"Monitor {index + 1}"
    return f"{kind} ({name})" if name else kind


class _SelectorPane(QWidget):
    """Seleção em um monitor: região arrastando o mouse ou clique em uma janela destacada."""

    selected = Signal(QRect)  # coordenadas globais
    cancelled = Signal()
    began = Signal(object)  # o usuário começou a marcar neste monitor

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("Selecionar área — GCP Capture Studio")
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.start: QPoint | None = None
        self.rect_sel = QRect()
        self.windows: list[dict] = []
        self.hover: QRect = QRect()
        self.mode = "region"
        self.label = ""

    def begin(self, screen_geometry: QRect, mode: str = "region", windows: list[dict] | None = None,
              current: QRect | None = None, label: str = "", focus: bool = True) -> None:
        self.mode = mode
        self.label = label
        self.origin = screen_geometry.topLeft()
        self.setGeometry(screen_geometry)
        self.windows = [w for w in (windows or [])]
        self.start = None
        self.rect_sel = current.translated(-self.origin) if current and mode == "region" else QRect()
        self.hover = QRect()
        from ..platform.hyprland import is_hyprland

        if is_hyprland():
            # no Hyprland, uma janela em tela cheia esconde as de trás (mesmo transparente): flutua do tamanho do monitor;
            # cada painel leva o nome do monitor no título para nascer nele (ver open_on_screen)
            from PySide6.QtGui import QGuiApplication

            from ..platform.hyprland import open_on_screen, settle

            sc = QGuiApplication.screenAt(screen_geometry.center())
            self.setWindowTitle(f"Selecionar área — GCP Capture Studio [{sc.name() if sc else ''}]")
            self.setGeometry(screen_geometry)
            open_on_screen(self, screen_geometry)
            self.show()
            settle(self, screen_geometry)
        else:
            self.showFullScreen()
        self.setGeometry(screen_geometry)
        self.raise_()
        if focus:
            self.activateWindow()
            self.setFocus()

    def clear_selection(self) -> None:
        self.start = None
        self.rect_sel = QRect()
        self.update()

    def _window_at(self, pos: QPoint) -> QRect:
        g = pos + self.origin
        best = QRect()
        for w in self.windows:
            r = QRect(w["x"], w["y"], w["w"], w["h"])
            if r.contains(g) and (best.isNull() or w.get("active") or r.width() * r.height() < best.width() * best.height()):
                best = r
                if w.get("active"):
                    break
        return best.translated(-self.origin).intersected(self.rect()) if not best.isNull() else QRect()

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.RightButton:
            self._cancel()
            return
        if self.mode == "window":
            r = self._window_at(ev.position().toPoint())
            if not r.isNull():
                self._finish(r)
            return
        self.start = ev.position().toPoint()
        self.rect_sel = QRect(self.start, self.start)
        self.began.emit(self)
        self.update()

    def mouseMoveEvent(self, ev) -> None:
        pos = ev.position().toPoint()
        if self.mode == "window":
            self.hover = self._window_at(pos)
        elif self.start is not None:
            self.rect_sel = QRect(self.start, pos).normalized().intersected(self.rect())
        self.update()

    def mouseReleaseEvent(self, ev) -> None:
        if self.mode == "region" and self.start is not None:
            self.start = None
            if self.rect_sel.width() >= 64 and self.rect_sel.height() >= 64:
                self._finish(self.rect_sel)
            else:
                self.rect_sel = QRect()
                self.update()

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key_Escape:
            self._cancel()
        elif ev.key() in (Qt.Key_Return, Qt.Key_Enter) and not self.rect_sel.isNull():
            self._finish(self.rect_sel)

    def _finish(self, r: QRect) -> None:
        self.hide()
        self.selected.emit(r.translated(self.origin))

    def _cancel(self) -> None:
        self.hide()
        self.cancelled.emit()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        sel = self.hover if self.mode == "window" else self.rect_sel
        shade = QPainterPath()
        shade.addRect(QRectF(self.rect()))
        if not sel.isNull():
            hole = QPainterPath()
            hole.addRect(QRectF(sel))
            shade = shade.subtracted(hole)
        p.fillPath(shade, QColor(6, 10, 18, 150))
        f = QFont()
        f.setPixelSize(14)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        if not sel.isNull():
            p.setPen(QPen(QColor(theme.ACCENT), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(sel)
            tag = f"{sel.width()} × {sel.height()}"
            tw = p.fontMetrics().horizontalAdvance(tag) + 18
            ty = sel.top() - 30 if sel.top() > 36 else sel.top() + 8
            box = QRectF(sel.left(), ty, tw, 24)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.ACCENT))
            p.drawRoundedRect(box, 6, 6)
            p.setPen(QColor("#08202e"))
            p.drawText(box, Qt.AlignCenter, tag)
        hint = (
            "Clique na janela que deseja gravar  ·  Esc ou botão direito cancela"
            if self.mode == "window"
            else "Arraste para escolher a área de gravação  ·  Esc ou botão direito cancela"
        )
        f.setPixelSize(15)
        p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(hint) + 36
        box = QRectF((self.width() - tw) / 2, 28, tw, 40)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor(14, 21, 34, 235))
        p.drawRoundedRect(box, 12, 12)
        p.setPen(QColor(theme.TEXT))
        p.drawText(box, Qt.AlignCenter, hint)
        if self.label:
            f.setPixelSize(13)
            p.setFont(f)
            tw = p.fontMetrics().horizontalAdvance(self.label) + 28
            tag = QRectF((self.width() - tw) / 2, 76, tw, 28)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.ACCENT))
            p.drawRoundedRect(tag, 9, 9)
            p.setPen(QColor("#08202e"))
            p.drawText(tag, Qt.AlignCenter, self.label)


class RegionSelector(QObject):
    """Seleção de área em todos os monitores ao mesmo tempo: cada monitor recebe uma camada identificada
    com o seu nome, e a área pode ser marcada em qualquer um deles."""

    selected = Signal(QRect)  # coordenadas globais
    cancelled = Signal()

    def __init__(self):
        super().__init__()
        self.panes: list[_SelectorPane] = []

    def isVisible(self) -> bool:
        return any(p.isVisible() for p in self.panes)

    def begin(self, mode: str = "region", windows: list[dict] | None = None, current: QRect | None = None) -> None:
        self._close()
        screens = QGuiApplication.screens()
        under = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        for i, sc in enumerate(screens):
            pane = _SelectorPane()
            pane.selected.connect(self._done)
            pane.cancelled.connect(self._cancel)
            pane.began.connect(self._began)
            self.panes.append(pane)
        for i, (sc, pane) in enumerate(zip(screens, self.panes)):
            geo = sc.geometry()
            cur = current if current is not None and geo.contains(current.center()) else None
            pane.begin(geo, mode, windows, cur, screen_label(sc, i) if len(screens) > 1 else "", focus=sc is under)
        from ..platform import hyprland

        if hyprland.is_hyprland():
            # o seletor precisa ficar no topo da pilha do X para receber o mouse (ver raise_windows)
            QTimer.singleShot(120, lambda: self.isVisible() and hyprland.raise_windows(["Selecionar área"], "Selecionar área"))

    def _began(self, pane) -> None:
        for other in self.panes:
            if other is not pane:
                other.clear_selection()

    def _close(self) -> None:
        for pane in self.panes:
            pane.hide()
            pane.deleteLater()
        self.panes = []

    def _done(self, rect: QRect) -> None:
        self._close()
        self.selected.emit(rect)

    def _cancel(self) -> None:
        self._close()
        self.cancelled.emit()


def screen_at_cursor():
    return QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
