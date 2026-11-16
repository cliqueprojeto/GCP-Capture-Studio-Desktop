"""Controlador principal: une a barra de pré-gravação, o motor, as anotações e o editor."""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime

from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import APP_ID, APP_NAME, __version__, theme
from .config import SHORTCUT_ACTIONS, Settings
from .ui.recbar import HIDDEN_PREFIX

ALWAYS_ON = {"record_pause"}  # atalho ativo mesmo sem gravação em andamento


def _is_wayland() -> bool:
    return os.environ.get("XDG_SESSION_TYPE") == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))


def _register_with_portal() -> None:
    """Identifica o aplicativo para o portal (o seletor de tela mostra "GCP Capture Studio")."""
    try:
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        bus.call_sync(
            "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop", "org.freedesktop.host.portal.Registry",
            "Register", GLib.Variant("(sa{sv})", (APP_ID, {})), None, Gio.DBusCallFlags.NONE, 1500, None,
        )
    except Exception:
        pass


class Controller(QObject):
    def __init__(self, app: QApplication):
        super().__init__()
        from .editor import bridge
        from .engine import portal as portal_mod
        from .engine.recorder import Recorder
        from .platform.clicks import ClickWatcher
        from .platform.hotkeys import GlobalHotkeys
        from .platform.kwin import KWinBridge
        from .ui.countdown import Countdown, RegionSelector
        from .ui.launcher import Launcher
        from .ui.overlay import AnnotationOverlay
        from .ui.recbar import RecBar
        from .ui.webcam import WebcamBubble

        self.app = app
        self.bridge = bridge
        self.portal_mod = portal_mod
        self.settings = Settings()
        self.state = "idle"  # idle | preparing | countdown | recording | paused | finalizing
        self.portal = None
        self.source = None
        self.screen_geo = QRect()
        self.capture_local = QRect()
        self.frame_scale = 1.0
        self.elapsed = 0.0
        self._tick_at = 0.0
        self._kwin_click = False
        self._excluded = False  # a barra está fora do vídeo (KWin excludeFromCapture)
        self._pending_area: str | None = None
        self._target = None  # monitor que deve ser gravado
        self._used_token = False
        self._retried = False
        self._mark_tries = 0
        self._screen_scales: dict[str, float] = {}

        from .updater import Updater

        self.updater = Updater(self.settings, self)
        self.updater.checked.connect(self._update_checked)
        self._update_dialog = None
        self.recorder = Recorder(self)
        self.kwin = KWinBridge(self)
        self.clicks = ClickWatcher(self)
        self.hotkeys = GlobalHotkeys(self)
        self.launcher = Launcher(self.settings)
        self.overlay = AnnotationOverlay(self.settings, self.recorder, self)
        self.recbar = RecBar(self.settings)
        self.countdown = Countdown()
        self.selector = RegionSelector()
        self.webcam = WebcamBubble(self.settings)
        self.clock = QTimer(self)
        self.clock.setInterval(200)
        self.clock.timeout.connect(self._tick)

        self._wire()
        self._tray()
        self._apply_hotkeys()
        self._local_shortcuts()

    # -- ligações ----------------------------------------------------------------
    def _wire(self) -> None:
        L, R, B, O = self.launcher, self.recorder, self.recbar, self.overlay
        L.record.connect(self.start_recording)
        L.choose_area.connect(self.choose_area)
        L.open_settings.connect(self.show_settings)
        L.open_donate.connect(self.show_donate)
        L.open_editor.connect(self.open_editor)
        L.open_folder.connect(self.open_folder)
        L.quit_requested.connect(self.quit)
        R.finished.connect(self._finished)
        R.failed.connect(self._failed)
        R.level.connect(B.meter.set_level)
        R.notice.connect(lambda t: self.tray.showMessage(APP_NAME, t, QSystemTrayIcon.Information, 4000))
        B.pause_toggled.connect(self.toggle_pause)
        B.stop.connect(self.stop_recording)
        B.discard.connect(self.discard_recording)
        B.tool.connect(O.set_tool)
        B.undo.connect(O.undo)
        B.redo.connect(O.redo)
        B.clear.connect(O.clear)
        B.expanded_changed.connect(self._bar_collapsed)
        B.dragged.connect(lambda: self.settings.set("capture.bar_pos", [B.x(), B.y()]))
        O.tool_changed.connect(self._tool_changed)
        O.history_changed.connect(lambda: B.set_history(bool(O.items), bool(O.redo_stack)))
        self.countdown.finished.connect(self._begin)
        self.countdown.cancelled.connect(lambda: self._abort(""))
        self.selector.selected.connect(self._area_selected)
        self.selector.cancelled.connect(self._area_cancelled)
        self.kwin.pointer.connect(O.set_pointer)
        self.kwin.windows.connect(self._windows_ready)
        self.kwin.marked.connect(self._marked)
        self.kwin.screens.connect(self._screens_ready)
        QTimer.singleShot(0, self.kwin.request_screens)
        B.geometry_changed.connect(self._update_holes)
        self.webcam.geometry_changed.connect(self._update_holes)
        O.zoomview.geometry_changed.connect(self._update_holes)
        self.clicks.clicked.connect(O.click)
        self.clicks.combo.connect(O.show_keys)
        self.clicks.combo_released.connect(O.release_keys)
        self.hotkeys.triggered.connect(self.on_action)
        self.settings.changed.connect(self._setting_changed)

    def _tray(self) -> None:
        self.tray = QSystemTrayIcon(theme.rec_tray_icon(False), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        self.act_show = QAction("Abrir GCP Capture Studio", menu)
        self.act_show.triggered.connect(self.show_launcher)
        self.act_rec = QAction("Iniciar gravação", menu)
        self.act_rec.triggered.connect(lambda: self.on_action("record_pause"))
        self.act_stop = QAction("Parar e enviar ao editor", menu)
        self.act_stop.triggered.connect(self.stop_recording)
        self.act_bar = QAction("Mostrar barra de ferramentas", menu)
        self.act_bar.triggered.connect(self.toggle_bar)
        act_cfg = QAction("Configurações", menu)
        act_cfg.triggered.connect(self.show_settings)
        act_don = QAction("Apoie o projeto", menu)
        act_don.triggered.connect(self.show_donate)
        act_quit = QAction("Sair", menu)
        act_quit.triggered.connect(self.quit)
        for a in (self.act_show, None, self.act_rec, self.act_stop, self.act_bar, None, act_cfg, act_don, None, act_quit):
            menu.addSeparator() if a is None else menu.addAction(a)
        self._menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_clicked)
        self.tray.show()
        self._refresh_tray()

    def _tray_clicked(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            if self.state in ("recording", "paused"):
                self.toggle_bar()
            else:
                self.show_launcher()

    def _refresh_tray(self) -> None:
        rec = self.state in ("recording", "paused")
        self.tray.setIcon(theme.rec_tray_icon(rec, self.state == "paused"))
        self.act_rec.setText({"recording": "Pausar gravação", "paused": "Retomar gravação"}.get(self.state, "Iniciar gravação"))
        self.act_rec.setEnabled(self.state in ("idle", "recording", "paused"))
        self.act_stop.setEnabled(rec)
        self.act_bar.setEnabled(rec)
        self.act_bar.setText("Recolher barra de ferramentas" if self.recbar.shown and self.recbar.expanded else "Abrir barra de ferramentas")
        self.act_show.setEnabled(not rec)

    def _apply_hotkeys(self) -> None:
        active = None if self.state in ("recording", "paused", "countdown") else ALWAYS_ON
        self.hotkeys.apply(self.settings.get("shortcuts"), only=active)

    def _local_shortcuts(self) -> None:
        """Reserva quando não há atalhos globais: valem com a janela do aplicativo em foco."""
        for sc in getattr(self, "_shortcuts", []):
            sc.setParent(None)
        self._shortcuts = []
        if self.hotkeys.is_global:
            return
        for action in SHORTCUT_ACTIONS:
            seq = self.settings.get(f"shortcuts.{action}")
            if seq:
                sc = QShortcut(QKeySequence(seq), self.launcher)
                sc.setContext(Qt.ApplicationShortcut)
                sc.activated.connect(lambda a=action: self.on_action(a))
                self._shortcuts.append(sc)

    def _setting_changed(self, key: str) -> None:
        if key.startswith("shortcuts"):
            self._apply_hotkeys()
            self._local_shortcuts()
        elif key == "webcam.enabled":
            self._sync_webcam()
        elif key.startswith("webcam.") and key != "webcam.pos":
            self.webcam.apply()
        elif key.startswith("effects."):
            self.overlay.sync_effects()
            if key in ("effects.click", "effects.keys"):
                self._sync_click_source()
        elif key in ("audio.mic_volume", "audio.sys_volume") and self.recorder.pipe is not None:
            name = "micvol" if key == "audio.mic_volume" else "sysvol"
            el = self.recorder.pipe.get_by_name(name)
            if el is not None:
                el.set_property("volume", int(self.settings.get(key)) / 100.0)

    def _sync_webcam(self) -> None:
        """A webcam fica visível assim que é ligada, para ser posicionada antes de gravar."""
        if self.settings.get("webcam.enabled"):
            screen = self._launcher_screen() if self.screen_geo.isNull() else self.screen_geo
            if not self.webcam.start(screen):
                self.settings.set("webcam.enabled", False)
                self.launcher.set_status("Nenhuma webcam encontrada.", "warn")
        else:
            self.webcam.stop()
        self._update_holes()

    # -- ações de atalho ---------------------------------------------------------
    def on_action(self, action: str) -> None:
        rec = self.state in ("recording", "paused")
        if action == "record_pause":
            if self.state == "idle":
                if self.launcher.isVisible():  # nunca inicia "do nada" com o aplicativo fechado/oculto
                    self.start_recording()
            elif rec:
                self.toggle_pause()
            elif self.state == "countdown":
                self.countdown.cancel()
            return
        if not rec:
            return
        if action == "record_stop":
            self.stop_recording()
        elif action == "toggle_bar":
            self.toggle_bar()
        elif action.startswith("tool_"):
            self.overlay.set_tool(action[5:])
        elif action in ("undo", "redo", "clear"):
            getattr(self.overlay, action)()
        elif action in ("zoom_in", "zoom_out"):
            level = float(self.settings.get("effects.zoom_level") or 2.0) if self.settings.get("effects.zoom") else 1.0
            level = round(max(1.0, min(4.0, level + (0.5 if action == "zoom_in" else -0.5))), 2)
            if level <= 1.0:
                self.settings.set("effects.zoom", False)
            else:
                self.settings.set("effects.zoom_level", level, save=False)
                self.settings.set("effects.zoom", True)
                self.overlay.sync_effects()
        elif action.startswith("fx_"):
            key = f"effects.{action[3:]}"
            self.settings.set(key, not self.settings.get(key))

    def _tool_changed(self, tool: str) -> None:
        self.recbar.set_tool(tool)
        self._update_holes()
        self.overlay.raise_above(self.recbar, self.webcam)

    # -- janelas auxiliares ------------------------------------------------------
    def show_launcher(self) -> None:
        if self.state in ("idle", "finalizing"):
            self.launcher.show()
            self.launcher.raise_()
            self.launcher.activateWindow()

    def show_settings(self) -> None:
        from .ui.settings import SettingsDialog

        dlg = SettingsDialog(self.settings, self.hotkeys, self.launcher if self.launcher.isVisible() else None, self.updater)
        dlg.donate.connect(self.show_donate)
        dlg.exec()
        self.launcher.reload_devices()
        self.launcher.sync()

    def check_updates_on_start(self) -> None:
        from . import updater

        if updater.due(self.settings):
            self.updater.check()

    def _update_checked(self, info: dict) -> None:
        """Há versão nova publicada: oferece a atualização (nunca durante uma gravação)."""
        if info.get("status") != "newer" or self._update_dialog is not None or self.state != "idle":
            return
        from .ui.update import UpdateDialog

        self._update_dialog = UpdateDialog(self.updater, info, self.launcher if self.launcher.isVisible() else None)
        code = self._update_dialog.exec()
        self._update_dialog = None
        if code == 2:
            self.quit()

    def show_donate(self) -> None:
        from .ui.donate import DonateDialog

        DonateDialog(self.launcher if self.launcher.isVisible() else None).exec()

    def open_folder(self) -> None:
        path = self.settings.get("capture.output_dir")
        os.makedirs(path, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def open_editor(self) -> None:
        if not self.bridge.launch_editor(self.settings.get("editor.app"), self.settings.get("editor.custom_path")):
            self.launcher.set_status(
                "Nenhum editor de vídeo encontrado. Instale o Kdenlive ou escolha o seu editor em Configurações › Geral.", "warn"
            )

    # -- escolha de área ---------------------------------------------------------
    def _launcher_screen(self) -> QRect:
        screen = self.launcher.screen() or QGuiApplication.primaryScreen()
        return screen.geometry()

    def choose_area(self, mode: str) -> None:
        if self.state != "idle":
            return
        self._pending_area = mode
        self.launcher.hide()
        if mode == "window":
            if self.kwin.available and self.kwin.request_windows():
                self._win_timeout = QTimer.singleShot(1500, lambda: self._windows_ready(None))
                return
            self._pending_area = "region"
        QTimer.singleShot(180, lambda: self.selector.begin("region", None, self._current_region()))

    def _current_region(self) -> QRect | None:
        r = self.settings.get("capture.region")
        return QRect(*r) if r else None

    def _windows_ready(self, windows) -> None:
        if self._pending_area != "window" or self.selector.isVisible():
            return
        if not windows:
            self._pending_area = "region"
            self.selector.begin("region", None, self._current_region())
            return
        mine = self.app.applicationName().lower()
        wins = [w for w in windows if "gcp capture" not in w.get("title", "").lower() and mine not in w.get("app", "").lower()]
        self.selector.begin("window", wins)

    def _area_selected(self, rect: QRect) -> None:
        w, h = rect.width() - rect.width() % 2, rect.height() - rect.height() % 2
        self.settings.set("capture.region", [rect.x(), rect.y(), w, h], save=False)
        self.settings.set("capture.mode", self._pending_area or "region")
        self.settings.save()
        self._pending_area = None
        self.launcher.set_status("")
        self.launcher.sync()
        self.show_launcher()

    def _area_cancelled(self) -> None:
        self._pending_area = None
        self.show_launcher()

    # -- gravação ----------------------------------------------------------------
    def start_recording(self) -> None:
        if self.state != "idle":
            return
        mode = self.settings.get("capture.mode")
        if mode in ("window", "region") and not self.settings.get("capture.region"):
            self.choose_area(mode)
            return
        self.state = "preparing"
        self._target = self._target_screen()
        self._retried = False
        self.kwin.request_screens()
        self.launcher.set_status("")
        self.launcher.hide()
        self._refresh_tray()
        if os.environ.get("GCP_CAPTURE_TEST_SOURCE"):
            geo = QGuiApplication.primaryScreen().geometry()
            QTimer.singleShot(0, lambda: self._source_ready({"kind": "test", "position": (geo.x(), geo.y()), "size": (geo.width(), geo.height())}))
        elif _is_wayland() and sys.platform.startswith("linux"):
            # pequena espera para a janela do aplicativo sumir antes do seletor do sistema
            QTimer.singleShot(120, self._open_portal)
        elif sys.platform.startswith("win"):
            from .platform import win

            geo, dpr = self._target.geometry(), self._target.devicePixelRatio()
            info = {
                "kind": "win", "position": (geo.x(), geo.y()), "size": (round(geo.width() * dpr), round(geo.height() * dpr)),
                "handle": win.monitor_handle(geo.x() + 8, geo.y() + 8),
            }
            QTimer.singleShot(150, lambda: self._source_ready(info))
        elif sys.platform == "darwin":
            from .platform import mac

            geo, dpr = self._target.geometry(), self._target.devicePixelRatio()
            info = {
                "kind": "mac", "position": (geo.x(), geo.y()), "size": (round(geo.width() * dpr), round(geo.height() * dpr)),
                "handle": mac.display_index(geo.x(), geo.y()),
            }
            QTimer.singleShot(150, lambda: self._source_ready(info))
        else:
            virt = QGuiApplication.primaryScreen().virtualGeometry()
            QTimer.singleShot(0, lambda: self._source_ready({"kind": "x11", "position": (virt.x(), virt.y()), "size": (virt.width(), virt.height()), "virtual": True}))

    def _screen_label(self, screen) -> str:
        from .ui.countdown import screen_label

        screens = QGuiApplication.screens()
        return screen_label(screen, screens.index(screen) if screen in screens else 0)

    def _target_screen(self):
        """Monitor a gravar: o da região/janela escolhida ou o selecionado para tela inteira."""
        mode = self.settings.get("capture.mode")
        region = self.settings.get("capture.region")
        screen = None
        if mode in ("window", "region") and region:
            screen = QGuiApplication.screenAt(QRect(*region).center())
        else:
            name = self.settings.get("capture.monitor")
            screen = next((s for s in QGuiApplication.screens() if name and s.name() == name), None) or self.launcher.screen()
        return screen or QGuiApplication.primaryScreen()

    def _screens_ready(self, screens: list) -> None:
        self._screen_scales = {str(s.get("name")): float(s.get("scale") or 1.0) for s in screens}

    def _open_portal(self, use_token: bool = True) -> None:
        if self.state != "preparing":
            return
        tokens = self.settings.get("portal.tokens") or {}
        token = tokens.get(self._target.name(), "") if use_token else ""
        self._used_token = bool(token)
        if not token and len(QGuiApplication.screens()) > 1:
            self.tray.showMessage(
                APP_NAME, f"Na janela do sistema, escolha: {self._screen_label(self._target)}", QSystemTrayIcon.Information, 6000,
            )
        self.portal = self.portal_mod.ScreenCastPortal(self)
        self.portal.started.connect(lambda info: self._source_ready({"kind": "pipewire", **info}))
        self.portal.failed.connect(self._portal_failed)
        self.portal.closed.connect(self._portal_closed)
        self.portal.start(self.portal_mod.SRC_MONITOR, bool(self.settings.get("capture.show_cursor")), token)

    def _drop_portal(self) -> None:
        if self.portal is not None:
            portal, self.portal = self.portal, None
            portal.closed.disconnect(self._portal_closed)
            portal.close()
            portal.deleteLater()

    def _portal_failed(self, message: str) -> None:
        if self.state in ("preparing", "countdown"):
            self._abort("" if message == "cancelled" else message)

    def _portal_closed(self) -> None:
        if self.state in ("recording", "paused"):
            self.stop_recording()
        elif self.state in ("preparing", "countdown"):
            self.countdown.timer.stop()
            self.countdown.hide()
            self._abort("O compartilhamento de tela foi encerrado pelo sistema.")

    def _abort(self, message: str, kind: str = "error") -> None:
        self._close_session()
        self.state = "idle"
        self._refresh_tray()
        self._apply_hotkeys()
        self.launcher.set_status(message, kind)
        self.show_launcher()

    def _close_session(self) -> None:
        self.overlay.hide()
        self.recbar.hide()
        self.clock.stop()
        self.kwin.stop_pointer()
        self.clicks.configure(False, False)
        if self._kwin_click:
            self.kwin.set_effect("mouseclick", False)
            self._kwin_click = False
        if self.portal is not None:
            self.portal.close()
            self.portal.deleteLater()
            self.portal = None

    def _source_ready(self, info: dict) -> None:
        from .engine.recorder import CaptureSource

        if self.state != "preparing":
            return
        px, py = info.get("position", (0, 0))
        sw, sh = info.get("size", (0, 0))
        screens = QGuiApplication.screens()
        mode = self.settings.get("capture.mode")
        target = self._target or QGuiApplication.primaryScreen()
        if info.get("virtual"):
            geo = QGuiApplication.primaryScreen().virtualGeometry()
        elif info["kind"] in ("test", "win", "mac"):
            geo = target.geometry()
        else:
            match = [s for s in screens if s.geometry().topLeft() == QPoint(px, py)]
            if not match and sw and sh:
                match = [s for s in screens if s.geometry().size().width() == sw and s.geometry().height() == sh]
            got = match[0] if match else None
            if self.portal is not None and got is not None:
                # a permissão devolvida vale para o monitor que o sistema entregou: lembra por monitor
                tokens = dict(self.settings.get("portal.tokens") or {})
                if self.portal.restore_token:
                    tokens[got.name()] = self.portal.restore_token
                if got is not target and self._used_token:
                    tokens.pop(target.name(), None)
                self.settings.set("portal.tokens", tokens)
            if got is not None and got is not target and len(screens) > 1:
                if self._used_token and not self._retried:
                    # a permissão lembrada apontava para outro monitor: pergunta de novo ao sistema
                    self._retried = True
                    self._drop_portal()
                    QTimer.singleShot(150, lambda: self._open_portal(use_token=False))
                    return
                if mode in ("window", "region"):
                    self._abort(
                        f"A área escolhida fica em “{self._screen_label(target)}”, mas foi compartilhado "
                        f"“{self._screen_label(got)}”. Clique em gravar de novo e escolha “{self._screen_label(target)}” "
                        "na janela do sistema.", "warn",
                    )
                    return
            geo = (got or target).geometry()
            # o portal informa o tamanho lógico; com escala no monitor (ex.: 125%) o fluxo tem mais pixels
            k = self._screen_scales.get((got or target).name(), 1.0)
            if sw and sh and k > 1.0:
                sw, sh = round(sw * k), round(sh * k)
        if not sw or not sh:
            sw, sh = geo.width(), geo.height()
        scale = sw / max(1, geo.width())
        crop = None
        local = QRect(0, 0, geo.width(), geo.height())
        if info.get("virtual") and mode == "fullscreen":
            # X11: recorta a área do monitor escolhido
            local = target.geometry().translated(-geo.topLeft())
            crop = (int(local.x() * scale), int(local.y() * scale), int(local.width() * scale), int(local.height() * scale))
        elif mode in ("window", "region"):
            region = QRect(*self.settings.get("capture.region"))
            local = region.translated(-geo.topLeft()).intersected(QRect(0, 0, geo.width(), geo.height()))
            if local.width() < 64 or local.height() < 64:
                self._abort("A área escolhida não está no monitor compartilhado. Escolha a área novamente.", "warn")
                return
            x, y = round(local.x() * scale), round(local.y() * scale)
            crop = (x, y, min(sw - x, round(local.width() * scale)), min(sh - y, round(local.height() * scale)))
        self.source = CaptureSource(
            kind=info["kind"], node=info.get("node", 0), open_fd=self.portal.open_remote if self.portal else None,
            size=(sw, sh), crop=crop, show_cursor=bool(self.settings.get("capture.show_cursor")),
            handle=int(info.get("handle", 0)),
        )
        self.screen_geo, self.capture_local, self.frame_scale = geo, local, scale
        self.state = "countdown"
        self._apply_hotkeys()
        center = geo.topLeft() + local.center()
        self.recbar.set_time(0)
        self.recbar.set_paused(False)
        self.recbar.set_history(False, False)
        self._place_bar()
        self._excluded = False
        self.recbar.set_shown(False)
        self.recbar.show()  # mapeada (invisível) para o compositor poder excluí-la da captura
        self.overlay.prepare_lens_window()
        self.overlay.place_private_windows(geo, local.translated(geo.topLeft()))
        self._mark_tries = 0
        QTimer.singleShot(60, self._mark)
        self.countdown.start(
            int(self.settings.get("capture.countdown")), center,
            self.settings.get("shortcuts.record_stop"), self.settings.get("shortcuts.record_pause"),
        )

    def _begin(self) -> None:
        from .engine import audio
        from .engine.recorder import RecordOptions

        if self.state != "countdown":
            return
        s = self.settings
        opts = RecordOptions(
            fps=int(s.get("video.fps")), quality=s.get("video.quality"), encoder=s.get("video.encoder"),
            mic=audio.resolve_mic(s.get("audio.mic_device")) if s.get("audio.mic_enabled") else "",
            mic_volume=int(s.get("audio.mic_volume")) / 100.0,
            system=audio.resolve_system(s.get("audio.sys_device")) if s.get("audio.sys_enabled") else "",
            system_volume=int(s.get("audio.sys_volume")) / 100.0,
            out_dir=s.get("capture.output_dir"),
            basename="Gravação " + datetime.now().strftime("%Y-%m-%d %H-%M-%S"),
        )
        has_pointer = self.kwin.start_pointer() if _is_wayland() else False
        self.overlay.show_on(self.screen_geo, self.capture_local, self.frame_scale, has_pointer)
        self._sync_click_source()
        self.state = "recording"
        self.elapsed = 0.0
        self._tick_at = time.monotonic()
        self.recorder.start(self.source, opts)
        if self.state != "recording":
            return  # falhou ao iniciar
        self.clock.start()
        self._apply_bar_policy()
        if not self.recbar.shown:
            self.tray.showMessage(
                APP_NAME,
                f"Gravando. {s.get('shortcuts.record_stop')} para parar · {s.get('shortcuts.toggle_bar')} abre as ferramentas.",
                QSystemTrayIcon.Information, 3500,
            )
        self.overlay.raise_above(self.recbar, self.webcam)
        self._refresh_tray()

    def _sync_click_source(self) -> None:
        """Liga a leitura de cliques/teclas somente enquanto há gravação e o efeito está ativo."""
        if self.state not in ("recording", "paused", "countdown"):
            return
        clicks, keys = bool(self.settings.get("effects.click")), bool(self.settings.get("effects.keys"))
        ok = self.clicks.configure(clicks, keys)
        if clicks and not ok and self.kwin.available and not self._kwin_click:
            # sem acesso aos botões do mouse: usa a animação de clique nativa do KWin
            if not self.kwin.effect_loaded("mouseclick"):
                self._kwin_click = self.kwin.set_effect("mouseclick", True)
        elif not clicks and self._kwin_click:
            self.kwin.set_effect("mouseclick", False)
            self._kwin_click = False
        if keys and not ok:
            self.settings.set("effects.keys", False)
            self.tray.showMessage(
                APP_NAME, "Para mostrar as teclas, adicione seu usuário ao grupo “input” e reinicie a sessão.",
                QSystemTrayIcon.Warning, 6000,
            )

    def _bar_fits_outside(self) -> bool:
        self.recbar.adjustSize()
        h = self.recbar.height()
        return self.capture_local.bottom() + h + 8 <= self.screen_geo.height() or self.capture_local.top() - h - 8 >= 0

    def _place_bar(self) -> None:
        """Posição inicial do widget: a escolhida pelo usuário ou o topo central da tela gravada."""
        self.recbar.set_expanded(False)
        self.recbar.adjustSize()
        bw, bh = self.recbar.width(), self.recbar.height()
        g, c = self.screen_geo, self.capture_local
        pos = self.settings.get("capture.bar_pos")
        if pos and g.contains(QPoint(pos[0] + bw // 2, pos[1] + bh // 2)):
            x, y = pos
        else:
            x = g.x() + c.center().x() - bw // 2
            if c.size() != g.size() and c.top() - bh - 6 >= 0:
                y = g.y() + c.top() - bh - 4  # acima da região gravada
            elif c.size() != g.size() and c.bottom() + bh + 6 <= g.height():
                y = g.y() + c.bottom() + 4
            else:
                y = g.y() + 6
        self.recbar.move(x, y)
        self._keep_bar_on_screen()

    def _mark(self) -> None:
        if self.state not in ("countdown", "recording", "paused"):
            return
        if sys.platform.startswith("win"):
            from .platform import win

            o = self.overlay
            self._marked(sum(win.exclude_from_capture(w) for w in (self.recbar, o.lenswin, o.zoomframe, o.zoomview)))
        elif sys.platform == "darwin":
            from .platform import mac

            o = self.overlay
            self._marked(sum(mac.exclude_from_capture(w) for w in (self.recbar, o.lenswin, o.zoomframe, o.zoomview)))
        else:
            self.kwin.hide_from_capture(HIDDEN_PREFIX)

    def _marked(self, count: int) -> None:
        """Resposta do compositor: quantas janelas (barra + lupa) ficaram fora do vídeo."""
        from .ui.overlay import PRIVATE_WINDOWS

        ok = count >= 1 + PRIVATE_WINDOWS
        if not ok and self._mark_tries < 8:
            # as janelas podem ainda não ter sido registradas pelo compositor: tenta de novo
            self._mark_tries += 1
            QTimer.singleShot(200, self._mark)
        self._excluded = ok
        self.overlay.set_lens_excluded(ok)
        self._apply_bar_policy()

    def _apply_bar_policy(self) -> None:
        """Decide se a barra aparece: sempre que o compositor a mantém fora do vídeo;
        caso contrário, só quando cabe fora da área gravada (ou não há atalhos globais)."""
        if self.state not in ("countdown", "recording", "paused"):
            return
        full = self.capture_local.size() == self.screen_geo.size()
        widget = self.settings.get("capture.bar_mode") == "widget"
        if self._excluded:
            want = widget
        else:
            want = (widget and not full and self._bar_fits_outside()) or not self.hotkeys.is_global
        if self.recbar.expanded:
            want = True  # aberta pelo usuário: permanece
        self.set_bar_visible(want)

    def toggle_bar(self) -> None:
        """Abre a barra completa; se já estiver aberta, recolhe para o widget (ou oculta)."""
        if self.state not in ("recording", "paused"):
            return
        if self.recbar.shown and self.recbar.expanded:
            self.recbar.set_expanded(False)
        else:
            self.set_bar_visible(True)
            self.recbar.set_expanded(True)
            self._keep_bar_on_screen()

    def _bar_collapsed(self, expanded: bool) -> None:
        if not expanded:
            self._apply_bar_policy()
        else:
            self._keep_bar_on_screen()
        self._update_holes()
        self._refresh_tray()

    def _keep_bar_on_screen(self) -> None:
        g, b = self.screen_geo, self.recbar
        x = max(g.x() + 4, min(b.x(), g.x() + g.width() - b.width() - 4))
        y = max(g.y() + 4, min(b.y(), g.y() + g.height() - b.height() - 4))
        if (x, y) != (b.x(), b.y()):
            b.move(x, y)

    def set_bar_visible(self, on: bool) -> None:
        if self.state not in ("countdown", "recording", "paused"):
            return
        self.recbar.set_shown(on)
        if on:
            self.overlay.raise_above(self.recbar, self.webcam)
        self._update_holes()
        self._refresh_tray()

    def _update_holes(self) -> None:
        if not self.overlay.active:
            return
        rects = []
        if self.recbar.isVisible() and self.recbar.shown:
            rects.append(self.recbar.geometry())
        if self.webcam.isVisible():
            rects.append(self.webcam.geometry())
        if self.overlay.zoomview.isVisible() and self.overlay.zoomview.shown:
            rects.append(self.overlay.zoomview.geometry())
        self.overlay.set_holes(rects)

    def _tick(self) -> None:
        now = time.monotonic()
        if self.state == "recording":
            self.elapsed += now - self._tick_at
        self._tick_at = now
        self.recbar.set_time(self.elapsed)

    def toggle_pause(self) -> None:
        if self.state == "recording":
            self._tick()
            self.recorder.pause()
            self.state = "paused"
        elif self.state == "paused":
            self.recorder.resume()
            self._tick_at = time.monotonic()
            self.state = "recording"
        else:
            return
        self.recbar.set_paused(self.state == "paused")
        self._refresh_tray()

    def stop_recording(self) -> None:
        if self.state not in ("recording", "paused"):
            return
        self.state = "finalizing"
        self.overlay.hide()
        self.recbar.hide()
        self.clock.stop()
        self._refresh_tray()
        self._apply_hotkeys()
        self.recorder.stop()

    def discard_recording(self) -> None:
        if self.state not in ("recording", "paused"):
            return
        was_recording = self.state == "recording"
        if was_recording:
            self.toggle_pause()
        self.overlay.set_tool("cursor")
        box = QMessageBox(QMessageBox.Question, APP_NAME, "Descartar esta gravação? O vídeo será apagado.", QMessageBox.Yes | QMessageBox.No)
        box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        box.button(QMessageBox.Yes).setText("Descartar")
        box.button(QMessageBox.No).setText("Continuar gravando")
        if box.exec() == QMessageBox.Yes:
            self.recorder.discard()
            self._abort("Gravação descartada.", "info")
        elif was_recording:
            self.toggle_pause()

    def _finished(self, path: str) -> None:
        self._close_session()
        self.state = "idle"
        self._refresh_tray()
        self._apply_hotkeys()
        name = os.path.basename(path)
        if self.settings.get("editor.auto_open"):
            ok, msg = self.bridge.open_in_editor(path, self.settings.get("editor.app"), self.settings.get("editor.custom_path"))
            if ok and self.settings.get("editor.close_after", True):
                # a gravação seguiu para o editor: o gravador se encerra (janelas, bandeja e atalhos),
                # para que nenhuma tecla inicie outra gravação por cima enquanto se edita
                QTimer.singleShot(0, self.quit)
                return
            self.launcher.set_status(f"“{name}” salva. {msg}", "info" if ok else "warn")
            if not ok:
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
        else:
            self.launcher.set_status(f"“{name}” salva em {os.path.dirname(path)}.")
        self.show_launcher()
        self.tray.showMessage(APP_NAME, f"Gravação salva: {name}", QSystemTrayIcon.Information, 4000)

    def _failed(self, message: str) -> None:
        if self.recorder.state == "finalizing":
            # parte do material foi preservada; `finished` virá em seguida
            self.tray.showMessage(APP_NAME, message, QSystemTrayIcon.Warning, 6000)
            self.overlay.hide()
            self.recbar.hide()
            self.clock.stop()
            self.state = "finalizing"
            return
        self._abort(message)

    def quit(self) -> None:
        if self.state in ("recording", "paused"):
            self.launcher.set_status("Há uma gravação em andamento. Pare a gravação antes de sair.", "warn")
            return
        self._close_session()
        self.webcam.stop()
        self.launcher.meter_src.stop()
        self.hotkeys.shutdown()
        self.kwin.shutdown()
        self.settings.save()
        self.tray.hide()
        self.app.quit()


def _selftest(report: str) -> int:
    """Confere se o pacote instalado tem tudo o que a gravação precisa (usado na geração dos instaladores)."""
    lines, ok = [f"{APP_NAME} {__version__} em {sys.platform}"], True
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        Gst.init(None)
        from .engine import encoders, recorder

        needed = ["matroskamux", "videoconvert", "videorate", "audiomixer", "appsink", "tee"]
        if sys.platform.startswith("win"):
            needed += ["d3d11screencapturesrc", "wasapi2src"]
        elif sys.platform == "darwin":
            needed += ["avfvideosrc", "osxaudiosrc"]
        else:
            needed += ["pipewiresrc", "pulsesrc"]
        for name in needed:
            found = Gst.ElementFactory.find(name) is not None
            ok = ok and found
            lines.append(f"{'ok ' if found else 'FALTA'} {name}")
        encs = [e.id for e in encoders.available()]
        ok = ok and bool(encs)
        lines.append("codificadores H.264: " + (", ".join(encs) or "NENHUM"))
        lines.append(f"áudio: {encoders.audio_encoder()[0]}")
        lines.append(f"efeitos no vídeo (cairo): {recorder.HAVE_CAIRO}")
        ok = ok and recorder.HAVE_CAIRO
        import shutil

        lines.append(f"ffmpeg: {shutil.which('ffmpeg') or 'não encontrado'}")
    except Exception as exc:  # noqa: BLE001
        ok = False
        lines.append(f"ERRO: {exc!r}")
    lines.append("RESULTADO: " + ("OK" if ok else "FALHOU"))
    text = "\n".join(lines) + "\n"
    if report:
        with open(report, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        print(text, end="")
    return 0 if ok else 1


def _record_test(out_dir: str) -> int:
    """Grava alguns segundos da tela principal pelo motor do programa e informa o resultado
    (conferência automática do programa empacotado)."""
    from .engine.recorder import CaptureSource, Recorder, RecordOptions

    app = QApplication.instance() or QApplication(sys.argv[:1])
    screen = QGuiApplication.primaryScreen()
    geo, dpr = screen.geometry(), screen.devicePixelRatio()
    size = (round(geo.width() * dpr), round(geo.height() * dpr))
    if sys.platform == "darwin":
        from .platform import mac

        src = CaptureSource(kind="mac", size=size, handle=mac.display_index(geo.x(), geo.y()))
    elif sys.platform.startswith("win"):
        from .platform import win

        src = CaptureSource(kind="win", size=size, handle=win.monitor_handle(geo.x() + 8, geo.y() + 8))
    else:
        src = CaptureSource(kind="test", size=size)
    rec = Recorder()
    result: dict[str, str] = {}
    rec.finished.connect(lambda p: (result.update(path=p), app.quit()))
    rec.failed.connect(lambda m: (result.update(error=m), app.quit()))
    rec.started.connect(lambda: QTimer.singleShot(4000, rec.stop))
    QTimer.singleShot(0, lambda: rec.start(src, RecordOptions(fps=30, quality="media", out_dir=out_dir, basename="gravacao-teste")))
    QTimer.singleShot(90000, app.quit)
    app.exec()
    if "path" in result:
        print(f"gravação: {result['path']}")
        return 0
    print(f"gravação FALHOU: {result.get('error', 'sem resposta')}")
    return 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--version" in argv:
        print(f"{APP_NAME} {__version__}")
        return 0
    if getattr(sys, "frozen", False):
        # programa empacotado (Windows e macOS): ffmpeg/ffprobe acompanham o programa
        base = os.path.dirname(sys.executable)
        inner = getattr(sys, "_MEIPASS", os.path.join(base, "_internal"))
        os.environ["PATH"] = os.pathsep.join(
            [base, inner, os.path.join(inner, "ffmpeg"), os.path.join(base, "_internal"), os.environ.get("PATH", "")]
        )
        # o GStreamer só deve examinar a pasta dos plugins: se examinar a pasta inteira do
        # programa, carrega e descarrega bibliotecas que não aceitam isso
        for folder in (os.path.join(inner, "gst_plugins"), os.path.join(base, "_internal", "gst_plugins"), os.path.join(base, "gst_plugins")):
            if os.path.isdir(folder):
                for var in ("GST_PLUGIN_PATH", "GST_PLUGIN_PATH_1_0", "GST_PLUGIN_SYSTEM_PATH", "GST_PLUGIN_SYSTEM_PATH_1_0"):
                    os.environ[var] = folder
                break
        if sys.platform == "darwin":
            cache = os.path.expanduser("~/Library/Caches/GCP Capture Studio")
        else:
            cache = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "GCP Capture Studio")
        try:
            os.makedirs(cache, exist_ok=True)
            os.environ["GST_REGISTRY"] = os.environ["GST_REGISTRY_1_0"] = os.path.join(cache, f"gst-registry-{__version__}.bin")
        except OSError:
            pass
        for folder in (inner, os.path.join(base, "_internal"), base):
            for name in ("gst-plugin-scanner.exe", "gst-plugin-scanner"):
                scanner = os.path.join(folder, name)
                if os.path.isfile(scanner):
                    os.environ["GST_PLUGIN_SCANNER"] = scanner
                    break
            else:
                continue
            break
    if "--selftest" in argv:
        return _selftest(argv[argv.index("--selftest") + 1] if len(argv) > argv.index("--selftest") + 1 else "")
    if "--gravacao-teste" in argv:
        i = argv.index("--gravacao-teste")
        return _record_test(argv[i + 1] if len(argv) > i + 1 else os.path.expanduser("~"))
    if sys.platform.startswith("linux") and "QT_QPA_PLATFORM" not in os.environ:
        # XWayland/X11: permite janelas sempre no topo, posicionamento livre e cliques que atravessam a camada de anotações
        os.environ["QT_QPA_PLATFORM"] = os.environ.get("GCP_CAPTURE_QPA", "xcb")
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName("gcp-capture-studio")
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("Gestão Cultural Pro")
    app.setDesktopFileName(APP_ID)
    _register_with_portal()
    app.setWindowIcon(theme.app_icon())
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setPalette(theme.dark_palette())  # o tema não depende do tema claro/escuro do sistema
    app.setStyleSheet(theme.STYLESHEET)

    # instância única: uma segunda abertura apenas traz a janela existente para frente
    sock = QLocalSocket()
    sock.connectToServer(APP_ID)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(APP_ID)
    server = QLocalServer()
    server.listen(APP_ID)

    ctl = Controller(app)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), ctl.show_launcher()))
    ctl.launcher.show()
    screen = QGuiApplication.primaryScreen().availableGeometry()
    ctl.launcher.adjustSize()
    ctl.launcher.move(screen.center() - QPoint(ctl.launcher.width() // 2, ctl.launcher.height() // 2))
    QTimer.singleShot(400, ctl._sync_webcam)
    QTimer.singleShot(2500, ctl.check_updates_on_start)
    if "--donate" in argv:
        QTimer.singleShot(200, ctl.show_donate)
    code = app.exec()
    server.close()
    return code
