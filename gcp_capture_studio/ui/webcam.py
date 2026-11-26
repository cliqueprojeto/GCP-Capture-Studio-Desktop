"""Webcam flutuante: fica fixa onde for posicionada e entra no vídeo por estar sobre a tela gravada.

Formatos: círculo, oval, quadrado e retângulo 16:9. Arraste para mover, role o mouse sobre ela
para redimensionar e dê duplo clique para alternar o formato. Moldura com cor e espessura ajustáveis.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

try:
    from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices, QVideoSink

    HAVE_CAMERA = True
except Exception:  # noqa: BLE001
    HAVE_CAMERA = False

SHAPES = [("circle", "Círculo"), ("oval", "Oval"), ("square", "Quadrado"), ("wide", "Retângulo 16:9")]
_ASPECT = {"circle": 1.0, "oval": 0.78, "square": 1.0, "wide": 16 / 9}  # largura / altura


def cameras() -> list[str]:
    if not HAVE_CAMERA:
        return []
    return [d.description() for d in QMediaDevices.videoInputs()]


class WebcamBubble(QWidget):
    geometry_changed = Signal()

    def __init__(self, settings):
        from ..platform.hyprland import managed

        super().__init__(
            None,
            managed(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.X11BypassWindowManagerHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus),
        )
        self.settings = settings
        self.setWindowTitle("GCP Capture Studio — webcam")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setCursor(Qt.SizeAllCursor)
        self.setToolTip("Arraste para mover · role para redimensionar · duplo clique alterna o formato")
        self.image = None
        self.camera = None
        self.session = None
        self.sink = None
        self._device = None
        self._drag: QPoint | None = None

    # -- geometria ---------------------------------------------------------------
    def _size(self) -> QSize:
        base = int(self.settings.get("webcam.size", 240))
        aspect = _ASPECT.get(self.settings.get("webcam.shape"), 1.0)
        return QSize(int(base * aspect), base) if aspect <= 1 else QSize(int(base * aspect), base)

    def apply(self) -> None:
        """Aplica formato/tamanho/moldura mantendo o centro no lugar."""
        center = self.geometry().center()
        size = self._size()
        self.resize(size)
        if self.isVisible():
            self.move(center - QPoint(size.width() // 2, size.height() // 2))
        self.update()
        wanted = self.settings.get("webcam.device")
        if self.camera is not None and wanted != self._device:
            self._open_camera()

    def _open_camera(self) -> bool:
        if not HAVE_CAMERA or not QMediaDevices.videoInputs():
            return False
        if self.camera is not None:
            self.camera.stop()
        wanted = self.settings.get("webcam.device")
        device = next((d for d in QMediaDevices.videoInputs() if d.description() == wanted), QMediaDevices.defaultVideoInput())
        self._device = wanted
        self.camera = QCamera(device)
        self.session = QMediaCaptureSession()
        self.sink = QVideoSink()
        self.session.setCamera(self.camera)
        self.session.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self._frame)
        self.camera.start()
        return True

    def start(self, screen: QRect) -> bool:
        if self.isVisible() and self.camera is not None:
            self.apply()
            return True
        if not self._open_camera():
            return False
        size = self._size()
        self.resize(size)
        pos = self.settings.get("webcam.pos")
        if pos and screen.adjusted(-40, -40, 40, 40).contains(QPoint(pos[0] + size.width() // 2, pos[1] + size.height() // 2)):
            self.move(pos[0], pos[1])
        else:
            self.move(screen.right() - size.width() - 36, screen.bottom() - size.height() - 96)
        from ..platform.hyprland import open_on_screen

        open_on_screen(self)
        self.show()
        self.raise_()
        return True

    def stop(self) -> None:
        if self.camera:
            self.camera.stop()
        self.camera = self.session = self.sink = None
        self.image = None
        self.hide()

    def _frame(self, frame) -> None:
        img = frame.toImage()
        if not img.isNull():
            self.image = img.mirrored(True, False) if self.settings.get("webcam.mirror", True) else img
            self.update()

    # -- interação -----------------------------------------------------------------
    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, ev) -> None:
        if self._drag is not None and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _ev) -> None:
        if self._drag is not None:
            self._drag = None
            self.settings.set("webcam.pos", [self.x(), self.y()])

    def mouseDoubleClickEvent(self, _ev) -> None:
        keys = [k for k, _ in SHAPES]
        cur = self.settings.get("webcam.shape")
        self.settings.set("webcam.shape", keys[(keys.index(cur) + 1) % len(keys)] if cur in keys else "circle")

    def wheelEvent(self, ev) -> None:
        size = int(self.settings.get("webcam.size", 240))
        self.settings.set("webcam.size", max(120, min(640, size + (20 if ev.angleDelta().y() > 0 else -20))))

    def moveEvent(self, ev) -> None:
        super().moveEvent(ev)
        self.geometry_changed.emit()

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self.geometry_changed.emit()

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        self.geometry_changed.emit()

    def hideEvent(self, ev) -> None:
        super().hideEvent(ev)
        self.geometry_changed.emit()

    # -- pintura -------------------------------------------------------------------
    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        border = int(self.settings.get("webcam.border", 4))
        shape = self.settings.get("webcam.shape")
        pad = 3 + border / 2
        r = QRectF(self.rect()).adjusted(pad, pad, -pad, -pad)
        outline = QPainterPath()
        if shape in ("circle", "oval"):
            outline.addEllipse(r)
        else:
            outline.addRoundedRect(r, 14, 14)
        # sombra suave
        p.setPen(QPen(QColor(0, 0, 0, 70), border + 5))
        p.drawPath(outline)
        p.setClipPath(outline)
        if self.image is not None:
            iw, ih = self.image.width(), self.image.height()
            target = r.width() / r.height()
            if iw / ih > target:
                sw, sh = ih * target, ih
            else:
                sw, sh = iw, iw / target
            p.drawImage(r, self.image, QRectF((iw - sw) / 2, (ih - sh) / 2, sw, sh))
        else:
            p.fillRect(r, QColor(20, 28, 42))
            p.setPen(QColor("#93a3ba"))
            p.drawText(r, Qt.AlignCenter, "Abrindo webcam…")
        p.setClipping(False)
        if border > 0:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(self.settings.get("webcam.border_color", "#ffffff")), border))
            p.drawPath(outline)
