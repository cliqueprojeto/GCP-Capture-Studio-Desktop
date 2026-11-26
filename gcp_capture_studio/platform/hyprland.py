"""Integração com o Hyprland (Omarchy e outras distribuições com Hyprland).

O Hyprland organiza as janelas lado a lado (tiling): sem regras próprias, cada janela do
programa (tela inicial, camada de anotações, barra, lupa, contagem…) viraria um bloco da grade.
Este módulo conversa com o compositor pelo socket de controle (o mesmo do `hyprctl`) para:

- registrar regras de janela: tudo do programa flutua, e as camadas de gravação ficam fixas,
  sem borda, sombra, animação ou foco;
- informar a posição global do ponteiro, a lista de janelas e os monitores com a escala real;
- registrar os atalhos globais e, sem acesso a /dev/input, os cliques do mouse.

Funciona com as duas gerações de configuração do Hyprland: Lua (`hyprctl eval`, Hyprland 0.55+,
usada pelo Omarchy) e hyprlang (`hyprctl keyword`, com a sintaxe de regras nova e a antiga).
"""
from __future__ import annotations

import json
import os
import shlex
import socket
import sys
import threading
import time

from PySide6.QtCore import QObject, QPoint, QRect, QSocketNotifier, QTimer, Signal

APP_CLASS = "gcp-capture-studio"
BIND_TAG = "GCP Capture Studio"  # descrição dos atalhos registrados pelo programa
STATE_NAME = "gcp-capture-studio-hyprland-{}.json"

# títulos das janelas (ver ui/*): camadas de gravação e janelas comuns
_OVERLAY_TITLES = r"GCP Capture Studio (·|—) .*"
_SELECTOR_TITLE = r"Selecionar área — GCP Capture Studio( \[[^\]]*\])?( — GCP Capture Studio)?"
_LAUNCHER_TITLE = r"GCP Capture Studio"
_TEXT_TITLE = r"Texto — GCP Capture Studio( — GCP Capture Studio)?"

# máscaras de modificadores do Hyprland (wlr)
_MODMASK = {"SHIFT": 1, "CTRL": 4, "ALT": 8, "SUPER": 64}
_QT_MODS = {"ctrl": "CTRL", "control": "CTRL", "alt": "ALT", "shift": "SHIFT", "meta": "SUPER", "super": "SUPER"}
_QT_KEYS = {
    "=": "equal", "-": "minus", "+": "plus", ",": "comma", ".": "period", "/": "slash", ";": "semicolon",
    "'": "apostrophe", "[": "bracketleft", "]": "bracketright", "\\": "backslash", "`": "grave",
    "space": "space", "esc": "Escape", "escape": "Escape", "return": "Return", "enter": "Return", "tab": "Tab",
    "backspace": "BackSpace", "del": "Delete", "delete": "Delete", "ins": "Insert", "insert": "Insert",
    "pgup": "Prior", "pgdown": "Next", "home": "Home", "end": "End", "up": "Up", "down": "Down",
    "left": "Left", "right": "Right", "print": "Print", "pause": "Pause",
}
MOUSE_BUTTONS = {"left": "mouse:272", "right": "mouse:273", "middle": "mouse:274"}

# mostrador de teclas sem acesso a /dev/input: combinações com Ctrl, Alt ou Super (digitação comum,
# inclusive senhas, nunca é capturada) registradas no Hyprland sem consumir a tecla
_COMBO_MODS = [["CTRL"], ["ALT"], ["SUPER"], ["CTRL", "SHIFT"], ["CTRL", "ALT"], ["SUPER", "SHIFT"], ["ALT", "SHIFT"], ["CTRL", "SUPER"]]
_COMBO_KEYS = (
    [chr(c) for c in range(ord("A"), ord("Z") + 1)] + [str(d) for d in range(10)] + [f"F{i}" for i in range(1, 13)]
    + ["Tab", "Return", "Escape", "space", "BackSpace", "Delete", "Left", "Right", "Up", "Down", "Home", "End",
       "Prior", "Next", "minus", "equal", "comma", "period", "slash", "semicolon", "apostrophe", "bracketleft",
       "bracketright", "backslash", "grave", "Print"]
)
_MOD_LABEL = {"CTRL": "Ctrl", "SUPER": "Super", "ALT": "Alt", "SHIFT": "Shift"}
_KEY_LABEL = {
    "Return": "Enter", "Escape": "Esc", "space": "Espaço", "BackSpace": "Backspace", "Left": "←", "Right": "→",
    "Up": "↑", "Down": "↓", "Prior": "PgUp", "Next": "PgDn", "minus": "-", "equal": "=", "comma": ",",
    "period": ".", "slash": "/", "semicolon": ";", "apostrophe": "'", "bracketleft": "[", "bracketright": "]",
    "backslash": "\\", "grave": "`", "Print": "PrtSc",
}


def combo_label(message: str) -> str:
    """"CTRL+SHIFT|S" → "Ctrl + Shift + S" (mesma ordem do mostrador por /dev/input)."""
    mods, _, key = message.partition("|")
    names = [_MOD_LABEL.get(m, m) for m in mods.split("+") if m]
    order = ["Ctrl", "Super", "Alt", "Shift"]
    names.sort(key=lambda n: order.index(n) if n in order else 9)
    return " + ".join(names + [_KEY_LABEL.get(key, key)])


