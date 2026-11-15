"""Dispositivos de áudio (microfones, interfaces USB, saída do sistema), medidor de nível e teste de microfone."""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402
from PySide6.QtCore import QObject, QTimer, Signal

Gst.init(None)


@dataclass(frozen=True)
class AudioDevice:
    name: str  # identificador PulseAudio/PipeWire
    label: str
    monitor: str = ""  # para saídas: fonte de monitoramento (som do sistema)


WINDOWS = sys.platform.startswith("win")


def source_fragment(device: str, client: str = "GCP Capture Studio", loopback: bool = False) -> str:
    """Trecho de pipeline que captura o dispositivo. No Linux a saída do sistema é gravada pela fonte
    de monitoramento; no Windows, pelo modo loopback do WASAPI."""
    if WINDOWS:
        return "wasapi2src low-latency=false" + (" loopback=true" if loopback else "")
    return f'pulsesrc device="{device}" client-name="{client}"'


def sink_fragment(device: str = "") -> str:
    if WINDOWS:
        return "autoaudiosink"
    return f'pulsesink device="{device}"' if device and device != "default" else "pulsesink"


def _pactl(*args) -> list | str:
    try:
        out = subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=3)
        return out.stdout
    except Exception:
        return ""


def _json(kind: str) -> list:
    try:
        return json.loads(_pactl("-f", "json", "list", kind) or "[]")
    except Exception:
        return []


def _label(item: dict) -> str:
    desc = item.get("description")
    if desc and desc != "(null)":
        return desc
    props = item.get("properties") or {}
    return (
        props.get("device.description")
        or props.get("node.description")
        or props.get("alsa.card_name")
        or item.get("name", "?")
    )


def microphones() -> list[AudioDevice]:
    """Entradas reais (microfones internos, headsets e interfaces de áudio USB)."""
    return [
        AudioDevice(s["name"], _label(s))
        for s in _json("sources")
        if not s.get("name", "").endswith(".monitor")
        and (s.get("properties") or {}).get("device.class", "") != "monitor"
    ]


def outputs() -> list[AudioDevice]:
    """Saídas (alto-falantes, fones, interfaces USB) com a respectiva fonte de monitoramento."""
    return [AudioDevice(s["name"], _label(s), s.get("monitor_source") or s["name"] + ".monitor") for s in _json("sinks")]


def default_source() -> str:
    return str(_pactl("get-default-source")).strip()


def default_sink() -> str:
    return str(_pactl("get-default-sink")).strip()


def resolve_mic(name: str) -> str:
    if WINDOWS:
        return "default"  # dispositivo de gravação padrão do Windows
    if name and name != "default" and any(d.name == name for d in microphones()):
        return name
    return default_source()


def resolve_system(name: str) -> str:
    """Fonte de monitoramento da saída escolhida (grava o que toca nos alto-falantes/fones)."""
    if WINDOWS:
        return "default"  # saída padrão do Windows, em loopback
    outs = outputs()
    target = name if name and name != "default" else default_sink()
    for d in outs:
        if d.name == target:
            return d.monitor
    return outs[0].monitor if outs else ""


def db_to_unit(db: float) -> float:
    """Converte dB de pico (-60..0) em 0..1 para os medidores."""
    if db is None or math.isinf(db) or math.isnan(db):
        return 0.0
    return max(0.0, min(1.0, (db + 60.0) / 60.0))


def level_from_message(msg) -> float | None:
    st = msg.get_structure()
    if st is None or st.get_name() != "level":
        return None
    try:
        peaks = st.get_value("peak")
        return db_to_unit(max(peaks)) if peaks else 0.0
    except Exception:
        return None


