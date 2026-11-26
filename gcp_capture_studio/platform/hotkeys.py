"""Atalhos globais personalizáveis.

- KDE Plasma (Wayland e X11): KGlobalAccel via D-Bus — funciona com qualquer janela em foco.
- Hyprland (Omarchy e outros): atalhos registrados no compositor pelo socket de controle.
- Outros ambientes Wayland: portal GlobalShortcuts.
- Windows: RegisterHotKey.
- macOS: RegisterEventHotKey (Carbon).
- Reserva: atalhos locais do Qt (ativos quando uma janela do aplicativo está em foco).
"""
from __future__ import annotations

import random
import sys

from gi.repository import Gio, GLib
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QKeySequence

from .. import APP_NAME
from ..config import SHORTCUT_ACTIONS

COMPONENT = "gcp-capture-studio"
KGA = "org.kde.kglobalaccel"
KGA_PATH = "/kglobalaccel"
KGA_IFACE = "org.kde.KGlobalAccel"
PORTAL = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
GS = "org.freedesktop.portal.GlobalShortcuts"


def _has_name(bus, name: str) -> bool:
    try:
        res = bus.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
            GLib.Variant("(s)", (name,)), None, Gio.DBusCallFlags.NONE, 1500, None,
        )
        return bool(res.unpack()[0])
    except Exception:
        return False


def _key_ints(seq: str) -> list[int]:
    ks = QKeySequence(seq)
    if ks.isEmpty():
        return [0, 0, 0, 0]
    return [ks[0].toCombined(), 0, 0, 0]


def _xdg_trigger(seq: str) -> str:
    """Converte 'Ctrl+Alt+Z' para a sintaxe XDG de atalhos ('CTRL+ALT+z')."""
    parts = seq.split("+")
    mods = [{"ctrl": "CTRL", "alt": "ALT", "shift": "SHIFT", "meta": "LOGO"}.get(p.lower(), p) for p in parts[:-1]]
    key = parts[-1]
    key = key.lower() if len(key) == 1 else key
    return "+".join(mods + [key])