# -- socket de controle -----------------------------------------------------------------------
def _socket_dir() -> str | None:
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not sig:
        return None
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    for base in (os.path.join(runtime, "hypr"), "/tmp/hypr"):
        path = os.path.join(base, sig)
        if os.path.exists(os.path.join(path, ".socket.sock")):
            return path
    return None


def state_path(ns: str) -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or os.path.expanduser("~/.cache")
    return os.path.join(runtime, STATE_NAME.format(ns))


def request(cmd: str, timeout: float = 1.0) -> str | None:
    """Envia um comando ao Hyprland (ex.: "j/monitors", "/eval ...") e devolve a resposta."""
    folder = _socket_dir()
    if folder is None:
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(os.path.join(folder, ".socket.sock"))
            s.sendall(cmd.encode("utf-8"))
            chunks = []
            while True:
                data = s.recv(65536)
                if not data:
                    break
                chunks.append(data)
        return b"".join(chunks).decode("utf-8", "replace")
    except OSError:
        return None


def query(what: str, timeout: float = 1.0):
    raw = request(f"j/{what}", timeout)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


_AVAILABLE: bool | None = None


def available() -> bool:
    """O compositor responde pelo socket de controle (com folga: logo após o login ele pode demorar)."""
    global _AVAILABLE
    if _AVAILABLE is None:
        _AVAILABLE = False
        if sys.platform.startswith("linux") and _socket_dir() is not None:
            for _ in range(3):
                if request("j/version", timeout=3.0):
                    _AVAILABLE = True
                    break
                time.sleep(0.3)
    return _AVAILABLE


def lua_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _ok(answer: str | None) -> bool:
    return answer is not None and answer.strip().startswith("ok")


class _Config:
    """Detecta o tipo de configuração do compositor e aplica comandos na sintaxe certa."""

    def __init__(self):
        answer = request("/eval return 1", timeout=3.0)
        if answer is None:
            answer = request("/eval return 1", timeout=3.0)
        self.lua = _ok(answer)
        self.new_rules = True  # hyprlang 0.53+: "windowrule = match:class ..., float on"

    def eval(self, code: str) -> bool:
        answer = request("/eval " + code, timeout=3.0)
        if answer is None:  # sem resposta (compositor ocupado): tenta de novo uma vez
            answer = request("/eval " + code, timeout=3.0)
        return _ok(answer)

    def keyword(self, name: str, value: str) -> bool:
        answer = request(f"/keyword {name} {value}", timeout=3.0)
        if answer is None:
            answer = request(f"/keyword {name} {value}", timeout=3.0)
        return _ok(answer)

    def batch_keywords(self, pairs: list[tuple[str, str]]) -> bool:
        ok = True
        for name, value in pairs:
            ok = self.keyword(name, value) and ok
        return ok


_CONFIG: _Config | None = None


def config() -> _Config:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = _Config()
    return _CONFIG


def force_zero_scaling() -> bool:
    opt = query("getoption xwayland:force_zero_scaling", 3.0) or query("getoption xwayland:force_zero_scaling", 3.0)
    if isinstance(opt, dict):
        for key in ("int", "bool", "value"):
            if key in opt:
                try:
                    return bool(int(opt[key]))
                except (TypeError, ValueError):
                    return str(opt[key]).lower() == "true"
    return False


def screen_scale_env() -> str:
    """Fatores de escala por monitor para o Qt (XWayland com force_zero_scaling, padrão do Omarchy).

    Nesse modo o XWayland trabalha em pixels reais e o Qt desenharia tudo minúsculo em telas HiDPI;
    com estes fatores a interface fica no tamanho certo e as coordenadas batem com as do compositor."""
    if not force_zero_scaling():
        return ""
    mons = query("monitors", 3.0) or []
    parts = []
    for m in mons:
        try:
            scale = float(m.get("scale") or 1.0)
        except (TypeError, ValueError):
            scale = 1.0
        if m.get("name"):
            parts.append(f"{m['name']}={scale:g}")
    return ";".join(parts) if any(not p.endswith("=1") for p in parts) else ""


def managed(flags):
    """No Hyprland, as camadas do programa são janelas gerenciadas, nunca override-redirect: estas não
    recebem o ponteiro quando são do tipo utilitário (são tratadas como dicas de ferramenta) e, com o
    XWayland em pixels reais (force_zero_scaling), são posicionadas e escaladas de forma errada.
    As regras abaixo mantêm as camadas flutuantes, fixas, sem moldura e, as que só exibem, sem foco."""
    from PySide6.QtCore import Qt

    if is_hyprland():
        return flags & ~Qt.X11BypassWindowManagerHint
    return flags


def _title_regex(title: str) -> str:
    esc = "".join("\\" + ch if ch in "\\.^$|?*+()[]{}" else ch for ch in title)
    return f"{esc}( — GCP Capture Studio)?"


