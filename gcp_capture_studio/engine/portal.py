"""Captura de tela no Wayland via xdg-desktop-portal (ScreenCast) + PipeWire."""
from __future__ import annotations

import os
import random

import gi

from gi.repository import Gio, GLib  # noqa: E402
from PySide6.QtCore import QObject, Signal

PORTAL = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
SC = "org.freedesktop.portal.ScreenCast"

SRC_MONITOR = 1
SRC_WINDOW = 2
CURSOR_HIDDEN = 1
CURSOR_EMBEDDED = 2


def portal_available() -> bool:
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        res = bus.call_sync(
            PORTAL, PATH, "org.freedesktop.DBus.Properties", "Get",
            GLib.Variant("(ss)", (SC, "version")), None, Gio.DBusCallFlags.NONE, 2000, None,
        )
        return res is not None
    except Exception:
        return False


class ScreenCastPortal(QObject):
    """Sessão de compartilhamento de tela. Emite `started` com os dados do fluxo PipeWire."""

    started = Signal(dict)  # {node, position, size, source_type}
    failed = Signal(str)
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.sender = self.bus.get_unique_name()[1:].replace(".", "_")
        self.session: str | None = None
        self.restore_token = ""
        self._subs: list[int] = []
        self._opts: dict = {}

    # -- utilidades ---------------------------------------------------------
    def _token(self) -> str:
        return f"gcp{random.randint(0, 2**31)}"

    def _request(self, method: str, signature: str, args: tuple, options: dict, on_ok) -> None:
        token = self._token()
        options = dict(options)
        options["handle_token"] = GLib.Variant("s", token)
        req_path = f"{PATH}/request/{self.sender}/{token}"
        sub_id = 0

        def on_response(_c, _s, _p, _i, _sig, params, *_):
            self.bus.signal_unsubscribe(sub_id)
            code, results = params.unpack()
            if code == 0:
                on_ok(results)
            elif code == 1:
                self.failed.emit("cancelled")
            else:
                self.failed.emit(f"O portal de captura recusou a solicitação ({method}).")

        sub_id = self.bus.signal_subscribe(
            PORTAL, "org.freedesktop.portal.Request", "Response", req_path, None,
            Gio.DBusSignalFlags.NONE, on_response,
        )

        def on_done(bus, res):
            try:
                bus.call_finish(res)
            except Exception as exc:  # noqa: BLE001
                self.bus.signal_unsubscribe(sub_id)
                self.failed.emit(f"Falha ao falar com o portal de captura: {exc}")

        self.bus.call(
            PORTAL, PATH, SC, method, GLib.Variant(signature, (*args, options)), None,
            Gio.DBusCallFlags.NONE, -1, None, on_done,
        )

    # -- fluxo --------------------------------------------------------------
    def start(self, source_types: int = SRC_MONITOR, show_cursor: bool = True, restore_token: str = "") -> None:
        self._opts = {"types": source_types, "cursor": show_cursor, "restore": restore_token}
        self._request(
            "CreateSession", "(a{sv})", (),
            {"session_handle_token": GLib.Variant("s", self._token())},
            self._on_session,
        )

    def _on_session(self, results: dict) -> None:
        self.session = results["session_handle"]
        self._subs.append(
            self.bus.signal_subscribe(
                PORTAL, "org.freedesktop.portal.Session", "Closed", self.session, None,
                Gio.DBusSignalFlags.NONE, lambda *_: self._on_closed(),
            )
        )
        opts = {
            "types": GLib.Variant("u", self._opts["types"]),
            "multiple": GLib.Variant("b", False),
            "cursor_mode": GLib.Variant("u", CURSOR_EMBEDDED if self._opts["cursor"] else CURSOR_HIDDEN),
            "persist_mode": GLib.Variant("u", 2),
        }
        if self._opts["restore"]:
            opts["restore_token"] = GLib.Variant("s", self._opts["restore"])
        self._request("SelectSources", "(oa{sv})", (self.session,), opts, self._on_selected)

    def _on_selected(self, _results: dict) -> None:
        self._request("Start", "(osa{sv})", (self.session, ""), {}, self._on_started)

    def _on_started(self, results: dict) -> None:
        streams = results.get("streams") or []
        if not streams:
            self.failed.emit("Nenhuma tela foi selecionada.")
            return
        self.restore_token = results.get("restore_token", "") or ""
        node, props = streams[0]
        self.started.emit(
            {
                "node": int(node),
                "position": tuple(props.get("position", (0, 0))),
                "size": tuple(props.get("size", (0, 0))),
                "source_type": int(props.get("source_type", SRC_MONITOR)),
            }
        )

    def open_remote(self) -> int:
        """Abre uma nova conexão PipeWire para a sessão (um descritor por pipeline)."""
        res, fds = self.bus.call_with_unix_fd_list_sync(
            PORTAL, PATH, SC, "OpenPipeWireRemote", GLib.Variant("(oa{sv})", (self.session, {})),
            None, Gio.DBusCallFlags.NONE, 5000, None, None,
        )
        fd = fds.get(res.unpack()[0])
        return os.dup(fd) if fd < 3 else fd

    def _on_closed(self) -> None:
        if self.session:
            self.session = None
            self.closed.emit()

    def close(self) -> None:
        for sub in self._subs:
            self.bus.signal_unsubscribe(sub)
        self._subs.clear()
        if self.session:
            try:
                self.bus.call_sync(
                    PORTAL, self.session, "org.freedesktop.portal.Session", "Close", None, None,
                    Gio.DBusCallFlags.NONE, 2000, None,
                )
            except Exception:
                pass
            self.session = None
