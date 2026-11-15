"""Integrações com o Windows: atalhos globais, cliques/teclas, janelas fora da captura e monitores.

Tudo por ctypes (sem dependências extras). O módulo pode ser importado em qualquer sistema,
mas as funções só fazem efeito no Windows.
"""
from __future__ import annotations

import ctypes
import os
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, QTimer, Signal

IS_WINDOWS = sys.platform.startswith("win")
WDA_EXCLUDEFROMCAPTURE = 0x11  # Windows 10 2004+: a janela aparece na tela, mas não em capturas
WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 1, 2, 4, 8, 0x4000

_user32 = ctypes.windll.user32 if IS_WINDOWS else None  # type: ignore[attr-defined]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint), ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint), ("pt", _POINT),
    ]


def exclude_from_capture(widget) -> bool:
    """Mantém a janela visível para o usuário e fora do vídeo gravado."""
    if not IS_WINDOWS:
        return False
    try:
        return bool(_user32.SetWindowDisplayAffinity(ctypes.c_void_p(int(widget.winId())), WDA_EXCLUDEFROMCAPTURE))
    except Exception:  # noqa: BLE001
        return False


def monitor_handle(x: int, y: int) -> int:
    """HMONITOR do monitor que contém o ponto (coordenadas nativas)."""
    if not IS_WINDOWS:
        return 0
    try:
        _user32.MonitorFromPoint.restype = ctypes.c_void_p
        return int(_user32.MonitorFromPoint(_POINT(int(x), int(y)), 2) or 0)  # MONITOR_DEFAULTTONEAREST
    except Exception:  # noqa: BLE001
        return 0