def open_on_screen(widget, rect=None) -> None:
    """Antes de mostrar uma janela: diz ao Hyprland em qual monitor ela deve nascer.

    O Hyprland abre toda janela nova no monitor em foco e só depois atende o pedido de posição; com
    vários monitores, a camada de anotações nascia no monitor errado (os desenhos iam para lá) e o
    seletor de área empilhava todos os painéis num monitor só. Uma regra com o monitor certo, por título,
    resolve na origem."""
    if not is_hyprland():
        return
    from PySide6.QtGui import QGuiApplication

    try:
        g = rect if rect is not None else widget.geometry()
        screen = QGuiApplication.screenAt(g.center())
        title = widget.windowTitle()
    except RuntimeError:
        return
    if screen is None or not title:
        return
    name = screen.name()
    if _ASSIGNED.get(title) == name:
        return
    cfg = config()
    match = {"class": _CLASS, "title": _title_regex(title)}
    if cfg.lua:
        rule_name = "gcp-capture-studio-mon-" + "".join(ch if ch.isalnum() else "-" for ch in title.lower())[:60]
        ok = cfg.eval(_lua_rule(rule_name, match, {"monitor": name}))
    elif cfg.new_rules:
        ok = cfg.keyword("windowrule", _new_rule(match, {"monitor": name}))
    else:
        sel = ",".join(f"{k}:{_anchor(v)}" for k, v in match.items())
        ok = cfg.keyword("windowrulev2", f"monitor {name}, {sel}")
    if ok:
        _ASSIGNED[title] = name


_ASSIGNED: dict[str, str] = {}


def settle(widget, rect=None, stop_when_placed: bool = False) -> None:
    """Confirma a posição de uma janela logo depois de mapeada.

    O Hyprland trata uma janela X mapeada exatamente em (0,0) como "sem posição" e a centraliza;
    com o XWayland em pixels reais (force_zero_scaling) ele usa o tamanho em pixels, e uma camada do
    tamanho do monitor acaba deslocada para fora da tela. Pedidos de posição feitos depois do
    mapeamento são respeitados: confere onde o compositor pôs a janela e, se preciso, move alguns
    pixels e volta para o lugar certo (até ela estar no lugar)."""
    if not is_hyprland():
        return
    from PySide6.QtCore import QRect as _QRect

    target = _QRect(rect) if rect is not None else widget.geometry()
    title = widget.windowTitle()
    token = object()
    try:
        widget._settle_token = token  # o programa cancela (None) quando o usuário move ou redimensiona a janela
    except (AttributeError, RuntimeError):
        pass
    pid = os.getpid()
    state = {"until": time.monotonic() + 15.0}

    def placed() -> bool | None:
        clients = query("clients", 2.0)
        if clients is None:
            return None
        want = CoordMap().to_hypr(target.x(), target.y())
        mine = [c for c in clients if c.get("pid") == pid and c.get("mapped", True) and not c.get("hidden")
                and str(c.get("title", "")).startswith(title)]
        if not mine:
            return None  # ainda não mapeada
        return any(abs(c["at"][0] - want[0]) <= 2 and abs(c["at"][1] - want[1]) <= 2 for c in mine)

    def alive() -> bool:
        try:
            return widget.isVisible() and getattr(widget, "_settle_token", token) is token
        except RuntimeError:  # a janela já foi destruída (ex.: seletor de área fechado)
            return False

    def check() -> None:
        if not alive() or time.monotonic() > state["until"]:
            return
        ok = placed()
        if ok and stop_when_placed and state.get("opened"):
            return  # no lugar depois de mapeada: daqui em diante o usuário pode arrastá-la à vontade
        if ok is False:
            # ida e volta em instantes separados (o Qt ignora um pedido igual à posição que ainda supõe
            # ter) e com mais de 2 px (abaixo disso o Hyprland ignora a mudança)
            widget.setGeometry(target.translated(4, 4))
            QTimer.singleShot(120, lambda: alive() and widget.setGeometry(target))
        # continua vigiando por alguns segundos: o compositor pode reposicionar ao terminar de mapear
        QTimer.singleShot({True: 500, False: 250}.get(ok, 150), check)

    def nudge() -> None:
        if alive():
            widget.setGeometry(target.translated(4, 4))
            QTimer.singleShot(120, lambda: alive() and widget.setGeometry(target))

    # assim que o compositor terminar de mapear a janela (evento openwindow), confirma a posição
    ev = events()
    state["connected"] = True

    def release() -> None:
        if state.pop("connected", False):
            try:
                ev.opened.disconnect(on_open)
            except (RuntimeError, TypeError):
                pass

    def on_open(opened_title: str) -> None:
        if opened_title.startswith(title):
            state["opened"] = True
            release()
            QTimer.singleShot(30, nudge)

    ev.opened.connect(on_open)
    QTimer.singleShot(15000, release)
    QTimer.singleShot(60, check)


# -- regras de janela -------------------------------------------------------------------------
_CLASS = APP_CLASS
_FLOAT_ALL = {"float": True}
_LAUNCHER = {"border_size": 0, "no_shadow": True, "no_blur": True, "rounding": 0, "no_dim": True, "decorate": False}
# camadas de gravação (barra, webcam, miniatura do zoom, camada de desenho…): fixas e sem moldura
_OVERLAY = {
    "float": True, "pin": True, "border_size": 0, "no_shadow": True, "no_blur": True, "no_anim": True,
    "rounding": 0, "no_dim": True, "decorate": False, "no_initial_focus": True, "no_follow_mouse": True,
}
# camadas que só exibem (lupa, moldura do zoom, anotações, contagem): o clique atravessa
_PASSTHROUGH_TITLES = r"GCP Capture Studio (· lupa|· enquadramento do zoom|— anotações|— contagem)( — GCP Capture Studio)?"
_SELECTOR = {
    "float": True, "border_size": 0, "no_shadow": True, "no_blur": True, "no_anim": True, "rounding": 0,
    "no_dim": True, "decorate": False,
}
_TEXT = {"float": True, "pin": True, "border_size": 0, "no_shadow": True, "no_blur": True, "no_anim": True, "rounding": 0, "decorate": False}
_RULES = [
    ("gcp-capture-studio-float", {"class": _CLASS}, _FLOAT_ALL),
    ("gcp-capture-studio-launcher", {"class": _CLASS, "title": _LAUNCHER_TITLE}, _LAUNCHER),
    ("gcp-capture-studio-overlay", {"class": _CLASS, "title": _OVERLAY_TITLES}, _OVERLAY),
    ("gcp-capture-studio-passthrough", {"class": _CLASS, "title": _PASSTHROUGH_TITLES}, {"no_focus": True}),
    ("gcp-capture-studio-selector", {"class": _CLASS, "title": _SELECTOR_TITLE}, _SELECTOR),
    # campo de texto ao vivo: fixo e sem moldura, mas recebe o teclado
    ("gcp-capture-studio-text", {"class": _CLASS, "title": _TEXT_TITLE}, _TEXT),
]


