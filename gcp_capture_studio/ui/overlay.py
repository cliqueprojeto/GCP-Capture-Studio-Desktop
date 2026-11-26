"""Camada de anotações em tempo real: desenhos, texto, desfoque e efeitos do mouse.

Duas janelas transparentes cobrem a tela gravada:
- `_Canvas`: só exibe (cliques atravessam) — tudo que aparece aqui entra no vídeo;
- `_Catcher`: invisível, recebe o mouse apenas quando uma ferramenta de desenho está ativa.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QCursor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient, QRegion,
)
from PySide6.QtWidgets import QLineEdit, QWidget

from ..platform.hyprland import settle

LENS_TITLE = "GCP Capture Studio · lupa"  # mesmo prefixo da barra: fica fora do vídeo
FRAME_TITLE = "GCP Capture Studio · enquadramento do zoom"
PREVIEW_TITLE = "GCP Capture Studio · miniatura do zoom"
PRIVATE_WINDOWS = 3  # lupa, moldura do zoom e miniatura: todas fora do vídeo
DRAW_TOOLS = ("pen", "highlighter", "arrow", "line", "rect", "ellipse", "text", "blur")
TOOLS = ("cursor",) + DRAW_TOOLS

_OVERLAY_FLAGS = (
    Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.X11BypassWindowManagerHint | Qt.Tool
    | Qt.WindowDoesNotAcceptFocus
)


@dataclass
class Item:
    kind: str
    color: QColor
    width: float
    points: list[QPointF] = field(default_factory=list)
    text: str = ""
    size: int = 28
    pixmap: QPixmap | None = None

    def rect(self) -> QRectF:
        a, b = self.points[0], self.points[-1]
        return QRectF(a, b).normalized()


def _smooth_path(points: list[QPointF]) -> QPainterPath:
    path = QPainterPath(points[0])
    if len(points) < 3:
        for p in points[1:]:
            path.lineTo(p)
        if len(points) == 1:
            path.lineTo(points[0] + QPointF(0.01, 0.01))
        return path
    for i in range(1, len(points) - 1):
        mid = (points[i] + points[i + 1]) / 2
        path.quadTo(points[i], mid)
    path.lineTo(points[-1])
    return path


def paint_item(p: QPainter, it: Item) -> None:
    p.setRenderHint(QPainter.Antialiasing)
    if it.kind in ("pen", "highlighter"):
        color = QColor(it.color)
        width = it.width
        if it.kind == "highlighter":
            color.setAlphaF(0.38)
            width = it.width * 3.2
        pen = QPen(color, width, Qt.SolidLine, Qt.RoundCap if it.kind == "pen" else Qt.FlatCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(_smooth_path(it.points))
    elif it.kind in ("line", "arrow"):
        a, b = it.points[0], it.points[-1]
        pen = QPen(it.color, it.width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        if it.kind == "line":
            p.drawLine(a, b)
            return
        ang = math.atan2(b.y() - a.y(), b.x() - a.x())
        head = max(14.0, it.width * 3.6)
        length = math.hypot(b.x() - a.x(), b.y() - a.y())
        head = min(head, max(6.0, length * 0.6))
        base = QPointF(b.x() - head * 0.82 * math.cos(ang), b.y() - head * 0.82 * math.sin(ang))
        p.drawLine(a, base)
        left = QPointF(b.x() - head * math.cos(ang - 0.45), b.y() - head * math.sin(ang - 0.45))
        right = QPointF(b.x() - head * math.cos(ang + 0.45), b.y() - head * math.sin(ang + 0.45))
        tri = QPainterPath(b)
        tri.lineTo(left)
        tri.lineTo(right)
        tri.closeSubpath()
        p.setPen(QPen(it.color, 1.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(it.color)
        p.drawPath(tri)
    elif it.kind == "rect":
        p.setPen(QPen(it.color, it.width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(it.rect(), 4, 4)
    elif it.kind == "ellipse":
        p.setPen(QPen(it.color, it.width))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(it.rect())
    elif it.kind == "text":
        font = QFont()
        font.setPixelSize(it.size)
        font.setWeight(QFont.DemiBold)
        path = QPainterPath()
        path.addText(it.points[0], font, it.text)
        p.setPen(QPen(QColor(0, 0, 0, 120), max(2.0, it.size / 12), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(it.color)
        p.drawPath(path)
    elif it.kind == "blur":
        r = it.rect()
        if it.pixmap is not None:
            clip = QPainterPath()
            clip.addRoundedRect(r, 6, 6)
            p.save()
            p.setClipPath(clip)
            p.drawPixmap(r, it.pixmap, QRectF(it.pixmap.rect()))
            p.restore()
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(120, 130, 145, 245))
            p.drawRoundedRect(r, 6, 6)


class _Canvas(QWidget):
    def __init__(self, owner: "AnnotationOverlay"):
        from ..platform.hyprland import managed

        super().__init__(None, managed(_OVERLAY_FLAGS | Qt.WindowTransparentForInput))
        self.owner = owner
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowTitle("GCP Capture Studio — anotações")

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        self.owner.paint(p, self.rect())
        p.end()


class _Catcher(QWidget):
    def __init__(self, owner: "AnnotationOverlay"):
        from ..platform.hyprland import managed

        super().__init__(None, managed(_OVERLAY_FLAGS))
        self.owner = owner
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setWindowTitle("GCP Capture Studio — entrada")

    def paintEvent(self, _ev) -> None:
        # alfa mínimo: invisível no vídeo, mas garante que o compositor entregue o mouse
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 1))
        p.end()

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self.owner.press(ev.position())
        elif ev.button() == Qt.RightButton:
            self.owner.set_tool("cursor")

    def mouseMoveEvent(self, ev) -> None:
        self.owner.native_move(ev.position())
        if ev.buttons() & Qt.LeftButton:
            self.owner.drag(ev.position(), bool(ev.modifiers() & Qt.ShiftModifier))

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self.owner.release(ev.position())


class _LensWindow(QWidget):
    """Lupa vista na tela. É uma janela à parte, mantida fora do vídeo pelo compositor: assim os quadros
    capturados nunca contêm a própria lupa e o conteúdo ampliado é sempre o real, ao vivo.
    No vídeo, a lupa é composta pelo motor de gravação na mesma posição."""

    def __init__(self, owner: "AnnotationOverlay"):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput,
        )
        self.owner = owner
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowTitle(LENS_TITLE)
        self.resize(240, 240)

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        self.owner.paint_lens(p, QPointF(self.width() / 2, self.height() / 2))
        p.end()


class _ZoomFrame(QWidget):
    """Moldura que mostra, sobre a tela real, a área que o vídeo está enquadrando com o zoom.
    Fica fora do vídeo (mesmo mecanismo da barra) e não recebe cliques."""

    def __init__(self, owner: "AnnotationOverlay"):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput,
        )
        self.owner = owner
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowTitle(FRAME_TITLE)
        self.view = QRectF()

    def set_view(self, view: QRectF) -> None:
        if view == self.view:
            return
        old, self.view = self.view, view
        region = QRegion()
        for r in (old, view):
            if not r.isNull():
                outer = r.adjusted(-8, -8, 8, 8).toAlignedRect()
                region += QRegion(outer) - QRegion(r.adjusted(26, 26, -26, -26).toAlignedRect())
        self.update(region)

    def paintEvent(self, _ev) -> None:
        if self.view.isNull():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.view.adjusted(1, 1, -1, -1)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 110), 4))
        p.drawRoundedRect(r, 6, 6)
        p.setPen(QPen(QColor(99, 193, 238, 235), 2))
        p.drawRoundedRect(r, 6, 6)
        # cantos reforçados, para a moldura ser lida de relance
        p.setPen(QPen(QColor("#63c1ee"), 4, Qt.SolidLine, Qt.RoundCap))
        n = min(22.0, r.width() / 4, r.height() / 4)
        for cx, cy, sx, sy in ((r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1), (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1)):
            p.drawLine(QPointF(cx, cy), QPointF(cx + sx * n, cy))
            p.drawLine(QPointF(cx, cy), QPointF(cx, cy + sy * n))
        p.end()


class _ZoomPreview(QWidget):
    """Miniatura ao vivo do vídeo com zoom, como está sendo gravado. Fora do vídeo; arraste para mover."""

    geometry_changed = Signal()

    def __init__(self, owner: "AnnotationOverlay"):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.owner = owner
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle(PREVIEW_TITLE)
        self.setCursor(Qt.SizeAllCursor)
        self._drag: QPoint | None = None
        self.shown = False

    def set_shown(self, on: bool) -> None:
        if on == self.shown:
            return
        self.shown = on
        if on:
            self.clearMask()
        else:
            self.setMask(QRegion(0, 0, 1, 1))
        self.geometry_changed.emit()

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, ev) -> None:
        if self._drag is not None and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _ev) -> None:
        if self._drag is not None:
            self._drag = None
            self.owner.settings.set("effects.zoom_preview_pos", [self.x(), self.y()])

    def moveEvent(self, ev) -> None:
        super().moveEvent(ev)
        self.geometry_changed.emit()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        clip = QPainterPath()
        clip.addRoundedRect(r, 10, 10)
        p.save()
        p.setClipPath(clip)
        p.fillRect(r, QColor(13, 20, 33))
        frame = self.owner.recorder.latest_frame()
        z, vx, vy = self.owner.recorder.view_transform()
        if frame is not None:
            p.drawImage(r, frame, QRectF(vx, vy, frame.width() / z, frame.height() / z))
        p.restore()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 120), 4))
        p.drawRoundedRect(r, 10, 10)
        p.setPen(QPen(QColor("#63c1ee"), 2))
        p.drawRoundedRect(r, 10, 10)
        f = QFont()
        f.setPixelSize(11)
        f.setWeight(QFont.Bold)
        p.setFont(f)
        tag = f"ZOOM {z:.1f}×"
        tw = p.fontMetrics().horizontalAdvance(tag) + 14
        box = QRectF(r.left() + 8, r.top() + 8, tw, 20)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(8, 14, 24, 215))
        p.drawRoundedRect(box, 6, 6)
        p.setPen(QColor("#63c1ee"))
        p.drawText(box, Qt.AlignCenter, tag)
        p.end()


class _TextEntry(QLineEdit):
    """Campo flutuante para digitar o texto ao vivo (aparece no vídeo enquanto digita)."""

    committed = Signal(str)

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("Texto — GCP Capture Studio")
        self.setPlaceholderText("Digite e tecle Enter")
        self.returnPressed.connect(self._commit)
        self._done = False

    def begin(self, global_pos: QPoint, color: QColor, size: int) -> None:
        self._done = False
        self.clear()
        self.setStyleSheet(
            f"QLineEdit {{ background: rgba(10,16,27,0.55); border: none; border-bottom: 2px dashed {color.name()};"
            f" border-radius: 4px; color: {color.name()}; font-size: {size}px; font-weight: 600; padding: 2px 6px; }}"
        )
        self.resize(max(360, size * 14), size + 22)
        self.move(global_pos - QPoint(6, self.height() - 10))
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.OtherFocusReason)

    def text_origin(self) -> QPoint:
        """Posição global da linha de base do texto."""
        return self.pos() + QPoint(6, self.height() - 12)

    def _commit(self) -> None:
        if self._done:
            return
        self._done = True
        text = self.text().strip()
        self.hide()
        self.committed.emit(text)

    def finish(self) -> None:
        if self.isVisible():
            self._commit()

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key_Escape:
            self._done = True
            self.hide()
            self.committed.emit("")
            return
        super().keyPressEvent(ev)

    def focusOutEvent(self, ev) -> None:
        super().focusOutEvent(ev)
        QTimer.singleShot(0, self.finish)


class AnnotationOverlay(QObject):
    tool_changed = Signal(str)
    history_changed = Signal()

    def __init__(self, settings, recorder, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.recorder = recorder
        self.canvas = _Canvas(self)
        self.catcher = _Catcher(self)
        self.entry = _TextEntry()
        self.entry.committed.connect(self._text_done)
        self.tool = "cursor"
        self.items: list[Item] = []
        self.redo_stack: list[Item] = []
        self.live: Item | None = None
        self.layer: QPixmap | None = None
        self.origin = QPoint(0, 0)  # canto da tela coberta (coordenadas globais)
        self._screen_rect = QRect()
        self.capture = QRect()  # área gravada, relativa à janela
        self.frame_scale = 1.0
        self.pointer = QPointF(-1000, -1000)
        self.has_global_pointer = False
        self.ripples: list[tuple[QPointF, float, str]] = []
        self.lenswin = _LensWindow(self)
        self.zoomframe = _ZoomFrame(self)
        self.zoomview = _ZoomPreview(self)
        self.lens_excluded = False  # o compositor mantém a janela da lupa fora do vídeo
        self.keycap: list | None = None  # [texto, instante ao pressionar, instante ao soltar]
        self._last_fx = QRect()
        self.active = False
        self.anim = QTimer(self)
        self.anim.setInterval(16)
        self.anim.timeout.connect(self._tick)
        self.lens_timer = QTimer(self)
        self.lens_timer.setInterval(30)
        self.lens_timer.timeout.connect(self._pull_lens)
        self.poll = QTimer(self)  # reserva (X11/Windows/macOS): posição via Qt
        self.poll.setInterval(16)
        self.poll.timeout.connect(lambda: self._set_pointer_global(QCursor.pos()))

    # -- ciclo de vida -------------------------------------------------------
    def show_on(self, screen_geometry: QRect, capture: QRect, frame_scale: float, global_pointer: bool) -> None:
        self.origin = screen_geometry.topLeft()
        self._screen_rect = QRect(screen_geometry)
        self.capture = capture
        self.frame_scale = frame_scale
        self.has_global_pointer = global_pointer
        for w in (self.canvas, self.catcher):
            w.setGeometry(screen_geometry)
        self.layer = None
        self.items.clear()
        self.redo_stack.clear()
        self.ripples.clear()
        self.active = True
        self.canvas.show()
        self.canvas.raise_()
        settle(self.canvas, screen_geometry)
        self.set_tool("cursor")
        if not global_pointer:
            self.poll.start()
        self.sync_effects()
        self.history_changed.emit()

    def hide(self) -> None:
        self.active = False
        self.anim.stop()
        self.lens_timer.stop()
        self.poll.stop()
        self.entry.hide()
        self.catcher.hide()
        self.canvas.hide()
        self.lenswin.hide()
        self.zoomframe.hide()
        self.zoomview.shown = False
        self.zoomview.hide()
        self.lens_excluded = False
        self.recorder.set_fx(None, None, 1.0)
        self.recorder.set_preview(False)

    def prepare_lens_window(self) -> None:
        """Mapeia a janela da lupa (invisível) para o compositor poder excluí-la da captura."""
        self.lenswin.setMask(QRegion(0, 0, 1, 1))
        self.lenswin.show()
        self.zoomframe.setMask(QRegion(0, 0, 1, 1))
        self.zoomframe.view = QRectF()
        self.zoomframe.show()
        self.zoomview.shown = False
        self.zoomview.setMask(QRegion(0, 0, 1, 1))
        self.zoomview.show()

    def place_private_windows(self, screen: QRect, capture: QRect) -> None:
        """Posiciona a moldura sobre a tela gravada e a miniatura no canto (ou onde o usuário a deixou)."""
        self.zoomframe.setGeometry(screen)
        settle(self.zoomframe, screen)
        w = int(self.settings.get("effects.zoom_preview_size", 320))
        h = max(90, round(w * capture.height() / max(1, capture.width())))
        self.zoomview.resize(w + 4, h + 4)
        pos = self.settings.get("effects.zoom_preview_pos")
        if pos and screen.contains(QPoint(pos[0] + w // 2, pos[1] + h // 2)):
            self.zoomview.move(pos[0], pos[1])
        else:
            self.zoomview.move(screen.right() - w - 28, screen.bottom() - h - 90)

    def set_lens_excluded(self, on: bool) -> None:
        self.lens_excluded = on
        self.sync_effects()

    def set_holes(self, rects: list[QRect]) -> None:
        """Abre "furos" na camada que captura o mouse para que barras e a webcam continuem clicáveis."""
        region = QRegion(self.catcher.rect())
        for r in rects:
            region -= QRegion(r.translated(-self.origin).adjusted(-2, -2, 2, 2))
        self.catcher.setMask(region)

    def raise_above(self, *widgets) -> None:
        """Mantém barras flutuantes acima da camada de captura do mouse."""
        for w in widgets:
            if w.isVisible():
                w.raise_()

    # -- ferramentas ---------------------------------------------------------
    def set_tool(self, tool: str) -> None:
        if tool not in TOOLS:
            return
        self.entry.finish()
        self.tool = tool
        if self.active:
            if tool == "cursor":
                self.catcher.hide()
            else:
                if not self._screen_rect.isNull():
                    self.catcher.setGeometry(self._screen_rect)
                self.catcher.show()
                settle(self.catcher, self._screen_rect)
                self.catcher.raise_()
            self._sync_preview()
        self.tool_changed.emit(tool)

    def _color(self) -> QColor:
        return QColor(self.settings.get("tools.color", "#ef4444"))

    def press(self, pos: QPointF) -> None:
        if self.entry.isVisible():
            self.entry.finish()
            return
        if self.tool == "text":
            self.entry.begin((pos + QPointF(self.origin)).toPoint(), self._color(), int(self.settings.get("tools.text_size", 28)))
            return
        self.live = Item(self.tool, self._color(), float(self.settings.get("tools.width", 5)), [pos, pos])
        self.canvas.update()

    def drag(self, pos: QPointF, constrain: bool = False) -> None:
        if not self.live:
            return
        if self.live.kind in ("pen", "highlighter"):
            last = self.live.points[-1]
            if constrain:
                first = self.live.points[0]
                pos = QPointF(pos.x(), first.y()) if abs(pos.x() - first.x()) > abs(pos.y() - first.y()) else QPointF(first.x(), pos.y())
                self.live.points = [first, pos]
            elif (pos - last).manhattanLength() >= 1.5:
                self.live.points.append(pos)
        else:
            a = self.live.points[0]
            if constrain and self.live.kind in ("rect", "ellipse", "blur"):
                side = max(abs(pos.x() - a.x()), abs(pos.y() - a.y()))
                pos = QPointF(a.x() + math.copysign(side, pos.x() - a.x()), a.y() + math.copysign(side, pos.y() - a.y()))
            elif constrain:
                ang = round(math.atan2(pos.y() - a.y(), pos.x() - a.x()) / (math.pi / 4)) * (math.pi / 4)
                dist = math.hypot(pos.x() - a.x(), pos.y() - a.y())
                pos = QPointF(a.x() + dist * math.cos(ang), a.y() + dist * math.sin(ang))
            self.live.points[-1] = pos
        self.canvas.update()

    def release(self, pos: QPointF) -> None:
        it, self.live = self.live, None
        if not it:
            return
        if it.kind not in ("pen", "highlighter"):
            a, b = it.points[0], it.points[-1]
            if abs(a.x() - b.x()) < 3 and abs(a.y() - b.y()) < 3:
                self.canvas.update()
                return
        if it.kind == "blur":
            it.pixmap = self._blurred(it.rect())
        self._commit(it)

    def _text_done(self, text: str) -> None:
        if text:
            origin = QPointF(self.entry.text_origin() - self.origin)
            self._commit(Item("text", self._color(), 0, [origin], text, int(self.settings.get("tools.text_size", 28))))

    def _commit(self, it: Item) -> None:
        self.items.append(it)
        self.redo_stack.clear()
        self._ensure_layer()
        p = QPainter(self.layer)
        paint_item(p, it)
        p.end()
        self.canvas.update()
        self.history_changed.emit()

    def _ensure_layer(self) -> None:
        if self.layer is None or self.layer.size() != self.canvas.size() * self.canvas.devicePixelRatioF():
            dpr = self.canvas.devicePixelRatioF()
            self.layer = QPixmap(self.canvas.size() * dpr)
            self.layer.setDevicePixelRatio(dpr)
            self._rebuild()

    def _rebuild(self) -> None:
        if self.layer is None:
            return
        self.layer.fill(Qt.transparent)
        p = QPainter(self.layer)
        for it in self.items:
            paint_item(p, it)
        p.end()
        self.canvas.update()

    def undo(self) -> None:
        if self.items:
            self.redo_stack.append(self.items.pop())
            self._rebuild()
            self.history_changed.emit()

    def redo(self) -> None:
        if self.redo_stack:
            self.items.append(self.redo_stack.pop())
            self._rebuild()
            self.history_changed.emit()

    def clear(self) -> None:
        if self.items:
            self.items.clear()
            self.redo_stack.clear()
            self._rebuild()
            self.history_changed.emit()

    # -- desfoque ------------------------------------------------------------
    def _blurred(self, rect: QRectF) -> QPixmap | None:
        frame = self.recorder.grab_frame()
        if frame is None:
            return None
        s = self.frame_scale
        src = QRectF((rect.x() - self.capture.x()) * s, (rect.y() - self.capture.y()) * s, rect.width() * s, rect.height() * s)
        src = src.toRect().intersected(frame.rect())
        if src.width() < 4 or src.height() < 4:
            return None
        k = max(4, int(self.settings.get("tools.blur_strength", 14)))
        crop = frame.copy(src)
        small = crop.scaled(max(2, src.width() // k), max(2, src.height() // k), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        small = small.scaled(max(2, small.width() // 2), max(2, small.height() // 2), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        return QPixmap.fromImage(small.scaled(src.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation))

    # -- efeitos do mouse ----------------------------------------------------
    def fx(self, name: str):
        return self.settings.get(f"effects.{name}")

    def sync_effects(self) -> None:
        if not self.active:
            return
        self._sync_preview()
        if self._lens_local() or self.fx("zoom"):
            self.lens_timer.start()
        elif not self._zoom_visible():
            self.lens_timer.stop()
        self._sync_lens()
        self._sync_zoom_windows()
        self.canvas.update()

    def _lens_on_screen(self) -> bool:
        """Lupa em janela própria, fora do vídeo (o vídeo recebe a lupa pelo motor de gravação)."""
        return bool(self.fx("magnifier")) and self.lens_excluded and self.recorder.lens_in_video

    def _lens_in_canvas(self) -> bool:
        """Reserva sem composição no vídeo: a lupa é desenhada na camada de anotações."""
        return bool(self.fx("magnifier")) and not self.recorder.lens_in_video

    def _lens_local(self) -> bool:
        return self._lens_on_screen() or self._lens_in_canvas()

    def _sync_preview(self) -> None:
        self.recorder.set_preview(self.active and (self.tool == "blur" or self._lens_local() or self._zoom_preview_on()))

    def _zoom_preview_on(self) -> bool:
        return bool(self.fx("zoom")) and bool(self.fx("zoom_preview")) and self.lens_excluded and self.recorder.lens_in_video

    def _zoom_visible(self) -> bool:
        """O zoom está ligado ou ainda terminando a animação de saída."""
        return bool(self.fx("zoom")) or self.recorder.view_transform()[0] > 1.002

    def _sync_zoom_windows(self) -> None:
        """Moldura (área enquadrada) e miniatura ao vivo do zoom — só quando ficam fora do vídeo."""
        usable = self.active and self.lens_excluded and self.recorder.lens_in_video
        z, vx, vy = self.recorder.view_transform()
        zooming = usable and z > 1.002
        fr = self.zoomframe
        if zooming and self.fx("zoom_frame"):
            s = self.frame_scale
            fw, fh = self.recorder.source.out_size()
            fr.clearMask()
            fr.set_view(QRectF(self.capture.x() + vx / s, self.capture.y() + vy / s, fw / z / s, fh / z / s))
        elif not fr.view.isNull():
            fr.set_view(QRectF())
            fr.setMask(QRegion(0, 0, 1, 1))
        pv = self.zoomview
        show = usable and self._zoom_preview_on()
        pv.set_shown(show)
        if show:
            pv.update()
        self._sync_preview()

    def _sync_lens(self) -> None:
        """Atualiza a lupa do vídeo e a janela da lupa para a posição atual do ponteiro."""
        inside = self.active and QRectF(self.capture).contains(self.pointer)
        on = inside and bool(self.fx("magnifier"))
        rad = float(self.fx("magnifier_size")) / 2
        s = self.frame_scale
        zoom = float(self.fx("zoom_level") or 2.0) if (self.active and self.fx("zoom")) else 1.0
        if self.recorder.lens_in_video:
            ptr = ((self.pointer.x() - self.capture.x()) * s, (self.pointer.y() - self.capture.y()) * s) if inside else None
            self.recorder.set_fx(ptr, (rad * s, float(self.fx("magnifier_zoom")), s) if on else None, zoom)
        w = self.lenswin
        if on and self._lens_on_screen():
            side = int(2 * rad) + 16
            if w.width() != side:
                w.resize(side, side)
            w.move((self.pointer + QPointF(self.origin) - QPointF(side / 2, side / 2)).toPoint())
            w.clearMask()
            if not w.isVisible():
                w.show()
            w.update()
        elif w.isVisible():
            w.setMask(QRegion(0, 0, 1, 1))

    def set_pointer(self, global_pos: QPoint) -> None:
        """Posição global vinda do compositor (KWin)."""
        self._set_pointer_global(global_pos)

    def native_move(self, local: QPointF) -> None:
        if not self.has_global_pointer:
            self._move_pointer(local)

    def _set_pointer_global(self, global_pos: QPoint) -> None:
        self._move_pointer(QPointF(global_pos - self.origin))

    def _move_pointer(self, local: QPointF) -> None:
        if local == self.pointer:
            return
        self.pointer = local
        if not self.active:
            return
        if self.fx("magnifier") or self.fx("zoom"):
            self._sync_lens()
        if self.fx("spotlight"):
            self.canvas.update()
        elif self.fx("highlight") or self._lens_in_canvas():
            self._update_fx()

    def click(self, button: str) -> None:
        if not (self.active and self.fx("click")):
            return
        if not self.canvas.rect().contains(self.pointer.toPoint()):
            return
        self.ripples.append((QPointF(self.pointer), time.monotonic(), button))
        if not self.anim.isActive():
            self.anim.start()

    def _tick(self) -> None:
        now = time.monotonic()
        self.ripples = [r for r in self.ripples if now - r[1] < 0.5]
        self._update_fx(extra=True)
        if self.keycap:
            self.canvas.update(self._keys_rect())
            if not self._keys_alive(now):
                self.keycap = None
        if not self.ripples and not self.keycap:
            self.anim.stop()

    def _fx_rect(self) -> QRect:
        r = QRectF()
        pt = self.pointer
        if self.fx("highlight"):
            s = float(self.fx("highlight_size")) + 4
            r = r.united(QRectF(pt.x() - s, pt.y() - s, 2 * s, 2 * s))
        if self._lens_in_canvas():
            c, rad = self._lens_center()
            rad += 8
            r = r.united(QRectF(c.x() - rad, c.y() - rad, 2 * rad, 2 * rad))
        for pos, _t, _b in self.ripples:
            s = float(self.fx("click_size")) + 6
            r = r.united(QRectF(pos.x() - s, pos.y() - s, 2 * s, 2 * s))
        return r.toAlignedRect()

    def _update_fx(self, extra: bool = False) -> None:
        if self.fx("spotlight"):
            self.canvas.update()
            return
        new = self._fx_rect()
        self.canvas.update(new.united(self._last_fx))
        self._last_fx = new

    def _lens_center(self) -> tuple[QPointF, float]:
        """A lupa fica centralizada exatamente no ponteiro."""
        return QPointF(self.pointer), float(self.fx("magnifier_size")) / 2

    def _pull_lens(self) -> None:
        """Busca o quadro mais recente e redesenha a lupa."""
        self.recorder.latest_frame()
        self._sync_zoom_windows()
        if not (self._lens_local() or self._zoom_visible()):
            self.lens_timer.stop()
        if self._lens_on_screen():
            self.lenswin.update()
        elif self._lens_in_canvas():
            self._update_fx()

    def show_keys(self, text: str, held: bool = True) -> None:
        """Exibe uma combinação de teclas: visível enquanto pressionada, some suavemente depois."""
        if not (self.active and self.fx("keys")):
            return
        now = time.monotonic()
        self.keycap = [text, now, None if held else now]
        if not self.anim.isActive():
            self.anim.start()
        self.canvas.update(self._keys_rect())

    def release_keys(self) -> None:
        if self.keycap and self.keycap[2] is None:
            self.keycap[2] = time.monotonic()

    _KEY_FADE = 0.45

    def _keys_alive(self, now: float) -> bool:
        if not self.keycap:
            return False
        _text, t0, t_rel = self.keycap
        if t_rel is None:
            if now - t0 < 8.0:
                return True
            self.keycap[2] = t_rel = now  # tecla presa/soltura não detectada
        return now - t_rel < float(self.fx("keys_duration")) + self._KEY_FADE

    def _keys_rect(self) -> QRect:
        h = int(int(self.fx("keys_size")) * 3.4) + 60
        c = self.capture if not self.capture.isNull() else self.canvas.rect()
        return QRect(c.x(), c.bottom() - h - 50, c.width(), h + 30)

    def _paint_keys(self, p: QPainter) -> None:
        now = time.monotonic()
        if not self._keys_alive(now):
            return
        text, t0, t_rel = self.keycap
        appear = min(1.0, (now - t0) / 0.16)
        ease = 1 - (1 - appear) ** 3
        alpha = ease
        if t_rel is not None:
            gone = now - t_rel - float(self.fx("keys_duration"))
            if gone > 0:
                k = min(1.0, gone / self._KEY_FADE)
                alpha = (1 - k) ** 2  # saída suave
        size = int(self.fx("keys_size"))
        style, anim = self.fx("keys_style"), self.fx("keys_anim")
        font = QFont()
        font.setPixelSize(size)
        font.setWeight(QFont.Bold)
        p.setFont(font)
        fm = p.fontMetrics()
        parts = text.split(" + ")
        keycap = style == "keycap"
        pad = size * (0.75 if keycap else 0.62)
        gap = size * (0.62 if keycap else 0.38)
        plus = fm.horizontalAdvance("+")
        face_h = size * 1.75
        skirt = size * 0.62 if keycap else 0.0  # "saia" da tecla em relevo
        side = size * 0.3 if keycap else 0.0
        widths = [max(fm.horizontalAdvance(k) + 2 * pad, size * 2.1) + 2 * side for k in parts]
        key_h = face_h + skirt + (size * 0.14 if keycap else 0)
        total = sum(widths) + (len(parts) - 1) * (plus + 2 * gap)
        area = self._keys_rect()
        box = QRectF(area.center().x() - total / 2 - pad, area.bottom() - key_h - 2 * pad - 6, total + 2 * pad, key_h + 2 * pad)
        p.save()
        p.setOpacity(max(0.0, min(1.0, alpha if anim != "pop" else max(alpha, 0.0))))
        if anim == "pop":
            scale = 0.8 + 0.2 * ease + (0.06 * (1 - abs(2 * appear - 1)) if appear < 1 else 0)
            p.translate(box.center())
            p.scale(scale, scale)
            p.translate(-box.center())
        elif anim == "slide":
            p.translate(0, (1 - ease) * size * 1.4)
        if not keycap:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(10, 16, 27, 225))
            p.drawRoundedRect(box, size * 0.7, size * 0.7)
        x, y = box.x() + pad, box.y() + pad
        lw = max(2.5, size * 0.11)
        ink = QColor("#0b0b0c")
        for i, (k, w) in enumerate(zip(parts, widths)):
            last = i == len(parts) - 1
            cap = QRectF(x, y, w, key_h)
            if keycap:
                r_out = size * 0.34
                # sombra, corpo e face superior com as arestas do relevo
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, 70))
                p.drawRoundedRect(cap.translated(0, size * 0.14), r_out, r_out)
                p.setPen(QPen(ink, lw, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.setBrush(QColor("#ffffff"))
                p.drawRoundedRect(cap, r_out, r_out)
                face = QRectF(cap.x() + side, cap.y() + size * 0.14, cap.width() - 2 * side, face_h)
                r_in = size * 0.24
                p.drawLine(QPointF(face.left() + r_in * 0.3, face.bottom() - r_in * 0.3), QPointF(cap.left() + r_out * 0.3, cap.bottom() - r_out * 0.3))
                p.drawLine(QPointF(face.right() - r_in * 0.3, face.bottom() - r_in * 0.3), QPointF(cap.right() - r_out * 0.3, cap.bottom() - r_out * 0.3))
                p.drawRoundedRect(face, r_in, r_in)
                p.setPen(ink)
                p.drawText(face, Qt.AlignCenter, k)
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, 120))
                p.drawRoundedRect(cap.translated(0, size * 0.12), size * 0.36, size * 0.36)
                p.setBrush(QColor("#63c1ee") if last else QColor("#e9eff8"))
                p.drawRoundedRect(cap, size * 0.36, size * 0.36)
                p.setPen(QColor("#08202e"))
                p.drawText(cap, Qt.AlignCenter, k)
            x += w
            if not last:
                seg = QRectF(x, y, plus + 2 * gap, key_h)
                if keycap:
                    big = QFont(font)
                    big.setPixelSize(int(size * 1.5))
                    bw = plus * 1.5
                    path = QPainterPath()
                    path.addText(seg.center().x() - bw / 2, seg.y() + face_h / 2 + size * 0.62, big, "+")
                    p.setPen(QPen(QColor(255, 255, 255, 230), lw * 1.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                    p.setBrush(Qt.NoBrush)
                    p.drawPath(path)
                    p.setPen(Qt.NoPen)
                    p.setBrush(ink)
                    p.drawPath(path)
                else:
                    p.setPen(QColor("#93a3ba"))
                    p.drawText(seg, Qt.AlignCenter, "+")
                x += plus + 2 * gap
        p.restore()

    # -- pintura -------------------------------------------------------------
    def paint(self, p: QPainter, _rect: QRect) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if self.fx("spotlight"):
            self._paint_spotlight(p)
        if self.layer is not None:
            p.drawPixmap(0, 0, self.layer)
        if self.live is not None:
            if self.live.kind == "blur":
                p.setPen(QPen(QColor(255, 255, 255, 220), 1.5, Qt.DashLine))
                p.setBrush(QColor(120, 130, 145, 110))
                p.drawRoundedRect(self.live.rect(), 6, 6)
            else:
                paint_item(p, self.live)
        if self.fx("highlight"):
            color = QColor(self.fx("highlight_color"))
            color.setAlphaF(float(self.fx("highlight_opacity")) / 100.0)
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            s = float(self.fx("highlight_size"))
            p.drawEllipse(self.pointer, s, s)
        now = time.monotonic()
        for pos, t0, button in self.ripples:
            k = min(1.0, (now - t0) / 0.5)
            ease = 1 - (1 - k) ** 3
            color = QColor(self.fx("click_right_color") if button == "right" else self.fx("click_color"))
            size = float(self.fx("click_size"))
            ring = QColor(color)
            ring.setAlphaF(max(0.0, 1.0 - k))
            p.setPen(QPen(ring, 3.0))
            fill = QColor(color)
            fill.setAlphaF(max(0.0, 0.28 * (1.0 - k)))
            p.setBrush(fill)
            rad = 6 + (size - 6) * ease
            p.drawEllipse(pos, rad, rad)
        if self._lens_in_canvas():
            self.paint_lens(p, QPointF(self.pointer))
        self._paint_keys(p)
        self._paint_frame(p)

    def _paint_spotlight(self, p: QPainter) -> None:
        dim = int(255 * float(self.fx("spotlight_dim")) / 100.0)
        rad = float(self.fx("spotlight_size"))
        grad = QRadialGradient(self.pointer, rad)
        grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        grad.setColorAt(0.78, QColor(0, 0, 0, 0))
        grad.setColorAt(1.0, QColor(0, 0, 0, dim))
        p.fillRect(self.canvas.rect(), QBrush(grad))

    def paint_lens(self, p: QPainter, center: QPointF) -> None:
        """Desenha a lupa centrada em `center`, ampliando exatamente o ponto sob o ponteiro."""
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        rad = float(self.fx("magnifier_size")) / 2
        frame = self.recorder.latest_frame()
        if frame is not None:
            s = self.frame_scale
            src = rad / float(self.fx("magnifier_zoom")) * s
            px, py = (self.pointer.x() - self.capture.x()) * s, (self.pointer.y() - self.capture.y()) * s
            clip = QPainterPath()
            clip.addEllipse(center, rad, rad)
            p.save()
            p.setClipPath(clip)
            p.fillRect(QRectF(center.x() - rad, center.y() - rad, 2 * rad, 2 * rad), QColor(13, 20, 33))
            p.drawImage(QRectF(center.x() - rad, center.y() - rad, 2 * rad, 2 * rad), frame, QRectF(px - src, py - src, 2 * src, 2 * src))
            p.restore()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 90), 6))
        p.drawEllipse(center, rad + 1, rad + 1)
        p.setPen(QPen(QColor("#ffffff"), 2.5))
        p.drawEllipse(center, rad, rad)

    def _paint_frame(self, p: QPainter) -> None:
        """Moldura da região gravada, desenhada por fora (não entra no vídeo)."""
        if self.capture.isNull() or self.capture == self.canvas.rect():
            return
        r = QRectF(self.capture).adjusted(-3, -3, 3, 3)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 120), 4))
        p.drawRect(r)
        p.setPen(QPen(QColor("#63c1ee"), 2, Qt.DashLine))
        p.drawRect(r)
