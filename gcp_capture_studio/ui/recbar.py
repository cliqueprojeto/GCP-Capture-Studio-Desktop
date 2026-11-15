"""Barra de gravação: tempo, áudio, pausa/parar e ferramentas de anotação em tempo real."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QRegion
from PySide6.QtWidgets import QButtonGroup, QColorDialog, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from .. import theme
from ..config import SHORTCUT_ACTIONS
from .widgets import LevelMeter, Swatch, tool_button, vline

PALETTE = ["#ef4444", "#f59e0b", "#facc15", "#34d399", "#63c1ee", "#7c5cff", "#ffffff", "#0b0f19"]
HIDDEN_PREFIX = "GCP Capture Studio ·"  # janelas com este título ficam fora do vídeo

TOOL_DEFS = [
    ("cursor", "cursor"), ("pen", "pen"), ("highlighter", "highlighter"), ("arrow", "arrow"), ("line", "line"),
    ("rect", "rect"), ("ellipse", "ellipse"), ("text", "text"), ("blur", "blur"),
]
FX_DEFS = [("click", "click"), ("highlight", "highlight"), ("spotlight", "spotlight"), ("magnifier", "magnifier"), ("zoom", "zoom"), ("keys", "keyboard")]


class RecBar(QWidget):
    pause_toggled = Signal()
    stop = Signal()
    discard = Signal()
    tool = Signal(str)
    undo = Signal()
    redo = Signal()
    clear = Signal()
    hide_requested = Signal()
    geometry_changed = Signal()
    expanded_changed = Signal(bool)
    dragged = Signal()

    def __init__(self, settings):
        super().__init__(
            None,
            # janela gerenciada: o compositor consegue mantê-la visível na tela e fora do vídeo
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus,
        )
        self.settings = settings
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle(HIDDEN_PREFIX + " barra de gravação")
        self._drag: QPoint | None = None
        self._paused = False
        self.shown = True

        self.expanded = False
        self.setMouseTracking(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)
        outer.setSizeConstraint(QVBoxLayout.SetFixedSize)

        # modo recolhido: widget discreto (ponto de gravação + tempo + expandir)
        self.pill = QWidget()
        pl = QHBoxLayout(self.pill)
        pl.setContentsMargins(8, 4, 5, 4)
        pl.setSpacing(7)
        self.grip = QLabel()
        self.grip.setPixmap(theme.pixmap("grip", theme.MUTED, 16))
        self.grip.setCursor(Qt.SizeAllCursor)
        pl.addWidget(self.grip)
        self.pill_dot = QLabel()
        self.pill_dot.setFixedSize(9, 9)
        pl.addWidget(self.pill_dot)
        self.pill_time = QLabel("00:00")
        self.pill_time.setStyleSheet("font-size: 12.5px; font-weight: 700; font-family: 'JetBrains Mono','DejaVu Sans Mono',monospace;")
        pl.addWidget(self.pill_time)
        self.pill_time.setCursor(Qt.SizeAllCursor)
        self.expand_btn = tool_button("tools", "", size=18, color=theme.TEXT)
        self.expand_btn.clicked.connect(lambda: self.set_expanded(True))
        pl.addWidget(self.expand_btn)
        outer.addWidget(self.pill)

        self.body = QWidget()
        body_l = QVBoxLayout(self.body)
        body_l.setContentsMargins(0, 0, 0, 0)
        body_l.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(14, 8, 10, 4)
        top.setSpacing(8)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(10, 2, 10, 8)
        bottom.setSpacing(3)
        body_l.addLayout(top)
        body_l.addLayout(bottom)
        # linha de ajuda: nome e atalho do item sob o mouse (fica na própria barra, fora do vídeo)
        self.hint = QLabel()
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setFixedHeight(20)
        self.hint.setStyleSheet(f"color: {theme.MUTED}; font-size: 11.5px; padding-bottom: 5px;")
        body_l.addWidget(self.hint)
        outer.addWidget(self.body)
        self.body.hide()

        # linha 1: gravação
        self.dot = QLabel()
        self.dot.setFixedSize(12, 12)
        top.addWidget(self.dot)
        self.time = QLabel("00:00:00")
        self.time.setStyleSheet("font-size: 19px; font-weight: 700; font-family: 'JetBrains Mono','DejaVu Sans Mono',monospace;")
        self.time.setMinimumWidth(104)
        top.addWidget(self.time)
        mic = QLabel()
        mic.setPixmap(theme.pixmap("mic", theme.MUTED, 16))
        top.addWidget(mic)
        self.meter = LevelMeter(height=6)
        self.meter.setFixedWidth(96)
        top.addWidget(self.meter)
        top.addSpacing(6)
        top.addWidget(vline(22))
        self.pause_btn = tool_button("pause", "", size=20)
        self.pause_btn.clicked.connect(self.pause_toggled.emit)
        top.addWidget(self.pause_btn)
        self.stop_btn = tool_button("stop", "", size=20, color=theme.REC_HI)
        self.stop_btn.clicked.connect(self.stop.emit)
        top.addWidget(self.stop_btn)
        self.discard_btn = tool_button("trash", "Descartar gravação", size=18, color=theme.MUTED)
        self.discard_btn.clicked.connect(self.discard.emit)
        top.addWidget(self.discard_btn)
        top.addStretch(1)
        self.state = QLabel("GRAVANDO")
        self.state.setProperty("role", "eyebrow")
        top.addWidget(self.state)
        top.addSpacing(4)
        hide = tool_button("minus", "", size=16, color=theme.MUTED)
        hide.clicked.connect(lambda: self.set_expanded(False))
        self.hide_btn = hide
        top.addWidget(hide)

        # linha 2: ferramentas
        self.tool_group = QButtonGroup(self)
        self.tool_buttons = {}
        for key, icon in TOOL_DEFS:
            b = tool_button(icon, "", checkable=True, size=19)
            b.clicked.connect(lambda _=False, k=key: self.tool.emit(k))
            self.tool_group.addButton(b)
            self.tool_buttons[key] = b
            bottom.addWidget(b)
        bottom.addSpacing(4)
        bottom.addWidget(vline(22))
        bottom.addSpacing(4)
        self.swatches: list[Swatch] = []
        self.color_group = QButtonGroup(self)
        for c in PALETTE:
            sw = Swatch(c, 20)
            sw.clicked.connect(lambda _=False, c=c: self.settings.set("tools.color", c))
            self.color_group.addButton(sw)
            self.swatches.append(sw)
            bottom.addWidget(sw)
        self.custom = Swatch("#ff00aa", 20)
        self.custom.setToolTip("Personalizar cor")
        self.custom.clicked.connect(self._pick_color)
        self.color_group.addButton(self.custom)
        bottom.addWidget(self.custom)
        bottom.addSpacing(6)
        self.width_slider = QSlider(Qt.Horizontal)
        self.width_slider.setRange(1, 24)
        self.width_slider.setFixedWidth(70)
        self.width_slider.setToolTip("Espessura do traço")
        self.width_slider.setFocusPolicy(Qt.NoFocus)
        self.width_slider.valueChanged.connect(lambda v: self.settings.set("tools.width", v))
        bottom.addWidget(self.width_slider)
        bottom.addSpacing(4)
        bottom.addWidget(vline(22))
        self.undo_btn = tool_button("undo", "", size=18)
        self.undo_btn.clicked.connect(self.undo.emit)
        self.redo_btn = tool_button("redo", "", size=18)
        self.redo_btn.clicked.connect(self.redo.emit)
        self.clear_btn = tool_button("trash", "", size=18)
        self.clear_btn.clicked.connect(self.clear.emit)
        for b in (self.undo_btn, self.redo_btn, self.clear_btn):
            bottom.addWidget(b)
        bottom.addWidget(vline(22))
        self.fx_buttons = {}
        for key, icon in FX_DEFS:
            b = tool_button(icon, "", checkable=True, size=19)
            b.clicked.connect(lambda on, k=key: self.settings.set(f"effects.{k}", bool(on)))
            self.fx_buttons[key] = b
            bottom.addWidget(b)

        for i, sw in enumerate(self.swatches):
            sw.setToolTip("Cor do traço")
        self._press: QPoint | None = None
        self._moved = False
        self._hovered = None
        self._drag_sources = {self.pill, self.grip, self.pill_dot, self.pill_time, self.expand_btn, self.dot, self.time, self.state, self.hint}
        for w in self.findChildren(QWidget):
            w.installEventFilter(self)
        self.sync()
        self.set_paused(False)
        settings.changed.connect(lambda _k: self.sync())

    def _tip(self, text: str, action: str) -> str:
        key = self.settings.get(f"shortcuts.{action}")
        return f"{text} ({key})" if key else text

    def _idle_hint(self) -> str:
        key = self.settings.get("shortcuts.toggle_bar")
        return "Passe o mouse sobre um item para ver o nome e o atalho · arraste a barra para mover" + (f" · {key} recolhe" if key else "")

    def eventFilter(self, obj, ev) -> bool:
        t = ev.type()
        if t == QEvent.ToolTip:
            return True  # a dica aparece na linha de ajuda da barra (um balão do sistema entraria no vídeo)
        if t == QEvent.Enter:
            tip = obj.toolTip() if hasattr(obj, "toolTip") else ""
            if tip:
                self._hovered = obj
                self.hint.setText(tip)
        elif t == QEvent.Leave and obj is self._hovered:
            self._hovered = None
            self.hint.setText(self._idle_hint())
        elif obj in self._drag_sources:
            # arrastar por qualquer parte do widget recolhido (inclusive pelo ícone) move a barra
            if t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
                self._press = ev.globalPosition().toPoint()
                self._drag = self._press - self.pos()
                self._moved = False
            elif t == QEvent.MouseMove and self._press is not None and ev.buttons() & Qt.LeftButton:
                gp = ev.globalPosition().toPoint()
                if self._moved or (gp - self._press).manhattanLength() > 5:
                    self._moved = True
                    self.move(gp - self._drag)
                    return True
            elif t == QEvent.MouseButtonRelease and self._press is not None:
                self._press = None
                self._drag = None
                if self._moved:
                    self._moved = False
                    if hasattr(obj, "setDown"):
                        obj.setDown(False)
                    self.dragged.emit()
                    return True
        return False

    def sync(self) -> None:
        s = self.settings
        for key, b in self.tool_buttons.items():
            b.setToolTip(self._tip(SHORTCUT_ACTIONS[f"tool_{key}"][0], f"tool_{key}"))
        for key, b in self.fx_buttons.items():
            b.setToolTip(self._tip(SHORTCUT_ACTIONS[f"fx_{key}"][0], f"fx_{key}"))
            b.setChecked(bool(s.get(f"effects.{key}")))
        self.undo_btn.setToolTip(self._tip("Desfazer", "undo"))
        self.redo_btn.setToolTip(self._tip("Refazer", "redo"))
        self.clear_btn.setToolTip(self._tip("Limpar desenhos", "clear"))
        self.stop_btn.setToolTip(self._tip("Parar e enviar ao editor", "record_stop"))
        self.hide_btn.setToolTip(self._tip("Recolher barra", "toggle_bar"))
        self.expand_btn.setToolTip(self._tip("Abrir ferramentas", "toggle_bar"))
        self.discard_btn.setToolTip("Descartar gravação")
        self.custom.setToolTip("Personalizar cor")
        self.width_slider.setToolTip("Espessura do traço")
        if self._hovered is not None:
            self.hint.setText(self._hovered.toolTip())
        else:
            self.hint.setText(self._idle_hint())
        self.pause_btn.setToolTip(self._tip("Retomar" if self._paused else "Pausar", "record_pause"))
        color = s.get("tools.color")
        found = False
        for sw in self.swatches:
            on = sw.color.lower() == str(color).lower()
            sw.setChecked(on)
            found = found or on
        if not found:
            self.custom.set_color(color)
            self.custom.setChecked(True)
        self.width_slider.blockSignals(True)
        self.width_slider.setValue(int(s.get("tools.width")))
        self.width_slider.blockSignals(False)

    def _pick_color(self) -> None:
        dlg = QColorDialog(QColor(self.settings.get("tools.color")), None)
        dlg.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        if dlg.exec():
            self.settings.set("tools.color", dlg.selectedColor().name())
        else:
            self.sync()

    def set_shown(self, on: bool) -> None:
        """Oculta/mostra sem desmapear a janela (preserva a exclusão da captura no compositor)."""
        self.shown = on
        if on:
            self.clearMask()
        else:
            self.setMask(QRegion(0, 0, 1, 1))
        self.geometry_changed.emit()

    def set_expanded(self, on: bool) -> None:
        """Alterna entre o widget discreto e a barra completa, mantendo o centro horizontal."""
        if on == self.expanded and self.body.isVisible() == on:
            return
        center_x, top_y = self.geometry().center().x(), self.y()
        self.expanded = on
        self.pill.setVisible(not on)
        self.body.setVisible(on)
        self.adjustSize()
        self.move(center_x - self.width() // 2, top_y)
        self._fade()
        self.update()
        self.expanded_changed.emit(on)
        self.geometry_changed.emit()

    def _fade(self) -> None:
        self.setWindowOpacity(1.0 if (self.expanded or self.underMouse()) else 0.78)

    def enterEvent(self, ev) -> None:
        super().enterEvent(ev)
        self._fade()

    def leaveEvent(self, ev) -> None:
        super().leaveEvent(ev)
        self._fade()

    def set_tool(self, tool: str) -> None:
        b = self.tool_buttons.get(tool)
        if b:
            b.setChecked(True)

    def set_time(self, seconds: float) -> None:
        s = int(seconds)
        self.time.setText(f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}")
        self.pill_time.setText(f"{s // 60:02d}:{s % 60:02d}" if s < 3600 else self.time.text())

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        color = theme.WARN if paused else theme.REC
        self.dot.setStyleSheet(f"background: {color}; border-radius: 6px;")
        self.pill_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        self.state.setText("PAUSADO" if paused else "GRAVANDO")
        self.state.setStyleSheet(f"color: {color};")
        self.pause_btn.setIcon(theme.icon("play" if paused else "pause", theme.TEXT, 20))
        self.pause_btn.setToolTip(self._tip("Retomar" if paused else "Pausar", "record_pause"))

    def set_history(self, can_undo: bool, can_redo: bool) -> None:
        self.undo_btn.setEnabled(can_undo)
        self.redo_btn.setEnabled(can_redo)
        self.clear_btn.setEnabled(can_undo)

    # -- arrastar --------------------------------------------------------------
    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, ev) -> None:
        if self._drag is not None and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _ev) -> None:
        if self._drag is not None:
            self._drag = None
            self.dragged.emit()

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

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        for i, a in enumerate((14, 22, 30) if self.expanded else ()):
            g = 6 - i * 2
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRoundedRect(r.adjusted(-g, -g + 2, g, g + 2), 16 + g, 16 + g)
        rad = 16 if self.expanded else r.height() / 2
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor(14, 21, 34, 246))
        p.drawRoundedRect(r, rad, rad)