def _lua_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return lua_str(str(v))


def _lua_rule(name: str, match: dict, effects: dict) -> str:
    m = ", ".join(f"{k} = {_lua_value(v if v != '' else '^$')}" for k, v in match.items())
    e = ", ".join(f"{k} = {_lua_value(v)}" for k, v in effects.items())
    return f"hl.window_rule({{ name = {lua_str(name)}, match = {{ {m} }}, {e} }})"


def _hyprlang_value(v) -> str:
    if isinstance(v, bool):
        return "on" if v else "off"
    return str(v)


def _anchor(pattern: str) -> str:
    return f"^({pattern})$" if pattern else "^$"


def _new_rule(match: dict, effects: dict) -> str:
    parts = [f"match:{k} {_anchor(v)}" for k, v in match.items()]
    parts += [f"{k} {_hyprlang_value(v)}" for k, v in effects.items()]
    return ", ".join(parts)


_OLD_NAMES = {
    "float": "float", "pin": "pin", "no_shadow": "noshadow", "no_blur": "noblur", "no_anim": "noanim",
    "no_dim": "nodim", "no_initial_focus": "noinitialfocus", "no_focus": "nofocus", "opaque": "opaque",
    "decorate": None, "no_follow_mouse": "nofollowmouse",
}


def _old_rules(match: dict, effects: dict) -> list[str]:
    sel = ",".join(f"{k}:{_anchor(v)}" for k, v in match.items())
    out = []
    for k, v in effects.items():
        if k == "border_size":
            out.append(f"noborder, {sel}")
        elif k == "rounding":
            out.append(f"rounding {v}, {sel}")
        elif k == "decorate":
            out.append(f"decorate 0, {sel}")
        elif _OLD_NAMES.get(k):
            out.append(f"{_OLD_NAMES[k]}, {sel}")
    return out


def install_rules() -> bool:
    """Registra as regras de janela do programa (idempotente; refeito após recarregar a configuração)."""
    cfg = config()
    if cfg.lua:
        code = "; ".join(_lua_rule(n, m, e) for n, m, e in _RULES)
        ok = cfg.eval(code)
        if not ok:  # alguma propriedade desconhecida nesta versão: aplica uma a uma
            ok = True
            for n, m, e in _RULES:
                if not cfg.eval(_lua_rule(n, m, e)):
                    ok = cfg.eval(_lua_rule(n, m, {k: v for k, v in e.items() if k in ("float", "pin", "border_size", "no_initial_focus", "no_focus", "no_follow_mouse")})) and ok
        # barra de título do plugin hyprbars (Omarchy): nunca nas janelas do programa
        cfg.eval(f'pcall(hl.window_rule, {{ name = "gcp-capture-studio-nobar", match = {{ class = {lua_str(_CLASS)} }}, ["hyprbars:no_bar"] = true }})')
        return ok
    if cfg.new_rules:
        ok = True
        for _n, m, e in _RULES:
            if not cfg.keyword("windowrule", _new_rule(m, e)):
                # propriedade desconhecida: repete só com o essencial
                essential = {k: v for k, v in e.items() if k in ("float", "pin", "border_size", "no_initial_focus", "no_focus", "no_follow_mouse")}
                if not cfg.keyword("windowrule", _new_rule(m, essential)):
                    ok = False
                    break
        if ok:
            return True
        cfg.new_rules = False
    ok = True
    for _n, m, e in _RULES:
        for rule in _old_rules(m, e):
            ok = cfg.keyword("windowrulev2", rule) and ok
    return ok


