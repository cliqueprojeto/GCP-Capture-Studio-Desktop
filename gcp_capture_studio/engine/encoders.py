"""Detecção e configuração de codificadores de vídeo (GPU quando disponível, CPU como reserva)."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

Gst.init(None)

QUALITY_QP = {"baixa": 30, "media": 25, "alta": 21, "maxima": 17}
QUALITY_BPP = {"baixa": 0.045, "media": 0.07, "alta": 0.11, "maxima": 0.17}  # bits por pixel/quadro


@dataclass(frozen=True)
class Encoder:
    id: str  # nome do elemento GStreamer
    label: str
    hardware: bool
    raw_format: str  # formato de entrada preferido


CANDIDATES = [
    Encoder("vah264enc", "GPU · VA-API (AMD/Intel)", True, "NV12"),
    Encoder("vah264lpenc", "GPU · VA-API baixo consumo (Intel)", True, "NV12"),
    Encoder("nvh264enc", "GPU · NVIDIA NVENC", True, "NV12"),
    Encoder("qsvh264enc", "GPU · Intel Quick Sync", True, "NV12"),
    Encoder("vaapih264enc", "GPU · VA-API (legado)", True, "NV12"),
    Encoder("vtenc_h264_hw", "GPU · VideoToolbox (macOS)", True, "NV12"),
    Encoder("mfh264enc", "GPU · Media Foundation (Windows)", True, "NV12"),
    Encoder("x264enc", "CPU · x264", False, "I420"),
    Encoder("openh264enc", "CPU · OpenH264", False, "I420"),
]
BY_ID = {e.id: e for e in CANDIDATES}

_cache: list[Encoder] | None = None


def _works(enc: Encoder) -> bool:
    if Gst.ElementFactory.find(enc.id) is None:
        return False
    try:
        pipe = Gst.parse_launch(
            f"videotestsrc num-buffers=8 ! video/x-raw,width=640,height=360,framerate=30/1 ! "
            f"videoconvert ! video/x-raw,format={enc.raw_format} ! {enc.id} ! fakesink"
        )
    except Exception:
        return False
    pipe.set_state(Gst.State.PLAYING)
    msg = pipe.get_bus().timed_pop_filtered(4 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
    pipe.set_state(Gst.State.NULL)
    return msg is not None and msg.type == Gst.MessageType.EOS


def available(refresh: bool = False) -> list[Encoder]:
    """Codificadores que realmente funcionam nesta máquina, em ordem de preferência."""
    global _cache
    if _cache is None or refresh:
        _cache = [e for e in CANDIDATES if _works(e)]
    return _cache


def pick(preferred: str = "auto") -> Encoder | None:
    encs = available()
    if preferred != "auto":
        for e in encs:
            if e.id == preferred:
                return e
    return encs[0] if encs else None


def software_fallback() -> Encoder | None:
    for e in available():
        if not e.hardware:
            return e
    return None


def _set(element, **props) -> None:
    for name, value in props.items():
        name = name.replace("_", "-")
        if element.find_property(name) is not None:
            try:
                Gst.util_set_object_arg(element, name, str(value))
            except Exception:
                pass


def configure(element, enc: Encoder, width: int, height: int, fps: int, quality: str) -> None:
    """Ajusta o codificador para gravação em tempo real conforme resolução, FPS e núcleos disponíveis."""
    qp = QUALITY_QP.get(quality, 21)
    kbps = max(1500, int(width * height * fps * QUALITY_BPP.get(quality, 0.11) / 1000))
    gop = fps * 2
    cores = os.cpu_count() or 4
    if enc.id == "x264enc":
        heavy = width * height * fps > 1920 * 1080 * 30 or cores <= 4
        _set(
            element,
            speed_preset="ultrafast" if heavy else "superfast",
            tune="zerolatency",
            **{"pass": "quant"},
            quantizer=qp,
            key_int_max=gop,
            bframes=0,
            threads=max(2, min(cores - 1, 12)),  # deixa um núcleo livre para a captura e a interface
        )
    elif enc.id == "openh264enc":
        _set(element, bitrate=kbps * 1000, complexity="low", gop_size=gop, multi_thread=max(2, cores - 1))
    elif enc.id in ("vah264enc", "vah264lpenc"):
        _set(element, rate_control="cqp", qpi=qp, qpp=qp + 2, qpb=qp + 4, key_int_max=gop, b_frames=0, target_usage=6)
        _set(element, bitrate=kbps)
    elif enc.id == "vaapih264enc":
        _set(element, rate_control="cqp", init_qp=qp, keyframe_period=gop, max_bframes=0, quality_level=6)
    elif enc.id == "nvh264enc":
        _set(element, preset="low-latency-hq", rc_mode="constqp", qp_const=qp, gop_size=gop, bframes=0, zerolatency="true")
    elif enc.id == "qsvh264enc":
        _set(element, bitrate=kbps, rate_control="vbr", gop_size=gop, b_frames=0, low_latency="true", target_usage=6)
    else:
        _set(element, bitrate=kbps, realtime="true", allow_frame_reordering="false")


def benchmark(width: int = 1920, height: int = 1080, frames: int = 90) -> dict[str, float]:
    """Mede quadros por segundo de cada codificador (para sugerir a melhor combinação)."""
    results: dict[str, float] = {}
    for enc in available():
        try:
            pipe = Gst.parse_launch(
                f"videotestsrc num-buffers={frames} pattern=smpte ! video/x-raw,width={width},height={height},framerate=30/1 ! "
                f"videoconvert ! video/x-raw,format={enc.raw_format} ! {enc.id} name=enc ! fakesink"
            )
            configure(pipe.get_by_name("enc"), enc, width, height, 30, "alta")
            t0 = time.monotonic()
            pipe.set_state(Gst.State.PLAYING)
            msg = pipe.get_bus().timed_pop_filtered(30 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
            dt = time.monotonic() - t0
            pipe.set_state(Gst.State.NULL)
            if msg is not None and msg.type == Gst.MessageType.EOS and dt > 0:
                results[enc.id] = frames / dt
        except Exception:
            continue
    return results


def audio_encoder() -> tuple[str, str]:
    """Retorna (fragmento de pipeline, codec)."""
    at = Gst.ElementFactory.make("atenc", None)  # AAC nativo do macOS (AudioToolbox)
    if at is not None:
        return "atenc" + (" bitrate=192000" if at.find_property("bitrate") is not None else "") + " ! aacparse", "aac"
    for name, frag in (
        ("fdkaacenc", "fdkaacenc bitrate=192000"),
        ("avenc_aac", "avenc_aac bitrate=192000"),
        ("faac", "faac bitrate=192000"),
    ):
        if Gst.ElementFactory.find(name):
            return frag + " ! aacparse", "aac"
    return "opusenc bitrate=160000", "opus"
