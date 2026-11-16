"""Cliques globais do mouse para o efeito de clique.

Lê os botões diretamente de /dev/input (o usuário precisa estar no grupo `input`,
padrão no BigLinux/Manjaro). Apenas eventos de botão são processados — nenhuma tecla é lida.
"""
from __future__ import annotations

import glob
import os
import struct
import sys

from PySide6.QtCore import QObject, QSocketNotifier, Signal

_EVENT = struct.Struct("llHHi")
EV_KEY = 1
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112
_NAMES = {BTN_LEFT: "left", BTN_RIGHT: "right", BTN_MIDDLE: "middle"}

# teclado: apenas para o mostrador de combinações (nada é armazenado; digitação comum é ignorada)
_MODS = {29: "Ctrl", 97: "Ctrl", 56: "Alt", 100: "AltGr", 42: "Shift", 54: "Shift", 125: "Super", 126: "Super"}
_MOD_ORDER = ["Ctrl", "Super", "Alt", "AltGr", "Shift"]
_KEYS = {1: "Esc", 14: "Backspace", 15: "Tab", 28: "Enter", 57: "Espaço", 99: "PrtSc", 102: "Home", 103: "↑", 104: "PgUp",
         105: "←", 106: "→", 107: "End", 108: "↓", 109: "PgDn", 110: "Insert", 111: "Delete", 87: "F11", 88: "F12",
         12: "-", 13: "=", 26: "[", 27: "]", 39: ";", 40: "'", 41: "`", 43: "\\", 51: ",", 52: ".", 53: "/"}
_KEYS.update({59 + i: f"F{i + 1}" for i in range(10)})
_KEYS.update({2 + i: c for i, c in enumerate("1234567890")})
_KEYS.update({16 + i: c for i, c in enumerate("QWERTYUIOP")})
_KEYS.update({30 + i: c for i, c in enumerate("ASDFGHJKL")})
_KEYS.update({44 + i: c for i, c in enumerate("ZXCVBNM")})
_ALONE = {1, 15, 28, 99, 111, 87, 88} | set(range(59, 69))  # teclas exibidas mesmo sem modificador


def _has_key(path: str, code: int) -> bool:
    name = os.path.basename(path)
    try:
        with open(f"/sys/class/input/{name}/device/capabilities/key", encoding="ascii") as fh:
            bits = 0
            for word in fh.read().split():
                bits = (bits << 64) | int(word, 16)
        return bool(bits >> code & 1)
    except Exception:
        return False


def _is_pointer(path: str) -> bool:
    """Só abre dispositivos que declaram botão esquerdo de mouse."""
    name = os.path.basename(path)
    try:
        with open(f"/sys/class/input/{name}/device/capabilities/key", encoding="ascii") as fh:
            words = fh.read().split()
        bits = 0
        for word in words:
            bits = (bits << 64) | int(word, 16)
        return bool(bits >> BTN_LEFT & 1)
    except Exception:
        return False


class ClickWatcher(QObject):
    clicked = Signal(str)  # left | right | middle
    released = Signal(str)
    combo = Signal(str)  # ex.: "Ctrl + Shift + S" (ao pressionar)
    combo_released = Signal()  # ao soltar a tecla principal

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fds: list[int] = []
        self._notifiers: list[QSocketNotifier] = []
        self._held: set[str] = set()
        self._shown: int | None = None
        self.want_clicks = False
        self.want_keys = False

    @property
    def running(self) -> bool:
        return bool(self._fds)

    def configure(self, clicks: bool, keys: bool) -> bool:
        """(Re)abre os dispositivos necessários. Retorna False se não houver acesso a /dev/input."""
        if (clicks, keys) == (self.want_clicks, self.want_keys) and (self._fds or not (clicks or keys)):
            return True
        self.want_clicks, self.want_keys = clicks, keys
        if not (clicks or keys):
            self.stop()
            return True
        return self.start()

    def start(self) -> bool:
        self.stop()
        self._held.clear()
        for path in sorted(glob.glob("/dev/input/event*")):
            pointer = self.want_clicks and _is_pointer(path)
            keyboard = self.want_keys and _has_key(path, 30) and _has_key(path, 28)
            if not (pointer or keyboard):
                continue
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            notifier = QSocketNotifier(fd, QSocketNotifier.Read, self)
            notifier.activated.connect(lambda *_args, fd=fd: self._read(fd))
            self._fds.append(fd)
            self._notifiers.append(notifier)
        return bool(self._fds)

    def _read(self, fd: int) -> None:
        try:
            data = os.read(fd, _EVENT.size * 64)
        except OSError:
            return
        for off in range(0, len(data) - _EVENT.size + 1, _EVENT.size):
            _s, _us, etype, code, value = _EVENT.unpack_from(data, off)
            if etype != EV_KEY:
                continue
            if code in _NAMES:
                if self.want_clicks:
                    if value == 1:
                        self.clicked.emit(_NAMES[code])
                    elif value == 0:
                        self.released.emit(_NAMES[code])
            elif self.want_keys:
                self._key(code, value)

    def _key(self, code: int, value: int) -> None:
        mod = _MODS.get(code)
        if mod:
            if value == 0:
                self._held.discard(mod)
            else:
                self._held.add(mod)
            return
        if value == 0 and code == self._shown:
            self._shown = None
            self.combo_released.emit()
            return
        if value != 1 or code not in _KEYS:
            return
        strong = self._held & {"Ctrl", "Alt", "Super"}
        if not strong and code not in _ALONE:
            return  # digitação comum (inclui senhas) nunca é exibida
        mods = [m for m in _MOD_ORDER if m in self._held]
        self._shown = code
        self.combo.emit(" + ".join(mods + [_KEYS[code]]))

    def stop(self) -> None:
        for notifier in self._notifiers:
            notifier.setEnabled(False)
            notifier.deleteLater()
        for fd in self._fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self._fds, self._notifiers = [], []
        self._held.clear()


if sys.platform.startswith("win"):
    # no Windows não existe /dev/input: mesma interface, por consulta ao estado das teclas
    from .win import WinInputWatcher as ClickWatcher  # noqa: E402,F811
elif sys.platform == "darwin":
    from .mac import MacInputWatcher as ClickWatcher  # noqa: E402,F811