# -- coordenadas ---------------------------------------------------------------------------------
class CoordMap:
    """Converte coordenadas lógicas do Hyprland para as do Qt (XWayland), monitor a monitor.

    O XWayland pode usar pixels reais (force_zero_scaling) e posições próprias por monitor;
    a correspondência é feita pelo nome do monitor, que é o mesmo nos dois lados."""

    def __init__(self, monitors: list | None = None):
        from PySide6.QtGui import QGuiApplication

        self.items: list[tuple[QRect, QRect, dict]] = []
        mons = monitors if monitors is not None else (query("monitors") or [])
        screens = {s.name(): s for s in QGuiApplication.screens()} if QGuiApplication.instance() else {}
        for m in mons:
            scale = float(m.get("scale") or 1.0)
            w, h = int(m.get("width", 0)), int(m.get("height", 0))
            if int(m.get("transform", 0)) % 2 == 1:
                w, h = h, w
            hypr = QRect(int(m.get("x", 0)), int(m.get("y", 0)), round(w / scale), round(h / scale))
            sc = screens.get(m.get("name"))
            qt = sc.geometry() if sc is not None else QRect(hypr)
            self.items.append((hypr, qt, m))

    def to_qt(self, x: float, y: float) -> QPoint:
        best = None
        for hypr, qt, _m in self.items:
            if hypr.contains(int(x), int(y)):
                best = (hypr, qt)
                break
        if best is None and self.items:
            # fora de todos: o monitor mais próximo
            def dist(item):
                r = item[0]
                dx = max(r.left() - x, 0, x - r.right())
                dy = max(r.top() - y, 0, y - r.bottom())
                return dx * dx + dy * dy

            hypr, qt, _m = min(self.items, key=dist)
            best = (hypr, qt)
        if best is None:
            return QPoint(round(x), round(y))
        hypr, qt = best
        kx = qt.width() / max(1, hypr.width())
        ky = qt.height() / max(1, hypr.height())
        return QPoint(round(qt.x() + (x - hypr.x()) * kx), round(qt.y() + (y - hypr.y()) * ky))

    def to_hypr(self, x: float, y: float) -> tuple[float, float]:
        """Inverso de to_qt: ponto do Qt em coordenadas lógicas do Hyprland."""
        for hypr, qt, _m in self.items:
            if qt.contains(int(x), int(y)):
                kx = qt.width() / max(1, hypr.width())
                ky = qt.height() / max(1, hypr.height())
                return hypr.x() + (x - qt.x()) / kx, hypr.y() + (y - qt.y()) / ky
        return float(x), float(y)

    def rect_to_qt(self, x: float, y: float, w: float, h: float) -> QRect:
        a = self.to_qt(x, y)
        b = self.to_qt(x + w - 1, y + h - 1)
        return QRect(a, b)

    def monitor(self, name: str) -> dict | None:
        return next((m for _h, _q, m in self.items if m.get("name") == name), None)

    def monitor_at(self, x: int, y: int) -> dict | None:
        return next((m for h, _q, m in self.items if h.contains(x, y)), None)


# -- eventos (socket2): recarga da configuração -----------------------------------------------------
class _Events(QObject):
    reloaded = Signal()
    opened = Signal(str)  # título de uma janela do programa que acabou de ser mapeada

    def __init__(self):
        super().__init__()
        self._sock = None
        self._notifier = None
        self._buf = b""
        folder = _socket_dir()
        if folder is None:
            return
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(os.path.join(folder, ".socket2.sock"))
            s.setblocking(False)
        except OSError:
            return
        self._sock = s
        self._notifier = QSocketNotifier(s.fileno(), QSocketNotifier.Read, self)
        self._notifier.activated.connect(self._read)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.reloaded.emit)

    def _read(self, *_args) -> None:
        try:
            data = self._sock.recv(65536)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            self._notifier.setEnabled(False)
            return
        self._buf += data
        *lines, self._buf = self._buf.split(b"\n")
        if any(line.startswith(b"configreloaded>>") for line in lines):
            self._timer.start()  # agrupa recargas em sequência
        for line in lines:
            if line.startswith(b"openwindow>>"):
                parts = line[12:].decode("utf-8", "replace").split(",", 3)
                if len(parts) == 4 and parts[2] == APP_CLASS:
                    self.opened.emit(parts[3])


_EVENTS: _Events | None = None


def events() -> _Events:
    global _EVENTS
    if _EVENTS is None:
        _EVENTS = _Events()
    return _EVENTS


# -- atalhos e cliques -------------------------------------------------------------------------
def to_hypr_keys(seq: str) -> tuple[list[str], str] | None:
    """'Ctrl+Alt+Z' → (['CTRL', 'ALT'], 'Z'). Devolve None para sequências vazias ou inválidas."""
    seq = (seq or "").strip()
    if not seq:
        return None
    if seq.endswith("++"):
        parts, key = seq[:-2].split("+") if seq[:-2] else [], "+"
    else:
        *parts, key = seq.split("+")
    mods = []
    for p in parts:
        mod = _QT_MODS.get(p.strip().lower())
        if mod is None:
            return None
        mods.append(mod)
    key = key.strip()
    if not key:
        return None
    key = _QT_KEYS.get(key.lower(), _QT_KEYS.get(key, key))
    if len(key) == 1 and key.isalpha():
        key = key.upper()
    return mods, key


def _modmask(mods: list[str]) -> int:
    m = 0
    for mod in mods:
        m |= _MODMASK.get(mod, 0)
    return m


def sender_command(server: str, message: str) -> str:
    """Comando curto executado pelo Hyprland ao pressionar um atalho: avisa o programa em execução."""
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hyprsend.py")
    py = sys.executable if sys.executable and os.path.exists(sys.executable) else "python3"
    return " ".join(shlex.quote(a) for a in (py, "-I", "-S", script, server, message))


def _bind_namespace(desc: str) -> str | None:
    """Grupo de um atalho do programa pela descrição: "GCP Capture Studio [mouse] click_left"
    (versões anteriores: "GCP Capture Studio: click_left")."""
    rest = desc[len(BIND_TAG):]
    if rest.startswith(" [") and "]" in rest:
        return rest[2:rest.index("]")]
    ident = rest.lstrip(": ").strip()
    return "mouse" if ident.startswith("click_") else "combo" if ident.startswith("combo_") else "keys"


