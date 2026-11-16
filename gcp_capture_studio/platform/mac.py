"""Integrações com o macOS: atalhos globais, cliques/teclas, janelas fora da captura e monitores.

Tudo por ctypes (Carbon, CoreGraphics e o runtime do Objective-C), sem dependências extras.
O módulo pode ser importado em qualquer sistema, mas as funções só fazem efeito no macOS.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import sys

from PySide6.QtCore import QObject, QTimer, Signal

IS_MAC = sys.platform == "darwin"


def _lib(path: str):
    try:
        return ctypes.CDLL(path)
    except OSError:
        return None


_objc = _lib(ctypes.util.find_library("objc") or "/usr/lib/libobjc.A.dylib") if IS_MAC else None
_cg = _lib("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics") if IS_MAC else None
_carbon = _lib("/System/Library/Frameworks/Carbon.framework/Carbon") if IS_MAC else None


# -- runtime do Objective-C ---------------------------------------------------------
def _msg(obj, selector: str, *args, restype=ctypes.c_void_p, argtypes=()):
    """[obj selector:args…] pelo objc_msgSend, com os tipos informados."""
    send = ctypes.cast(_objc.objc_msgSend, ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes))
    _objc.sel_registerName.restype = ctypes.c_void_p
    _objc.sel_registerName.argtypes = [ctypes.c_char_p]
    return send(obj, _objc.sel_registerName(selector.encode()), *args)


def exclude_from_capture(widget) -> bool:
    """Mantém a janela visível para o usuário e fora do vídeo gravado (NSWindowSharingNone)."""
    if _objc is None:
        return False
    try:
        view = ctypes.c_void_p(int(widget.winId()))
        window = _msg(view, "window")
        if not window:
            return False
        _msg(ctypes.c_void_p(window), "setSharingType:", 0, restype=None, argtypes=(ctypes.c_ulong,))
        return True
    except Exception:  # noqa: BLE001
        return False


# -- monitores ------------------------------------------------------------------------
class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


def displays() -> list[tuple[int, int, int, int]]:
    """Retângulos (x, y, largura, altura, em pontos) dos monitores, na ordem do CGGetActiveDisplayList,
    que é a mesma ordem usada pelo avfvideosrc em device-index."""
    if _cg is None:
        return []
    try:
        ids = (ctypes.c_uint32 * 16)()
        count = ctypes.c_uint32(0)
        _cg.CGGetActiveDisplayList.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        if _cg.CGGetActiveDisplayList(16, ids, ctypes.byref(count)) != 0:
            return []
        _cg.CGDisplayBounds.restype = _CGRect
        _cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
        out = []
        for i in range(count.value):
            r = _cg.CGDisplayBounds(ids[i])
            out.append((round(r.origin.x), round(r.origin.y), round(r.size.width), round(r.size.height)))
        return out
    except Exception:  # noqa: BLE001
        return []


def display_index(x: int, y: int) -> int:
    """Índice (para o avfvideosrc) do monitor cujo canto superior esquerdo é (x, y) em pontos."""
    rects = displays()
    for i, (dx, dy, _w, _h) in enumerate(rects):
        if (dx, dy) == (x, y):
            return i
    for i, (dx, dy, w, h) in enumerate(rects):
        if dx <= x < dx + w and dy <= y < dy + h:
            return i
    return 0


# -- teclas -----------------------------------------------------------------------------
# códigos virtuais do teclado do Mac (kVK_*)
_KEYCODES = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05, "z": 0x06, "x": 0x07, "c": 0x08, "v": 0x09,
    "b": 0x0B, "q": 0x0C, "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10, "t": 0x11, "1": 0x12, "2": 0x13, "3": 0x14,
    "4": 0x15, "6": 0x16, "5": 0x17, "=": 0x18, "+": 0x18, "9": 0x19, "7": 0x1A, "-": 0x1B, "8": 0x1C, "0": 0x1D,
    "]": 0x1E, "o": 0x1F, "u": 0x20, "[": 0x21, "i": 0x22, "p": 0x23, "return": 0x24, "enter": 0x24, "l": 0x25,
    "j": 0x26, "'": 0x27, "k": 0x28, ";": 0x29, "\\": 0x2A, ",": 0x2B, "/": 0x2C, "n": 0x2D, "m": 0x2E, ".": 0x2F,
    "tab": 0x30, "space": 0x31, "`": 0x32, "backspace": 0x33, "esc": 0x35, "escape": 0x35,
    "home": 0x73, "pgup": 0x74, "del": 0x75, "delete": 0x75, "end": 0x77, "pgdown": 0x79, "ins": 0x72, "insert": 0x72,
    "left": 0x7B, "right": 0x7C, "down": 0x7D, "up": 0x7E,
}
_FKEYS = [0x7A, 0x78, 0x63, 0x76, 0x60, 0x61, 0x62, 0x64, 0x65, 0x6D, 0x67, 0x6F, 0x69, 0x6B, 0x71, 0x6A, 0x40, 0x4F, 0x50, 0x5A]
for _i, _code in enumerate(_FKEYS):
    _KEYCODES[f"f{_i + 1}"] = _code

# modificadores do Carbon; no Qt para macOS "Ctrl" é a tecla Command e "Meta" é a Control
CMD_KEY, SHIFT_KEY, OPTION_KEY, CONTROL_KEY = 0x100, 0x200, 0x800, 0x1000
_MODS = {"ctrl": CMD_KEY, "alt": OPTION_KEY, "shift": SHIFT_KEY, "meta": CONTROL_KEY}


def parse_shortcut(seq: str) -> tuple[int, int] | None:
    """'Ctrl+Alt+X' -> (modificadores do Carbon, código virtual da tecla)."""
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
    code = _KEYCODES.get(key.lower())
    return (mods, code) if code is not None else None


# -- atalhos globais (Carbon RegisterEventHotKey: não exige permissão de acessibilidade) --
def _fourcc(text: str) -> int:
    return int.from_bytes(text.encode("ascii"), "big")


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_SIGNATURE = _fourcc("GCPc")


class MacHotkeys(QObject):
    """Atalhos globais (valem com qualquer aplicativo em foco)."""

    triggered = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ids: dict[int, str] = {}
        self._refs: list[ctypes.c_void_p] = []
        self._handler = _HANDLER(self._on_event)  # referência mantida: o Carbon chama de volta
        self._installed = False
        if _carbon is None:
            return
        try:
            _carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
            _carbon.InstallEventHandler.argtypes = [
                ctypes.c_void_p, _HANDLER, ctypes.c_ulong, ctypes.POINTER(_EventTypeSpec), ctypes.c_void_p, ctypes.c_void_p,
            ]
            spec = _EventTypeSpec(_fourcc("keyb"), 5)  # kEventClassKeyboard / kEventHotKeyPressed
            ref = ctypes.c_void_p()
            status = _carbon.InstallEventHandler(
                _carbon.GetApplicationEventTarget(), self._handler, 1, ctypes.byref(spec), None, ctypes.byref(ref)
            )
            self._installed = status == 0
        except Exception:  # noqa: BLE001
            self._installed = False

    @property
    def available(self) -> bool:
        return self._installed

    def _on_event(self, _call_ref, event, _data) -> int:
        try:
            hk = _EventHotKeyID()
            _carbon.GetEventParameter.argtypes = [
                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p,
            ]
            _carbon.GetEventParameter(
                event, _fourcc("----"), _fourcc("hkid"), None, ctypes.sizeof(hk), None, ctypes.byref(hk)
            )
            action = self._ids.get(hk.id)
            if action:
                QTimer.singleShot(0, lambda: self.triggered.emit(action))
        except Exception:  # noqa: BLE001
            pass
        return 0

    def apply(self, shortcuts: dict[str, str]) -> None:
        self.clear()
        if not self._installed:
            return
        _carbon.RegisterEventHotKey.argtypes = [
            ctypes.c_uint32, ctypes.c_uint32, _EventHotKeyID, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
        ]
        next_id = 1
        for action, seq in shortcuts.items():
            parsed = parse_shortcut(seq)
            if not parsed:
                continue
            mods, code = parsed
            ref = ctypes.c_void_p()
            status = _carbon.RegisterEventHotKey(
                code, mods, _EventHotKeyID(_SIGNATURE, next_id), _carbon.GetApplicationEventTarget(), 0, ctypes.byref(ref)
            )
            if status == 0:
                self._ids[next_id] = action
                self._refs.append(ref)
            next_id += 1

    def clear(self) -> None:
        if _carbon is not None:
            for ref in self._refs:
                try:
                    _carbon.UnregisterEventHotKey(ref)
                except Exception:  # noqa: BLE001
                    pass
        self._refs, self._ids = [], {}


# -- cliques e combinações de teclas (consulta ao estado, como no Windows) ----------
_STATE = 0  # kCGEventSourceStateCombinedSessionState
_BUTTONS = {0: "left", 1: "right", 2: "middle"}
_MOD_KEYS = [("Ctrl", (0x3B, 0x3E)), ("⌘", (0x37, 0x36)), ("Alt", (0x3A, 0x3D)), ("Shift", (0x38, 0x3C))]
_NAMED = {
    0x35: "Esc", 0x33: "Backspace", 0x30: "Tab", 0x24: "Enter", 0x31: "Espaço", 0x73: "Home", 0x7E: "↑", 0x74: "PgUp",
    0x7B: "←", 0x7C: "→", 0x77: "End", 0x7D: "↓", 0x79: "PgDn", 0x75: "Delete",
}
_NAMED.update({code: f"F{i + 1}" for i, code in enumerate(_FKEYS[:12])})
_NAMED.update({code: name.upper() for name, code in _KEYCODES.items() if len(name) == 1})
_ALONE = {0x35, 0x30, 0x24, 0x75} | set(_FKEYS[:12])  # exibidas mesmo sem modificador


class MacInputWatcher(QObject):
    """Mesma interface do leitor de /dev/input do Linux. Só combinações com Ctrl/⌘/Alt e teclas
    especiais são exibidas; digitação comum é ignorada."""

    clicked = Signal(str)
    released = Signal(str)
    combo = Signal(str)
    combo_released = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.want_clicks = False
        self.want_keys = False
        self._down: set = set()
        self._shown: int | None = None
        self.timer = QTimer(self)
        self.timer.setInterval(12)
        self.timer.timeout.connect(self._poll)
        if _cg is not None:
            _cg.CGEventSourceButtonState.restype = ctypes.c_bool
            _cg.CGEventSourceButtonState.argtypes = [ctypes.c_int32, ctypes.c_uint32]
            _cg.CGEventSourceKeyState.restype = ctypes.c_bool
            _cg.CGEventSourceKeyState.argtypes = [ctypes.c_int32, ctypes.c_uint16]

    @property
    def running(self) -> bool:
        return self.timer.isActive()

    def configure(self, clicks: bool, keys: bool) -> bool:
        self.want_clicks, self.want_keys = clicks, keys
        if _cg is None:
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
    def _key(code: int) -> bool:
        return bool(_cg.CGEventSourceKeyState(_STATE, code))

    def _poll(self) -> None:
        if self.want_clicks:
            for button, name in _BUTTONS.items():
                now = bool(_cg.CGEventSourceButtonState(_STATE, button))
                tag = ("b", button)
                if now and tag not in self._down:
                    self._down.add(tag)
                    self.clicked.emit(name)
                elif not now and tag in self._down:
                    self._down.discard(tag)
                    self.released.emit(name)
        if not self.want_keys:
            return
        if self._shown is not None and not self._key(self._shown):
            self._down.discard(self._shown)
            self._shown = None
            self.combo_released.emit()
        mods = [name for name, codes in _MOD_KEYS if any(self._key(c) for c in codes)]
        strong = any(m in ("Ctrl", "⌘", "Alt") for m in mods)
        for code, name in _NAMED.items():
            now = self._key(code)
            if now and code not in self._down:
                self._down.add(code)
                if strong or code in _ALONE:
                    self._shown = code
                    self.combo.emit(" + ".join(mods + [name]))
            elif not now:
                self._down.discard(code)