def find_program(exe: str, *folders: str) -> str | None:
    """Procura um executável nas pastas usuais de instalação (Arquivos de Programas)."""
    roots = [os.environ.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
    for root in filter(None, roots):
        for folder in folders:
            for base in (root, os.path.join(root, "Programs")):
                path = os.path.join(base, folder, exe)
                if os.path.isfile(path):
                    return path
    return None


# -- atalhos globais -----------------------------------------------------------------
_VK = {
    "space": 0x20, "tab": 0x09, "return": 0x0D, "enter": 0x0D, "esc": 0x1B, "escape": 0x1B, "backspace": 0x08,
    "del": 0x2E, "delete": 0x2E, "ins": 0x2D, "insert": 0x2D, "home": 0x24, "end": 0x23, "pgup": 0x21, "pgdown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "print": 0x2C, "pause": 0x13,
    "=": 0xBB, "+": 0xBB, "-": 0xBD, ",": 0xBC, ".": 0xBE, "/": 0xBF, ";": 0xBA, "[": 0xDB, "]": 0xDD, "\\": 0xDC,
    "'": 0xDE, "`": 0xC0,
}
_MODS = {"ctrl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "meta": MOD_WIN}


def parse_shortcut(seq: str) -> tuple[int, int] | None:
    """'Ctrl+Alt+X' -> (modificadores, tecla virtual)."""
    seq = (seq or "").strip()
    if not seq:
        return None
    key = "+" if seq.endswith("++") or seq == "+" else seq.rsplit("+", 1)[-1]
    head = seq[: -len(key)].rstrip("+") if len(seq) > len(key) else ""
    mods = 0
    for part in filter(None, head.split("+")):
        if part.lower() not in _MODS:
            return None
        mods |= _MODS[part.lower()]
    low = key.lower()
    if len(key) == 1 and key.isalnum():
        return mods, ord(key.upper())
    if low.startswith("f") and low[1:].isdigit() and 1 <= int(low[1:]) <= 24:
        return mods, 0x70 + int(low[1:]) - 1
    if low in _VK:
        return mods, _VK[low]
    return None


class _HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def nativeEventFilter(self, _event_type, message):
        try:
            msg = _MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self.callback(int(msg.wParam))
        except Exception:  # noqa: BLE001
            pass
        return False, 0


class WinHotkeys(QObject):
    """Atalhos globais pelo RegisterHotKey (valem com qualquer janela em foco)."""

    triggered = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ids: dict[int, str] = {}
        self._filter = _HotkeyFilter(self._fired)
        app = QCoreApplication.instance()
        if IS_WINDOWS and app is not None:
            app.installNativeEventFilter(self._filter)

    def _fired(self, hotkey_id: int) -> None:
        action = self._ids.get(hotkey_id)
        if action:
            self.triggered.emit(action)

    def apply(self, shortcuts: dict[str, str]) -> None:
        self.clear()
        if not IS_WINDOWS:
            return
        next_id = 0xB000
        for action, seq in shortcuts.items():
            parsed = parse_shortcut(seq)
            if not parsed:
                continue
            mods, vk = parsed
            if _user32.RegisterHotKey(None, next_id, mods | MOD_NOREPEAT, vk):
                self._ids[next_id] = action
            next_id += 1

    def clear(self) -> None:
        if IS_WINDOWS:
            for hotkey_id in self._ids:
                _user32.UnregisterHotKey(None, hotkey_id)
        self._ids = {}


# -- cliques e combinações de teclas -------------------------------------------------
_BUTTONS = {0x01: "left", 0x02: "right", 0x04: "middle"}
_MOD_KEYS = [("Ctrl", (0x11,)), ("Super", (0x5B, 0x5C)), ("Alt", (0x12,)), ("Shift", (0x10,))]
_NAMED = {
    0x1B: "Esc", 0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x20: "Espaço", 0x2C: "PrtSc", 0x24: "Home", 0x26: "↑",
    0x21: "PgUp", 0x25: "←", 0x27: "→", 0x23: "End", 0x28: "↓", 0x22: "PgDn", 0x2D: "Insert", 0x2E: "Delete",
    0xBD: "-", 0xBB: "=", 0xDB: "[", 0xDD: "]", 0xBA: ";", 0xDE: "'", 0xC0: "`", 0xDC: "\\", 0xBC: ",", 0xBE: ".", 0xBF: "/",
}
_NAMED.update({0x70 + i: f"F{i + 1}" for i in range(12)})
_NAMED.update({c: chr(c) for c in range(0x30, 0x3A)})
_NAMED.update({c: chr(c) for c in range(0x41, 0x5B)})
_ALONE = {0x1B, 0x09, 0x0D, 0x2C, 0x2E} | {0x70 + i for i in range(12)}  # exibidas mesmo sem modificador


class WinInputWatcher(QObject):
    """Mesma interface do leitor de /dev/input do Linux, por consulta ao estado das teclas.
    Só combinações com Ctrl/Alt/Win e teclas especiais são exibidas; digitação comum é ignorada."""

    clicked = Signal(str)
    released = Signal(str)
    combo = Signal(str)
    combo_released = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.want_clicks = False
        self.want_keys = False
        self._down: set[int] = set()
        self._shown: int | None = None
        self.timer = QTimer(self)
        self.timer.setInterval(12)
        self.timer.timeout.connect(self._poll)

    @property
    def running(self) -> bool:
        return self.timer.isActive()

    def configure(self, clicks: bool, keys: bool) -> bool:
        self.want_clicks, self.want_keys = clicks, keys
        if not IS_WINDOWS:
            return False
        if clicks or keys:
            self._down.clear()
            self.timer.start()
        else:
            self.stop()
        return True

    def stop(self) -> None:
        self.timer.stop()
        self._down.clear()
        self._shown = None

    @staticmethod
    def _pressed(vk: int) -> bool:
        return bool(_user32.GetAsyncKeyState(vk) & 0x8000)

    def _poll(self) -> None:
        if self.want_clicks:
            for vk, name in _BUTTONS.items():
                now = self._pressed(vk)
                if now and vk not in self._down:
                    self._down.add(vk)
                    self.clicked.emit(name)
                elif not now and vk in self._down:
                    self._down.discard(vk)
                    self.released.emit(name)
        if not self.want_keys:
            return
        if self._shown is not None and not self._pressed(self._shown):
            self._down.discard(self._shown)
            self._shown = None
            self.combo_released.emit()
        mods = [name for name, vks in _MOD_KEYS if any(self._pressed(v) for v in vks)]
        strong = any(m in ("Ctrl", "Alt", "Super") for m in mods)
        for vk, name in _NAMED.items():
            now = self._pressed(vk)
            if now and vk not in self._down:
                self._down.add(vk)
                if strong or vk in _ALONE:
                    self._shown = vk
                    self.combo.emit(" + ".join(mods + [name]))
            elif not now:
                self._down.discard(vk)