class Binds:
    """Atalhos registrados no Hyprland pelo programa. Nunca remove nem substitui atalhos do usuário:
    uma combinação já usada no sistema fica de fora (e é informada em `conflicts`)."""

    def __init__(self, ns: str = "keys"):
        self.ns = ns
        self.table = f"gcp_capture_binds_{ns}"
        self.cfg = config()
        self.active: dict[str, tuple[list[str], str]] = {}  # id → (mods, tecla)
        self.conflicts: set[str] = set()
        self._wanted: dict[str, tuple[str, str, bool]] = {}

    def _foreign(self) -> set[tuple[int, str]]:
        taken = set()
        for b in query("binds", 4.0) or []:
            if not isinstance(b, dict):
                continue
            desc = str(b.get("description", ""))
            arg = str(b.get("arg", ""))
            if desc.startswith(BIND_TAG) or "hyprsend.py" in arg:
                continue
            if b.get("submap"):
                continue
            key = str(b.get("key", ""))
            if key:
                taken.add((int(b.get("modmask", 0)), key.lower()))
        return taken

    def set(self, wanted: dict[str, tuple[str, str, bool]]) -> None:
        """wanted: id → (sequência Qt ou "mouse:272", comando, não consumir a tecla)."""
        self._wanted = dict(wanted)
        self.clear()
        if not wanted:
            return
        taken = self._foreign()
        self.conflicts = set()
        lua_parts = [f"{self.table} = {self.table} or {{}}"]
        unbind = []
        for ident, (seq, cmd, passthrough) in wanted.items():
            if isinstance(seq, tuple):
                mods, key = list(seq[0]), seq[1]
            elif seq.startswith("mouse:"):
                mods, key = [], seq
            else:
                parsed = to_hypr_keys(seq)
                if parsed is None:
                    continue
                mods, key = parsed
            if (_modmask(mods), key.lower()) in taken:
                self.conflicts.add(ident)
                continue
            desc = f"{BIND_TAG} [{self.ns}] {ident}"
            if self.cfg.lua:
                keys = " + ".join(mods + [key])
                opts = f"description = {lua_str(desc)}" + (", non_consuming = true" if passthrough else "")
                lua_parts.append(
                    f"table.insert({self.table}, hl.bind({lua_str(keys)}, hl.dsp.exec_cmd({lua_str(cmd)}), {{ {opts} }}))"
                )
            else:
                flag = "n" if passthrough else ""
                ok = self.cfg.keyword(f"bind{flag}d", f"{' '.join(mods)}, {key}, {desc}, exec, {cmd}")
                if not ok:
                    ok = self.cfg.keyword(f"bind{flag}", f"{' '.join(mods)}, {key}, exec, {cmd}")
                if not ok:
                    continue
                unbind.append(f"{' '.join(mods)}, {key}")
            self.active[ident] = (mods, key)
        if self.cfg.lua and len(lua_parts) > 1:
            if not self.cfg.eval("; ".join(lua_parts)):
                self.active.clear()
        self._save_state(unbind)

    def reapply(self) -> None:
        """Após recarregar a configuração do Hyprland, os atalhos dinâmicos somem: registra de novo."""
        if self._wanted:
            self.set(self._wanted)

    def clear(self) -> None:
        if self.cfg.lua:
            self.cfg.eval(f"for _, b in ipairs({self.table} or {{}}) do pcall(function() b:remove() end) end; {self.table} = {{}}")
        else:
            combos = {f"{' '.join(mods)}, {key}" for mods, key in self.active.values()}
            # atalhos deixados por uma execução anterior que fechou de forma inesperada
            for bd in query("binds", 4.0) or []:
                if not isinstance(bd, dict):
                    continue
                desc, arg = str(bd.get("description", "")), str(bd.get("arg", ""))
                if desc.startswith(BIND_TAG):
                    ns = _bind_namespace(desc)
                elif "hyprsend.py" in arg:  # sem descrição (bind sem "d"): pelo tipo da mensagem
                    ns = "mouse" if "click:" in arg else "combo" if "keys:" in arg else "keys"
                else:
                    ns = None
                if ns == self.ns:
                    mask = int(bd.get("modmask", 0))
                    mods = [m for m, bit in _MODMASK.items() if mask & bit]
                    combos.add(f"{' '.join(mods)}, {bd.get('key', '')}")
            for combo in combos:
                self.cfg.keyword("unbind", combo)
        self.active.clear()
        self._save_state([])

    def _save_state(self, unbind: list[str]) -> None:
        """Guarda o que limpar caso o programa feche de forma inesperada (usado por hyprsend.py)."""
        path = state_path(self.ns)
        try:
            if not self.active:
                if os.path.exists(path):
                    os.remove(path)
                return
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"lua": self.cfg.lua, "table": self.table, "unbind": unbind, "signature": os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")}, fh)
        except OSError:
            pass

    def display(self, ident: str) -> str:
        if ident not in self.active:
            return ""
        mods, key = self.active[ident]
        return " + ".join(mods + [key])