class GlobalHotkeys(QObject):
    triggered = Signal(str)  # id da ação

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        except Exception:  # noqa: BLE001 — sem D-Bus (ex.: Windows)
            self.bus = None
        self.backend = "none"
        self._sub = 0
        self._registered: list[str] = []
        self._session = None
        self._win = None
        self._hypr = None
        self._server = ""
        self.conflicts: set[str] = set()
        if sys.platform.startswith("win"):
            from .win import WinHotkeys

            self._win = WinHotkeys(self)
            self._win.triggered.connect(self.triggered.emit)
            self.backend = "win"
        elif sys.platform == "darwin":
            from .mac import MacHotkeys

            self._win = MacHotkeys(self)
            self._win.triggered.connect(self.triggered.emit)
            self.backend = "win" if self._win.available else "none"
        elif self._hyprland_ok():
            self.backend = "hyprland"
        elif self.bus is None:
            pass
        elif _has_name(self.bus, KGA):
            self.backend = "kde"
        elif self._portal_ok():
            self.backend = "portal"

    @property
    def is_global(self) -> bool:
        return self.backend in ("kde", "portal", "win", "hyprland")

    def _hyprland_ok(self) -> bool:
        if not sys.platform.startswith("linux"):
            return False
        from . import hyprland

        if not hyprland.is_hyprland() or not hyprland.available():
            return False
        self._hypr = hyprland.Binds("keys")
        hyprland.events().reloaded.connect(self._hypr.reapply)
        return True

    def bound_combos(self) -> set:
        """Combinações (modmask, tecla) registradas como atalhos do programa no Hyprland."""
        if self._hypr is None:
            return set()
        from .hyprland import _modmask

        return {(_modmask(mods), key.lower()) for mods, key in self._hypr.active.values()}

    def set_server(self, name: str) -> None:
        """Endereço do programa em execução: o Hyprland o avisa a cada atalho (ver hyprsend.py)."""
        self._server = name

    def _portal_ok(self) -> bool:
        try:
            self.bus.call_sync(
                PORTAL, PORTAL_PATH, "org.freedesktop.DBus.Properties", "Get",
                GLib.Variant("(ss)", (GS, "version")), None, Gio.DBusCallFlags.NONE, 1500, None,
            )
            return True
        except Exception:
            return False

    def apply(self, shortcuts: dict[str, str], only: set[str] | None = None) -> None:
        """(Re)registra os atalhos. `only` limita as ações ativas (as demais ficam sem tecla),
        para que Alt+1…9 só sejam capturados enquanto há uma gravação em andamento."""
        if only is not None:
            shortcuts = {k: (v if k in only else "") for k, v in shortcuts.items()}
        if self.backend == "kde":
            self._apply_kde(shortcuts)
        elif self.backend == "portal":
            self._apply_portal(shortcuts)
        elif self.backend == "win":
            self._win.apply(shortcuts)
        elif self.backend == "hyprland":
            self._apply_hyprland(shortcuts)

    # -- Hyprland ----------------------------------------------------------------
    def _apply_hyprland(self, shortcuts: dict[str, str]) -> None:
        from .hyprland import sender_command

        if not self._server:
            return
        wanted = {
            action: (seq, sender_command(self._server, f"action:{action}"), False)
            for action, seq in shortcuts.items()
            if action in SHORTCUT_ACTIONS and seq
        }
        self._hypr.set(wanted)
        self.conflicts = set(self._hypr.conflicts)

    # -- KDE -----------------------------------------------------------------
    def _action_id(self, action: str) -> list[str]:
        return [COMPONENT, action, APP_NAME, SHORTCUT_ACTIONS[action][0]]

    def _kga(self, method: str, args: GLib.Variant):
        return self.bus.call_sync(KGA, KGA_PATH, KGA_IFACE, method, args, None, Gio.DBusCallFlags.NONE, 3000, None)

    def _apply_kde(self, shortcuts: dict[str, str]) -> None:
        try:
            for action in SHORTCUT_ACTIONS:
                aid = self._action_id(action)
                self._kga("doRegister", GLib.Variant("(as)", (aid,)))
                keys = [(_key_ints(shortcuts.get(action, "")),)]
                # flags: SetPresent (2) | NoAutoloading (4) — impõe o atalho escolhido no aplicativo
                self._kga("setShortcutKeys", GLib.Variant("(asa(ai)u)", (aid, keys, 6)))
                if action not in self._registered:
                    self._registered.append(action)
            if not self._sub:
                path = self._kga("getComponent", GLib.Variant("(s)", (COMPONENT,))).unpack()[0]
                self._sub = self.bus.signal_subscribe(
                    KGA, "org.kde.kglobalaccel.Component", "globalShortcutPressed", path, None,
                    Gio.DBusSignalFlags.NONE, self._on_kde,
                )
        except Exception:
            self.backend = "none"

    def _on_kde(self, _c, _s, _p, _i, _sig, params, *_):
        component, action, _ts = params.unpack()
        if component == COMPONENT and action in SHORTCUT_ACTIONS:
            self.triggered.emit(action)

    def current(self, action: str) -> str:
        """Atalho efetivamente ativo no sistema (pode ter sido alterado nas Configurações do KDE)."""
        if self.backend != "kde":
            return ""
        try:
            keys = self._kga("shortcutKeys", GLib.Variant("(as)", (self._action_id(action),))).unpack()[0]
            if keys and keys[0][0][0]:
                return QKeySequence(keys[0][0][0]).toString()
        except Exception:
            pass
        return ""

    # -- Portal ----------------------------------------------------------------
    def _apply_portal(self, shortcuts: dict[str, str]) -> None:
        sender = self.bus.get_unique_name()[1:].replace(".", "_")

        def request(method, signature, args, options, on_ok):
            token = f"gcp{random.randint(0, 2**31)}"
            options = dict(options, handle_token=GLib.Variant("s", token))
            sub = 0

            def on_resp(_c, _s, _p, _i, _sig, params, *_):
                self.bus.signal_unsubscribe(sub)
                code, results = params.unpack()
                if code == 0:
                    on_ok(results)

            sub = self.bus.signal_subscribe(
                PORTAL, "org.freedesktop.portal.Request", "Response",
                f"{PORTAL_PATH}/request/{sender}/{token}", None, Gio.DBusSignalFlags.NONE, on_resp,
            )
            self.bus.call(
                PORTAL, PORTAL_PATH, GS, method, GLib.Variant(signature, (*args, options)), None,
                Gio.DBusCallFlags.NONE, -1, None, None,
            )

        def bind(results):
            self._session = results["session_handle"]
            items = [
                (
                    action,
                    {
                        "description": GLib.Variant("s", SHORTCUT_ACTIONS[action][0]),
                        "preferred_trigger": GLib.Variant("s", _xdg_trigger(shortcuts.get(action, ""))),
                    },
                )
                for action in SHORTCUT_ACTIONS
                if shortcuts.get(action)
            ]
            request("BindShortcuts", "(oa(sa{sv})sa{sv})", (self._session, items, ""), {}, lambda _r: None)

        if self._session is None:
            if not self._sub:
                self._sub = self.bus.signal_subscribe(
                    PORTAL, GS, "Activated", PORTAL_PATH, None, Gio.DBusSignalFlags.NONE,
                    lambda _c, _s, _p, _i, _sig, params, *_: self.triggered.emit(params.unpack()[1]),
                )
            try:
                request(
                    "CreateSession", "(a{sv})", (),
                    {"session_handle_token": GLib.Variant("s", f"gcp{random.randint(0, 2**31)}")}, bind,
                )
            except Exception:
                self.backend = "none"

    # -- encerramento ----------------------------------------------------------
    def shutdown(self) -> None:
        if self._win is not None:
            self._win.clear()
        if self._hypr is not None:
            self._hypr._wanted = {}
            self._hypr.clear()
        if self._sub and self.bus is not None:
            self.bus.signal_unsubscribe(self._sub)
            self._sub = 0
        if self.backend == "kde":
            # libera as teclas quando o aplicativo fecha (voltam a valer na próxima abertura)
            for action in self._registered:
                try:
                    self._kga("setInactive", GLib.Variant("(as)", (self._action_id(action),)))
                except Exception:
                    pass
            self._registered.clear()
