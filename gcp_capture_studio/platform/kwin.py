"""Ponte com o KWin (KDE Plasma): posição global do ponteiro e lista de janelas no Wayland.

No Wayland os aplicativos não enxergam o ponteiro fora das próprias janelas; um pequeno
script do KWin envia a posição por D-Bus para os efeitos do mouse (destaque, holofote, lupa).
"""
from __future__ import annotations

import json
import os
import tempfile

from gi.repository import Gio, GLib
from PySide6.QtCore import QObject, QPoint, Signal

SERVICE = "br.com.gestaoculturalpro.CaptureStudio"
OBJ = "/Bridge"
IFACE = "br.com.gestaoculturalpro.CaptureStudio.Bridge"

_XML = f"""
<node><interface name="{IFACE}">
  <method name="Pos"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
  <method name="Windows"><arg type="s" direction="in"/></method>
  <method name="Marked"><arg type="i" direction="in"/></method>
  <method name="Screens"><arg type="s" direction="in"/></method>
</interface></node>
"""

_POINTER_JS = f"""
var last = 0, timer = null;
function send() {{
    var p = workspace.cursorPos;
    callDBus("{SERVICE}", "{OBJ}", "{IFACE}", "Pos", Math.round(p.x), Math.round(p.y));
}}
try {{ timer = new QTimer(); timer.singleShot = true; timer.interval = 4; timer.timeout.connect(send); }} catch (e) {{ timer = null; }}
workspace.cursorPosChanged.connect(function () {{
    var now = Date.now();
    if (now - last >= 4) {{ last = now; send(); }}
    else if (timer) {{ timer.start(); }}
}});
send();
"""

_WINDOWS_JS = f"""
var out = [];
var list = workspace.windowList ? workspace.windowList() : workspace.clientList();
for (var i = 0; i < list.length; i++) {{
    var w = list[i];
    if (!w.normalWindow || w.minimized || w.skipTaskbar) continue;
    var g = w.frameGeometry;
    out.push({{title: String(w.caption), app: String(w.resourceClass), x: Math.round(g.x), y: Math.round(g.y),
              w: Math.round(g.width), h: Math.round(g.height), active: w === workspace.activeWindow}});
}}
callDBus("{SERVICE}", "{OBJ}", "{IFACE}", "Windows", JSON.stringify(out));
"""


_SCREENS_JS = f"""
var out = [];
var list = workspace.screens;
for (var i = 0; i < list.length; i++) {{
    var s = list[i], g = s.geometry;
    out.push({{name: String(s.name), x: Math.round(g.x), y: Math.round(g.y), w: Math.round(g.width), h: Math.round(g.height),
              scale: Number(s.devicePixelRatio)}});
}}
callDBus("{SERVICE}", "{OBJ}", "{IFACE}", "Screens", JSON.stringify(out));
"""

_MARK_JS = f"""
var done = 0;
var list = workspace.windowList ? workspace.windowList() : workspace.clientList();
for (var i = 0; i < list.length; i++) {{
    var w = list[i];
    if (w.pid !== %d || String(w.caption).indexOf("%s") !== 0) continue;
    w.skipTaskbar = true; w.skipSwitcher = true; w.skipPager = true; w.keepAbove = true;
    if ("excludeFromCapture" in w) {{ w.excludeFromCapture = true; if (w.excludeFromCapture) done++; }}
}}
callDBus("{SERVICE}", "{OBJ}", "{IFACE}", "Marked", done);
"""


def kwin_available() -> bool:
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        res = bus.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
            GLib.Variant("(s)", ("org.kde.KWin",)), None, Gio.DBusCallFlags.NONE, 1500, None,
        )
        return bool(res.unpack()[0])
    except Exception:
        return False