def raise_windows(prefixes: list[str], focus_prefix: str | None = None) -> int:
    """Traz para a frente, nesta ordem, as janelas do programa cujo título começa com cada prefixo.

    No XWayland a janela X que recebe o ponteiro é decidida pela pilha do próprio X, e o Hyprland
    ignora o raise() de janelas gerenciadas: sem isto, uma janela focada antes (por exemplo, a que
    está atrás do seletor de área) continuaria recebendo o mouse. `focus_prefix`: também dá o foco
    (à janela com esse prefixo que estiver sob o ponteiro)."""
    clients = query("clients", 2.0)
    if not clients:
        return 0
    cfg, pid = config(), os.getpid()
    mine = [c for c in clients if c.get("pid") == pid and c.get("mapped", True) and not c.get("hidden")]
    done = 0

    def dispatch(lua: str, legacy: str) -> None:
        if cfg.lua:
            cfg.eval(f"hl.dispatch({lua})")
        else:
            request(f"/dispatch {legacy}")

    for prefix in prefixes:
        for c in mine:
            if str(c.get("title", "")).startswith(prefix):
                a = c.get("address")
                dispatch(f'hl.dsp.window.alter_zorder({{ mode = "top", window = "address:{a}" }})', f"alterzorder top,address:{a}")
                done += 1
    if focus_prefix:
        pos = query("cursorpos") or {}
        px, py = pos.get("x", 0), pos.get("y", 0)
        for c in mine:
            (x, y), (w, h) = c.get("at", (0, 0)), c.get("size", (0, 0))
            if str(c.get("title", "")).startswith(focus_prefix) and x <= px < x + w and y <= py < y + h:
                a = c.get("address")
                dispatch(f'hl.dsp.focus({{ window = "address:{a}" }})', f"focuswindow address:{a}")
                break
    return done


def diagnostic_path() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "gcp-capture-studio", "hyprland-diagnostico.txt")


def diagnose(event: str, widgets: dict) -> None:
    """Registra onde cada camada está segundo o Qt e segundo o Hyprland (para investigar problemas de
    posição/escala com vários monitores). Arquivo: ~/.cache/gcp-capture-studio/hyprland-diagnostico.txt"""
    try:
        from PySide6.QtGui import QGuiApplication

        lines = [f"== {time.strftime('%Y-%m-%d %H:%M:%S')} {event}"]
        ver = query("version", 2.0) or {}
        lines.append(f"hyprland {ver.get('tag', '?')} lua={config().lua} zero_scaling={force_zero_scaling()} "
                     f"QT_SCREEN_SCALE_FACTORS={os.environ.get('QT_SCREEN_SCALE_FACTORS', '')!r}")
        for m in query("monitors", 2.0) or []:
            lines.append(f"monitor {m.get('name')} {m.get('width')}x{m.get('height')} em {m.get('x')},{m.get('y')} "
                         f"escala {m.get('scale')} transform {m.get('transform')} foco {m.get('focused')}")
        for sc in QGuiApplication.screens():
            g = sc.geometry()
            lines.append(f"qt-tela {sc.name()} {g.width()}x{g.height()} em {g.x()},{g.y()} dpr {sc.devicePixelRatio()}")
        for name, w in widgets.items():
            try:
                g = w.geometry()
                lines.append(f"qt {name}: visivel={w.isVisible()} {g.width()}x{g.height()} em {g.x()},{g.y()} "
                             f"dpr={w.devicePixelRatio()} tela={w.screen().name() if w.screen() else None} titulo={w.windowTitle()!r}")
            except RuntimeError:
                pass
        pid = os.getpid()
        for c in query("clients", 2.0) or []:
            if c.get("pid") != pid:
                continue
            lines.append(f"hypr {c.get('title', '')[:48]!r}: em {c.get('at')} tam {c.get('size')} monitor {c.get('monitor')} "
                         f"flutua={c.get('floating')} fixa={c.get('pinned')} mapeada={c.get('mapped')} oculta={c.get('hidden')} "
                         f"ws={(c.get('workspace') or {}).get('id')}")
        path = diagnostic_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > 400_000:
            os.remove(path)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except Exception:  # noqa: BLE001 — diagnóstico nunca pode atrapalhar a gravação
        pass


