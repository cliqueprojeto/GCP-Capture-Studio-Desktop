"""Barra de pré-gravação: área, entradas de áudio, qualidade e botão REC."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from .. import APP_NAME, theme
from ..engine import audio, encoders
from .countdown import screen_label
from .widgets import DevFooter, LevelMeter, RecordButton, Toggle, button, label, separator, tool_button

QUALITIES = [("baixa", "Leve"), ("media", "Média"), ("alta", "Alta"), ("maxima", "Máxima")]


class Launcher(QWidget):
    record = Signal()
    choose_area = Signal(str)  # window | region
    open_settings = Signal()
    open_donate = Signal()
    open_editor = Signal()
    open_folder = Signal()
    quit_requested = Signal()

    def __init__(self, settings):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Window)
        self.settings = settings
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(theme.app_icon())
        self._drag: QPoint | None = None
        self.meter_src = audio.LevelMonitor(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        root = QVBoxLayout()
        root.setContentsMargins(24, 18, 24, 16)
        root.setSpacing(0)
        outer.addLayout(root)

        root.addLayout(self._header())
        root.addSpacing(16)
        root.addWidget(separator())
        root.addSpacing(18)

        body = QHBoxLayout()
        body.setSpacing(26)
        left = QVBoxLayout()
        left.setSpacing(0)
        left.addWidget(label("ÁREA DE GRAVAÇÃO", "eyebrow"))
        left.addSpacing(10)
        left.addLayout(self._modes())
        left.addSpacing(8)
        mon = QHBoxLayout()
        mon.setSpacing(10)
        self.monitor_label = label("Monitor")
        self.monitor_combo = QComboBox()
        self.monitor_combo.activated.connect(lambda _i: self.settings.set("capture.monitor", self.monitor_combo.currentData()))
        mon.addWidget(self.monitor_label)
        mon.addWidget(self.monitor_combo, 1)
        left.addLayout(mon)
        left.addSpacing(6)
        self.area_info = label("", "small")
        self.area_info.setWordWrap(True)
        left.addWidget(self.area_info)
        app = QGuiApplication.instance()
        app.screenAdded.connect(lambda _s: (self.reload_devices(), self.sync()))
        app.screenRemoved.connect(lambda _s: (self.reload_devices(), self.sync()))
        left.addSpacing(18)
        left.addWidget(label("ENTRADAS", "eyebrow"))
        left.addSpacing(10)
        left.addLayout(self._inputs())
        left.addSpacing(18)
        left.addWidget(label("VÍDEO", "eyebrow"))
        left.addSpacing(10)
        left.addLayout(self._video())
        body.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(10)
        right.addStretch(1)
        self.rec = RecordButton(118)
        self.rec.clicked.connect(self.record.emit)
        right.addWidget(self.rec, 0, Qt.AlignHCenter)
        self.rec_hint = label("", "small")
        self.rec_hint.setAlignment(Qt.AlignCenter)
        right.addWidget(self.rec_hint)
        right.addStretch(1)
        wrap = QWidget()
        wrap.setLayout(right)
        wrap.setFixedWidth(190)
        body.addWidget(wrap)
        root.addLayout(body)

        root.addSpacing(18)
        root.addWidget(separator())
        root.addSpacing(10)
        self.status = label("", "small")
        self.status.setWordWrap(True)
        self.status.hide()
        root.addWidget(self.status)
        footer = DevFooter()
        footer.donate.connect(self.open_donate.emit)
        root.addWidget(footer)

        self.setFixedWidth(800)
        self.reload_devices()
        self.sync()
        settings.changed.connect(self._on_setting)

    # -- construção ----------------------------------------------------------
    def _header(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(40))
        h.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(0)
        name = label(APP_NAME)
        name.setStyleSheet("font-size: 16px; font-weight: 700;")
        col.addWidget(name)
        col.addWidget(label("Grave, anote ao vivo e edite", "small"))
        h.addLayout(col)
        h.addStretch(1)
        for icon, tip, sig in (
            ("film", "Abrir o editor de vídeo", self.open_editor),
            ("folder", "Abrir pasta das gravações", self.open_folder),
            ("settings", "Configurações", self.open_settings),
            ("heart", "Apoie o projeto", self.open_donate),
        ):
            b = tool_button(icon, tip, color=theme.ACCENT if icon == "heart" else theme.TEXT)
            b.clicked.connect(sig.emit)
            h.addWidget(b)
        h.addSpacing(8)
        mini = tool_button("minus", "Minimizar", color=theme.MUTED)
        mini.clicked.connect(self.showMinimized)
        h.addWidget(mini)
        close = tool_button("x", "Fechar", color=theme.MUTED)
        close.clicked.connect(self.quit_requested.emit)
        h.addWidget(close)
        return h

    def _modes(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        self.mode_group = QButtonGroup(self)
        self.mode_buttons: dict[str, QPushButton] = {}
        for key, text, icon in (("fullscreen", "Tela inteira", "monitor"), ("window", "Janela", "window"), ("region", "Região", "region")):
            b = QPushButton("  " + text)
            b.setProperty("role", "mode")
            b.setCheckable(True)
            b.setIcon(theme.icon(icon, theme.MUTED, 22, active=theme.ACCENT_HI))
            b.setIconSize(QSize(22, 22))
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(54)
            b.clicked.connect(lambda _=False, k=key: self._mode_clicked(k))
            self.mode_group.addButton(b)
            self.mode_buttons[key] = b
            row.addWidget(b, 1)
        return row

    def _inputs(self) -> QGridLayout:
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(8)
        g.setColumnStretch(2, 1)

        def icon_label(name: str) -> QLabel:
            lb = QLabel()
            lb.setPixmap(theme.pixmap(name, theme.MUTED, 18))
            return lb

        # microfone
        self.mic_on = Toggle()
        self.mic_combo = QComboBox()
        self.mic_meter = LevelMeter()
        self.mic_vol = QSlider(Qt.Horizontal)
        self.mic_vol.setRange(0, 200)
        self.mic_vol.setFixedWidth(120)
        self.mic_vol_text = label("100%", "small")
        self.mic_vol_text.setFixedWidth(38)
        g.addWidget(icon_label("mic"), 0, 0)
        g.addWidget(label("Microfone"), 0, 1)
        g.addWidget(self.mic_combo, 0, 2)
        g.addWidget(self.mic_on, 0, 3)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self.mic_meter, 1)
        row.addWidget(self.mic_vol)
        row.addWidget(self.mic_vol_text)
        g.addLayout(row, 1, 2, 1, 2)
        # som do sistema
        self.sys_on = Toggle()
        self.sys_combo = QComboBox()
        self.sys_vol = QSlider(Qt.Horizontal)
        self.sys_vol.setRange(0, 200)
        self.sys_vol.setFixedWidth(120)
        self.sys_vol_text = label("100%", "small")
        self.sys_vol_text.setFixedWidth(38)
        g.addWidget(icon_label("speaker"), 2, 0)
        g.addWidget(label("Som do sistema"), 2, 1)
        g.addWidget(self.sys_combo, 2, 2)
        g.addWidget(self.sys_on, 2, 3)
        row2 = QHBoxLayout()
        row2.setSpacing(10)
        row2.addWidget(label("Áudio que toca no computador", "small"), 1)
        row2.addWidget(self.sys_vol)
        row2.addWidget(self.sys_vol_text)
        g.addLayout(row2, 3, 2, 1, 2)
        # webcam
        self.cam_on = Toggle()
        g.addWidget(icon_label("webcam"), 4, 0)
        g.addWidget(label("Webcam"), 4, 1)
        g.addWidget(label("Fixa onde você posicionar · ajustes em Configurações", "small"), 4, 2)
        g.addWidget(self.cam_on, 4, 3)

        self.mic_on.toggled.connect(lambda v: self.settings.set("audio.mic_enabled", v))
        self.sys_on.toggled.connect(lambda v: self.settings.set("audio.sys_enabled", v))
        self.cam_on.toggled.connect(lambda v: self.settings.set("webcam.enabled", v))
        self.mic_combo.activated.connect(lambda _i: self.settings.set("audio.mic_device", self.mic_combo.currentData()))
        self.sys_combo.activated.connect(lambda _i: self.settings.set("audio.sys_device", self.sys_combo.currentData()))
        self.mic_vol.valueChanged.connect(lambda v: self.settings.set("audio.mic_volume", v))
        self.sys_vol.valueChanged.connect(lambda v: self.settings.set("audio.sys_volume", v))
        self.meter_src.level.connect(self.mic_meter.set_level)
        return g

    def _video(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        self.fps = QComboBox()
        for v in (15, 24, 30, 60):
            self.fps.addItem(f"{v} fps", v)
        self.quality = QComboBox()
        for key, text in QUALITIES:
            self.quality.addItem(f"Qualidade {text.lower()}", key)
        self.fps.activated.connect(lambda _i: self.settings.set("video.fps", self.fps.currentData()))
        self.quality.activated.connect(lambda _i: self.settings.set("video.quality", self.quality.currentData()))
        row.addWidget(self.fps)
        row.addWidget(self.quality)
        self.enc_chip = QLabel()
        self.enc_chip.setStyleSheet(
            f"background: {theme.alpha(theme.OK, 0.12)}; color: {theme.OK}; border-radius: 9px; padding: 5px 10px; font-size: 11.5px; font-weight: 600;"
        )
        row.addWidget(self.enc_chip)
        row.addStretch(1)
        return row

    # -- estado ----------------------------------------------------------------
    def reload_devices(self) -> None:
        screens = QGuiApplication.screens()
        self.monitor_combo.clear()
        self.monitor_combo.addItem("Monitor onde esta janela está", "")
        for i, sc in enumerate(screens):
            self.monitor_combo.addItem(screen_label(sc, i), sc.name())
        many = len(screens) > 1
        self.monitor_label.setVisible(many)
        self.monitor_combo.setVisible(many)
        self.mic_combo.clear()
        self.mic_combo.addItem("Padrão do sistema", "default")
        for d in audio.microphones():
            self.mic_combo.addItem(d.label, d.name)
        self.sys_combo.clear()
        self.sys_combo.addItem("Saída padrão do sistema", "default")
        for d in audio.outputs():
            self.sys_combo.addItem(d.label, d.name)

    @staticmethod
    def _select(combo: QComboBox, value) -> None:
        idx = combo.findData(value)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def sync(self) -> None:
        s = self.settings
        for w, key in ((self.mic_on, "audio.mic_enabled"), (self.sys_on, "audio.sys_enabled"), (self.cam_on, "webcam.enabled")):
            w.blockSignals(True)
            w.setChecked(bool(s.get(key)))
            w.set_knob(1.0 if w.isChecked() else 0.0)
            w.blockSignals(False)
        self._select(self.mic_combo, s.get("audio.mic_device"))
        self._select(self.sys_combo, s.get("audio.sys_device"))
        for sl, txt, key in ((self.mic_vol, self.mic_vol_text, "audio.mic_volume"), (self.sys_vol, self.sys_vol_text, "audio.sys_volume")):
            sl.blockSignals(True)
            sl.setValue(int(s.get(key)))
            sl.blockSignals(False)
            txt.setText(f"{int(s.get(key))}%")
        self.mic_combo.setEnabled(self.mic_on.isChecked())
        self.mic_vol.setEnabled(self.mic_on.isChecked())
        self.sys_combo.setEnabled(self.sys_on.isChecked())
        self.sys_vol.setEnabled(self.sys_on.isChecked())
        self._select(self.fps, s.get("video.fps"))
        self._select(self.quality, s.get("video.quality"))
        mode = s.get("capture.mode")
        self.mode_buttons.get(mode, self.mode_buttons["fullscreen"]).setChecked(True)
        self._select(self.monitor_combo, s.get("capture.monitor") or "")
        self.monitor_combo.setEnabled(mode == "fullscreen")
        self._area_text()
        enc = encoders.pick(s.get("video.encoder"))
        if enc is None:
            self.enc_chip.setText("Sem codificador H.264")
        else:
            self.enc_chip.setText(("Aceleração por GPU · " if enc.hardware else "") + enc.label.split("· ")[-1] + ("" if enc.hardware else " (CPU)"))
            self.enc_chip.setToolTip(enc.label)
        self.rec_hint.setText(f"{s.get('shortcuts.record_pause') or 'Clique'} inicia · {s.get('shortcuts.record_stop') or '—'} para")
        self._restart_meter()

    def _area_text(self) -> None:
        mode = self.settings.get("capture.mode")
        region = self.settings.get("capture.region")
        if mode == "fullscreen":
            self.area_info.setText("O monitor inteiro será gravado.")
        elif region:
            kind = "Janela" if mode == "window" else "Região"
            where = ""
            screens = QGuiApplication.screens()
            if len(screens) > 1:
                from PySide6.QtCore import QPoint

                center = QPoint(region[0] + region[2] // 2, region[1] + region[3] // 2)
                for i, sc in enumerate(screens):
                    if sc.geometry().contains(center):
                        where = f" · {screen_label(sc, i)}"
            self.area_info.setText(f"{kind}: {region[2]} × {region[3]} px{where} — clique novamente para redefinir.")
        else:
            self.area_info.setText("Clique para escolher a área.")

    def _mode_clicked(self, key: str) -> None:
        if key == "fullscreen":
            self.settings.set("capture.mode", "fullscreen")
        else:
            self.choose_area.emit(key)
            self.sync()  # mantém o botão anterior marcado até a escolha ser confirmada

    def _on_setting(self, key: str) -> None:
        if key.startswith(("audio.", "video.", "capture.", "webcam.", "shortcuts")):
            self.sync()

    def _restart_meter(self) -> None:
        s = self.settings
        if self.isVisible() and s.get("audio.mic_enabled"):
            dev = audio.resolve_mic(s.get("audio.mic_device"))
            key = (dev, int(s.get("audio.mic_volume")))
            prev = getattr(self, "_meter_key", None)
            if prev == key and self.meter_src.pipe is not None:
                return
            if prev and prev[0] == dev and self.meter_src.pipe is not None:
                self.meter_src.set_volume(key[1] / 100.0)
            else:
                self.meter_src.start(dev, key[1] / 100.0)
            self._meter_key = key
        else:
            self.meter_src.stop()
            self._meter_key = None

    def set_status(self, text: str, kind: str = "info") -> None:
        if not text:
            self.status.hide()
        else:
            color = {"error": theme.REC_HI, "warn": theme.WARN}.get(kind, theme.MUTED)
            self.status.setStyleSheet(f"color: {color}; font-size: 12px; padding-bottom: 6px;")
            self.status.setText(text)
            self.status.show()
        self.adjustSize()

    def set_busy(self, busy: bool) -> None:
        self.rec.setEnabled(not busy)

    # -- eventos ---------------------------------------------------------------
    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        self._restart_meter()

    def hideEvent(self, ev) -> None:
        super().hideEvent(ev)
        self.meter_src.stop()
        self._meter_key = None

    def closeEvent(self, ev) -> None:
        ev.ignore()
        self.quit_requested.emit()

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton and ev.position().y() < 90:
            from ..platform.hyprland import is_hyprland

            handle = self.windowHandle()
            # o Hyprland anuncia, mas não atende, o arrasto pelo compositor (_NET_WM_MOVERESIZE): lá o
            # programa move a janela por conta própria
            if not is_hyprland() and handle is not None and handle.startSystemMove():
                return
            self._drag = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, ev) -> None:
        if self._drag is not None and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _ev) -> None:
        self._drag = None

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(14, 14, -14, -14)
        for i, a in enumerate((10, 16, 22, 30)):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, a))
            g = 12 - i * 3
            p.drawRoundedRect(r.adjusted(-g, -g + 3, g, g + 3), 20 + g, 20 + g)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor(theme.BG))
        p.drawRoundedRect(r, 20, 20)
