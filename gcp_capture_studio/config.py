"""Configurações persistentes (JSON em ~/.config/gcp-capture-studio/settings.json)."""
from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, Signal


def _videos_dir() -> str:
    try:
        out = subprocess.run(["xdg-user-dir", "VIDEOS"], capture_output=True, text=True, timeout=2)
        base = out.stdout.strip()
        if base and os.path.isdir(base):
            return os.path.join(base, "GCP Capture Studio")
    except Exception:
        pass
    return str(Path.home() / "Videos" / "GCP Capture Studio")


# id -> (rótulo, grupo, atalho padrão)
SHORTCUT_ACTIONS: dict[str, tuple[str, str, str]] = {
    "record_pause": ("Iniciar / pausar / retomar gravação", "Gravação", "F9"),
    "record_stop": ("Parar gravação e enviar ao editor", "Gravação", "F10"),
    "toggle_bar": ("Mostrar / ocultar barra de ferramentas", "Gravação", "Ctrl+Alt+D"),
    "tool_cursor": ("Cursor (interagir com a tela)", "Ferramentas", "Alt+1"),
    "tool_pen": ("Caneta", "Ferramentas", "Alt+2"),
    "tool_highlighter": ("Marca-texto", "Ferramentas", "Alt+3"),
    "tool_arrow": ("Seta", "Ferramentas", "Alt+4"),
    "tool_line": ("Linha", "Ferramentas", "Alt+5"),
    "tool_rect": ("Retângulo", "Ferramentas", "Alt+6"),
    "tool_ellipse": ("Elipse", "Ferramentas", "Alt+7"),
    "tool_text": ("Texto", "Ferramentas", "Alt+8"),
    "tool_blur": ("Desfoque (blur)", "Ferramentas", "Alt+9"),
    "clear": ("Limpar todos os desenhos", "Ferramentas", "Alt+0"),
    "undo": ("Desfazer", "Ferramentas", "Ctrl+Alt+Z"),
    "redo": ("Refazer", "Ferramentas", "Ctrl+Alt+Y"),
    "fx_magnifier": ("Lupa", "Efeitos do mouse", "Ctrl+Alt+L"),
    "fx_zoom": ("Zoom acompanhando o mouse (liga/desliga)", "Efeitos do mouse", "Ctrl+Alt+X"),
    "zoom_in": ("Aumentar o zoom", "Efeitos do mouse", "Ctrl+Alt+="),
    "zoom_out": ("Diminuir o zoom", "Efeitos do mouse", "Ctrl+Alt+-"),
    "fx_spotlight": ("Holofote", "Efeitos do mouse", "Ctrl+Alt+S"),
    "fx_highlight": ("Destaque do cursor", "Efeitos do mouse", "Ctrl+Alt+H"),
    "fx_click": ("Efeito de clique", "Efeitos do mouse", "Ctrl+Alt+C"),
    "fx_keys": ("Mostrar combinações de teclas", "Efeitos do mouse", "Ctrl+Alt+K"),
}


def default_shortcuts() -> dict[str, str]:
    return {k: v[2] for k, v in SHORTCUT_ACTIONS.items()}


DEFAULTS: dict = {
    "capture": {
        "mode": "fullscreen",  # fullscreen | window | region
        "monitor": "",  # monitor gravado em tela inteira ("" = onde está a janela do aplicativo)
        "region": None,  # [x, y, w, h] em coordenadas globais
        "countdown": 3,
        "output_dir": _videos_dir(),
        "bar_mode": "widget",  # widget (discreto, expansível) | hidden (só bandeja e atalhos)
        "bar_pos": None,  # posição escolhida pelo usuário [x, y]
        "show_cursor": True,
    },
    "video": {
        "fps": 30,
        "quality": "alta",  # baixa | media | alta | maxima
        "encoder": "auto",  # auto | <id do encoder>
    },
    "audio": {
        "mic_enabled": True,
        "mic_device": "default",
        "mic_volume": 100,
        "sys_enabled": True,
        "sys_device": "default",
        "sys_volume": 100,
        "monitor_device": "default",
    },
    "webcam": {
        "enabled": False, "device": "", "size": 240, "shape": "circle",  # circle | oval | square | wide
        "border": 4, "border_color": "#ffffff", "mirror": True, "pos": None,
    },
    "effects": {
        "click": True,
        "click_color": "#63c1ee",
        "click_right_color": "#f59e0b",
        "click_size": 34,
        "highlight": False,
        "highlight_color": "#facc15",
        "highlight_size": 34,
        "highlight_opacity": 45,
        "spotlight": False,
        "spotlight_size": 170,
        "spotlight_dim": 62,
        "keys": False,
        "keys_size": 30,
        "keys_duration": 1.2,  # segundos em tela após soltar as teclas
        "keys_style": "keycap",  # keycap (teclas em relevo) | dark (faixa escura)
        "keys_anim": "pop",  # pop | fade | slide
        "magnifier": False,
        "magnifier_size": 220,
        "magnifier_zoom": 2.0,
        "zoom": False,  # zoom do vídeo inteiro acompanhando o ponteiro (efeito "pan")
        "zoom_level": 2.0,
        "zoom_frame": True,  # moldura na tela mostrando a área enquadrada (fora do vídeo)
        "zoom_preview": True,  # miniatura ao vivo do vídeo com zoom (fora do vídeo)
        "zoom_preview_size": 320,
        "zoom_preview_pos": None,
    },
    "tools": {"color": "#ef4444", "width": 5, "text_size": 28, "blur_strength": 14},
    "editor": {"app": "kdenlive", "auto_open": True, "close_after": True},
    "shortcuts": default_shortcuts(),
    "portal": {"tokens": {}},  # permissão de captura lembrada por monitor
    "updates": {"frequency": "startup", "last_check": ""},  # startup | daily | weekly | never
    "ui": {"first_run": True},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Settings(QObject):
    """Acesso por caminho pontuado: settings.get('video.fps')."""

    changed = Signal(str)

    def __init__(self, path: str | None = None):
        super().__init__()
        cfg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        self.path = Path(path) if path else Path(cfg) / "gcp-capture-studio" / "settings.json"
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                self.data = _merge(DEFAULTS, json.load(fh))
        except FileNotFoundError:
            pass
        except Exception:
            self.data = copy.deepcopy(DEFAULTS)
        # garante que ações novas tenham atalho
        for k, v in default_shortcuts().items():
            self.data["shortcuts"].setdefault(k, v)

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def get(self, key: str, default=None):
        node = self.data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, key: str, value, save: bool = True) -> None:
        parts = key.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        if node.get(parts[-1]) == value:
            return
        node[parts[-1]] = value
        if save:
            self.save()
        self.changed.emit(key)

    def reset_shortcuts(self) -> None:
        self.data["shortcuts"] = default_shortcuts()
        self.save()
        self.changed.emit("shortcuts")