# -- ponte com a mesma interface da ponte do KWin --------------------------------------------------
class HyprlandBridge(QObject):
    pointer = Signal(QPoint)
    windows = Signal(list)
    marked = Signal(int)
    screens = Signal(list)
    clicked = Signal(str)  # cliques recebidos pelos atalhos do mouse (sem acesso a /dev/input)

    kind = "hyprland"
    can_exclude = False  # o Hyprland cobre de preto as janelas ocultas no compartilhamento

    def __init__(self, parent=None):
        super().__init__(parent)
        self.available = available()
        self._map: CoordMap | None = None
        self._last = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._mouse = Binds("mouse") if self.available else None
        self._combo = Binds("combo") if self.available else None
        self._server = ""
        if self.available:
            install_rules()
            events().reloaded.connect(self._reloaded)

    def _reloaded(self) -> None:
        _ASSIGNED.clear()
        install_rules()
        for b in (self._mouse, self._combo):
            if b is not None:
                b.reapply()

    def set_server(self, name: str) -> None:
        """Endereço do programa em execução (QLocalServer) para os comandos dos atalhos."""
        self._server = name

    # -- ponteiro --------------------------------------------------------------------------
    def start_pointer(self) -> bool:
        """Acompanha o ponteiro (~80 vezes por segundo) numa thread própria: uma consulta lenta ao
        compositor nunca trava a interface nem a gravação."""
        if not self.available:
            return False
        self._map = CoordMap()
        self._last = None
        if self._thread is None or not self._thread.is_alive():
            self._running = True
            self._thread = threading.Thread(target=self._loop, name="gcp-hyprland-pointer", daemon=True)
            self._thread.start()
        return True

    def stop_pointer(self) -> None:
        self._running = False
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(0.5)

    def _loop(self) -> None:
        cmap = self._map
        while self._running:
            started = time.monotonic()
            raw = request("j/cursorpos", timeout=0.5)
            if raw:
                try:
                    pos = json.loads(raw)
                    key = (pos.get("x"), pos.get("y"))
                    if key != self._last and cmap is not None:
                        self._last = key
                        self.pointer.emit(cmap.to_qt(float(pos.get("x", 0)), float(pos.get("y", 0))))
                except (ValueError, AttributeError, TypeError):
                    pass
            time.sleep(max(0.0, 0.0125 - (time.monotonic() - started)))

    # -- janelas e monitores -------------------------------------------------------------------
    def request_windows(self) -> bool:
        if not self.available:
            return False
        clients = query("clients", 3.0)
        if clients is None:
            return False
        mons = query("monitors", 3.0) or []
        cmap = CoordMap(mons)
        visible = {int((m.get("activeWorkspace") or {}).get("id", -1)) for m in mons}
        visible |= {int((m.get("specialWorkspace") or {}).get("id", 0)) for m in mons if (m.get("specialWorkspace") or {}).get("id")}
        active = (query("activewindow", 3.0) or {}).get("address")
        out = []
        for c in clients:
            if not c.get("mapped", True) or c.get("hidden"):
                continue
            ws = int((c.get("workspace") or {}).get("id", -1))
            if ws not in visible and not c.get("pinned"):
                continue
            (x, y), (w, h) = c.get("at", (0, 0)), c.get("size", (0, 0))
            if w < 32 or h < 32:
                continue
            r = cmap.rect_to_qt(x, y, w, h)
            out.append({
                "title": str(c.get("title", "")), "app": str(c.get("class", "")),
                "x": r.x(), "y": r.y(), "w": r.width(), "h": r.height(),
                "active": c.get("address") == active,
            })
        # janelas flutuantes ficam por cima: primeiro na lista para o clique escolher a de cima
        QTimer.singleShot(0, lambda: self.windows.emit(out))
        return True

    def request_screens(self) -> bool:
        if not self.available:
            return False
        mons = query("monitors") or []
        out = [{"name": m.get("name"), "x": m.get("x"), "y": m.get("y"), "w": m.get("width"), "h": m.get("height"),
                "scale": float(m.get("scale") or 1.0)} for m in mons]
        QTimer.singleShot(0, lambda: self.screens.emit(out))
        return True

    def pixel_size(self, screen_name: str) -> tuple[int, int] | None:
        """Tamanho real (em pixels) do monitor: é o tamanho do fluxo entregue pelo portal."""
        for m in query("monitors") or []:
            if m.get("name") == screen_name:
                w, h = int(m.get("width", 0)), int(m.get("height", 0))
                if int(m.get("transform", 0)) % 2 == 1:
                    w, h = h, w
                return w, h
        return None

    def monitor_name_at(self, x: int, y: int) -> str | None:
        """Monitor que contém o ponto em coordenadas lógicas do Hyprland (posição informada pelo portal)."""
        m = CoordMap().monitor_at(x, y)
        return m.get("name") if m else None

    # -- exclusão da captura e efeitos -----------------------------------------------------------
    def hide_from_capture(self, _caption_prefix: str) -> bool:
        QTimer.singleShot(0, lambda: self.marked.emit(0))
        return True

    def set_effect(self, _name: str, _on: bool) -> bool:
        return False

    def effect_loaded(self, _name: str) -> bool:
        return False

    def watch_clicks(self, on: bool) -> bool:
        """Sem acesso a /dev/input: o Hyprland avisa cada clique (atalho do mouse que não consome o clique)."""
        if self._mouse is None or not self._server:
            return False
        if on:
            self._mouse.set({
                f"click_{name}": (button, sender_command(self._server, f"click:{name}"), True)
                for name, button in MOUSE_BUTTONS.items()
            })
            return bool(self._mouse.active)
        self._mouse._wanted = {}
        self._mouse.clear()
        return True

    def restack(self, prefixes: list[str], focus_prefix: str | None = None) -> None:
        if self.available:
            raise_windows(prefixes, focus_prefix)

    def watch_keys(self, on: bool, skip: set | None = None) -> bool:
        """Sem acesso a /dev/input: o Hyprland avisa as combinações com Ctrl/Alt/Super (sem consumi-las).
        `skip`: combinações (modmask, tecla) que já são atalhos do próprio programa."""
        if self._combo is None or not self._server:
            return False
        if not on:
            self._combo._wanted = {}
            self._combo.clear()
            return True
        skip = skip or set()
        wanted = {}
        for mods in _COMBO_MODS:
            for key in _COMBO_KEYS:
                if (_modmask(mods), key.lower()) in skip:
                    continue
                msg = "keys:" + "+".join(mods) + "|" + key
                wanted[f"combo_{'_'.join(mods)}_{key}"] = ((mods, key), sender_command(self._server, msg), True)
        self._combo.set(wanted)
        return bool(self._combo.active)

    def shutdown(self) -> None:
        self.stop_pointer()
        if self._combo is not None:
            self._combo._wanted = {}
            self._combo.clear()
        if self._mouse is not None:
            self._mouse._wanted = {}
            self._mouse.clear()


def is_hyprland() -> bool:
    return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")) and _socket_dir() is not None


__all__ = [
    "HyprlandBridge", "Binds", "CoordMap", "available", "install_rules", "is_hyprland", "query", "request",
    "screen_scale_env", "sender_command", "to_hypr_keys",
]