class LevelMonitor(QObject):
    """Mede o nível de uma fonte de áudio em tempo real (medidor do microfone)."""

    level = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pipe = None
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._poll)

    def start(self, device: str, volume: float = 1.0) -> None:
        self.stop()
        if not device:
            return
        try:
            self.pipe = Gst.parse_launch(
                f'{source_fragment(device, "GCP Capture Studio (medidor)")} ! queue ! audioconvert ! '
                f"volume name=vol volume={volume:.3f} ! level interval=60000000 post-messages=true ! fakesink sync=false"
            )
            self.pipe.set_state(Gst.State.PLAYING)
            self.timer.start()
        except Exception:
            self.pipe = None

    def set_volume(self, volume: float) -> None:
        if self.pipe:
            self.pipe.get_by_name("vol").set_property("volume", volume)

    def _poll(self) -> None:
        if not self.pipe:
            return
        bus = self.pipe.get_bus()
        last = None
        while True:
            msg = bus.pop()
            if msg is None:
                break
            if msg.type == Gst.MessageType.ELEMENT:
                val = level_from_message(msg)
                if val is not None:
                    last = val
            elif msg.type == Gst.MessageType.ERROR:
                self.stop()
                return
        if last is not None:
            self.level.emit(last)

    def stop(self) -> None:
        self.timer.stop()
        if self.pipe:
            self.pipe.set_state(Gst.State.NULL)
            self.pipe = None
            self.level.emit(0.0)


class MicTest(QObject):
    """Teste de microfone: grava alguns segundos e reproduz na saída escolhida."""

    state = Signal(str)  # recording | playing | idle
    level = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pipe = None
        self.mode = "idle"
        self.path = os.path.join(tempfile.gettempdir(), f"gcp-capture-mictest-{os.getpid()}.wav")
        self.sink = ""
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._poll)

    def run(self, device: str, volume: float, sink: str = "", seconds: int = 4) -> None:
        self.cancel()
        self.sink = sink
        buffers = int(seconds * 48000 / 480)
        try:
            self.pipe = Gst.parse_launch(
                f"{source_fragment(device)} num-buffers={buffers} blocksize=1920 ! audioconvert ! audioresample ! "
                f"audio/x-raw,rate=48000,channels=2,format=S16LE ! audioconvert ! volume volume={volume:.3f} ! "
                "level interval=60000000 post-messages=true ! wavenc ! filesink name=out"
            )
            # caminho por propriedade: no texto do pipeline a barra invertida do Windows é escape
            self.pipe.get_by_name("out").set_property("location", self.path)
            self.pipe.set_state(Gst.State.PLAYING)
        except Exception:
            self.pipe = None
            return
        self.mode = "recording"
        self.state.emit(self.mode)
        self.timer.start()
        QTimer.singleShot((seconds + 2) * 1000, self._guard_record)

    def _guard_record(self) -> None:
        if self.mode == "recording":
            self._play()

    def _play(self) -> None:
        if self.pipe:
            self.pipe.set_state(Gst.State.NULL)
        try:
            self.pipe = Gst.parse_launch(
                "filesrc name=in ! wavparse ! audioconvert ! audioresample ! "
                f"level interval=60000000 post-messages=true ! {sink_fragment(self.sink)}"
            )
            self.pipe.get_by_name("in").set_property("location", self.path)
            self.pipe.set_state(Gst.State.PLAYING)
            self.mode = "playing"
            self.state.emit(self.mode)
        except Exception:
            self.cancel()

    def _poll(self) -> None:
        if not self.pipe:
            return
        bus = self.pipe.get_bus()
        while True:
            msg = bus.pop()
            if msg is None:
                break
            if msg.type == Gst.MessageType.ELEMENT:
                val = level_from_message(msg)
                if val is not None:
                    self.level.emit(val)
            elif msg.type == Gst.MessageType.EOS:
                if self.mode == "recording":
                    self._play()
                else:
                    self.cancel()
                return
            elif msg.type == Gst.MessageType.ERROR:
                self.cancel()
                return

    def cancel(self) -> None:
        self.timer.stop()
        if self.pipe:
            self.pipe.set_state(Gst.State.NULL)
            self.pipe = None
        if self.mode != "idle":
            self.mode = "idle"
            self.state.emit("idle")
            self.level.emit(0.0)
        try:
            os.remove(self.path)
        except OSError:
            pass