class KWinBridge(QObject):
    pointer = Signal(QPoint)
    windows = Signal(list)
    marked = Signal(int)  # janelas efetivamente excluídas da captura
    screens = Signal(list)  # monitores com a escala real de cada um

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        except Exception:  # noqa: BLE001 — sem D-Bus (ex.: Windows)
            self.bus = None
        self.available = self.bus is not None and kwin_available()
        self._reg = 0
        self._own = 0
        self._loaded: set[str] = set()
        self._tmp: dict[str, str] = {}
        if self.available:
            self._serve()

    def _serve(self) -> None:
        info = Gio.DBusNodeInfo.new_for_xml(_XML).interfaces[0]

        def on_call(_c, _sender, _path, _iface, method, params, invocation):
            if method == "Pos":
                x, y = params.unpack()
                self.pointer.emit(QPoint(x, y))
            elif method == "Marked":
                self.marked.emit(int(params.unpack()[0]))
            elif method == "Screens":
                try:
                    self.screens.emit(json.loads(params.unpack()[0]))
                except Exception:
                    pass
            elif method == "Windows":
                try:
                    self.windows.emit(json.loads(params.unpack()[0]))
                except Exception:
                    self.windows.emit([])
            invocation.return_value(None)

        try:
            self._reg = self.bus.register_object(OBJ, info, on_call, None, None)
            self._own = Gio.bus_own_name_on_connection(self.bus, SERVICE, Gio.BusNameOwnerFlags.REPLACE, None, None)
        except Exception:
            self.available = False

    def _call(self, path: str, iface: str, method: str, args=None):
        return self.bus.call_sync("org.kde.KWin", path, iface, method, args, None, Gio.DBusCallFlags.NONE, 3000, None)

    def _run(self, plugin: str, source: str) -> bool:
        if not self.available:
            return False
        self._unload(plugin)
        fd, path = tempfile.mkstemp(prefix=f"{plugin}-", suffix=".js")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(source)
        self._tmp[plugin] = path
        try:
            sid = self._call("/Scripting", "org.kde.kwin.Scripting", "loadScript", GLib.Variant("(ss)", (path, plugin))).unpack()[0]
            if sid < 0:
                return False
            self._call(f"/Scripting/Script{sid}", "org.kde.kwin.Script", "run")
            self._loaded.add(plugin)
            return True
        except Exception:
            return False

    def _unload(self, plugin: str) -> None:
        try:
            self._call("/Scripting", "org.kde.kwin.Scripting", "unloadScript", GLib.Variant("(s)", (plugin,)))
        except Exception:
            pass
        self._loaded.discard(plugin)
        path = self._tmp.pop(plugin, None)
        if path:
            try:
                os.remove(path)
            except OSError:
                pass

    # -- API -----------------------------------------------------------------
    def start_pointer(self) -> bool:
        return self._run("gcp_capture_pointer", _POINTER_JS)

    def stop_pointer(self) -> None:
        self._unload("gcp_capture_pointer")

    def request_windows(self) -> bool:
        return self._run("gcp_capture_windows", _WINDOWS_JS)

    def request_screens(self) -> bool:
        """Pede os monitores e a escala de cada um (o portal só informa o tamanho lógico)."""
        return self._run("gcp_capture_screens", _SCREENS_JS)

    def hide_from_capture(self, caption_prefix: str) -> bool:
        """Mantém as janelas do aplicativo com esse título visíveis na tela, mas fora do vídeo
        (KWin 6.x: propriedade excludeFromCapture). O resultado chega pelo sinal `marked`."""
        return self._run("gcp_capture_mark", _MARK_JS % (os.getpid(), caption_prefix))

    def set_effect(self, name: str, on: bool) -> bool:
        """Liga/desliga um efeito nativo do KWin (ex.: mouseclick) apenas durante a sessão."""
        try:
            if on:
                return bool(self._call("/Effects", "org.kde.kwin.Effects", "loadEffect", GLib.Variant("(s)", (name,))).unpack()[0])
            self._call("/Effects", "org.kde.kwin.Effects", "unloadEffect", GLib.Variant("(s)", (name,)))
            return True
        except Exception:
            return False

    def effect_loaded(self, name: str) -> bool:
        try:
            return bool(self._call("/Effects", "org.kde.kwin.Effects", "isEffectLoaded", GLib.Variant("(s)", (name,))).unpack()[0])
        except Exception:
            return False

    def shutdown(self) -> None:
        for plugin in list(self._loaded):
            self._unload(plugin)
