"""Motor de gravação: captura → codificação (GPU/CPU) → arquivo, com pausa por segmentos.

Um pipeline GStreamer por segmento; ao pausar o segmento é finalizado e, ao parar,
os segmentos são unidos sem recodificar e convertidos para MP4 (pronto para o editor).
"""
from __future__ import annotations

import math
import os
import shutil
import sys
import time
from dataclasses import dataclass, field

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402
from PySide6.QtCore import QObject, QProcess, QTimer, Signal
from PySide6.QtGui import QImage

from . import audio, encoders

Gst.init(None)

try:  # lupa composta direto no vídeo (cairooverlay)
    import cairo

    gi.require_foreign("cairo")
    HAVE_CAIRO = Gst.ElementFactory.find("cairooverlay") is not None
except Exception:  # noqa: BLE001
    HAVE_CAIRO = False


@dataclass
class CaptureSource:
    kind: str  # pipewire | x11 | test
    node: int = 0
    open_fd: object = None  # callable -> novo fd PipeWire
    size: tuple[int, int] = (0, 0)  # tamanho do fluxo em pixels
    crop: tuple[int, int, int, int] | None = None  # x, y, w, h em pixels do fluxo
    show_cursor: bool = True
    handle: int = 0  # Windows: HMONITOR do monitor gravado

    def out_size(self) -> tuple[int, int]:
        w, h = (self.crop[2], self.crop[3]) if self.crop else self.size
        return w - (w % 2), h - (h % 2)


@dataclass
class RecordOptions:
    fps: int = 30
    quality: str = "alta"
    encoder: str = "auto"
    mic: str = ""  # dispositivo ou "" para desativar
    mic_volume: float = 1.0
    system: str = ""  # fonte monitor ou ""
    system_volume: float = 1.0
    out_dir: str = ""
    basename: str = "gravacao"
    extra: dict = field(default_factory=dict)


class Recorder(QObject):
    started = Signal()
    finished = Signal(str)  # caminho do arquivo final
    failed = Signal(str)
    level = Signal(float)  # nível do microfone 0..1
    notice = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pipe = None
        self.source: CaptureSource | None = None
        self.opts: RecordOptions | None = None
        self.encoder: encoders.Encoder | None = None
        self.segments: list[str] = []
        self.state = "idle"  # idle | recording | paused | stopping | finalizing
        self._after_eos = None
        self._pending = None
        self._eos_deadline = 0.0
        self._seg_started = 0.0
        self._preview_on = False
        self._proc: QProcess | None = None
        self._ptr: tuple | None = None  # ponteiro em pixels do quadro
        self._lens: tuple | None = None  # (raio, ampliação, espessura) em pixels do quadro
        self._zoom_target = 1.0
        self._cam = [1.0, 0.0, 0.0]  # zoom atual e centro da "câmera" (animados quadro a quadro)
        self._fimg: QImage | None = None
        self._fdata = None
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._poll_bus)

    # -- construção do pipeline --------------------------------------------
    def _video_source(self) -> str:
        s, fps = self.source, self.opts.fps
        if s.kind == "pipewire":
            return f"pipewiresrc name=src fd={s.open_fd()} path={s.node} do-timestamp=true ! videorate ! video/x-raw,framerate={fps}/1"
        if s.kind == "x11":
            return (
                f"ximagesrc name=src use-damage=false show-pointer={'true' if s.show_cursor else 'false'} ! "
                f"videorate ! video/x-raw,framerate={fps}/1"
            )
        if s.kind == "win":
            mon = f" monitor-handle={s.handle}" if s.handle else ""
            return (
                f"d3d11screencapturesrc name=src show-cursor={'true' if s.show_cursor else 'false'}{mon} ! "
                f"d3d11download ! videorate ! video/x-raw,framerate={fps}/1"
            )
        if s.kind == "mac":
            return f"avfvideosrc name=src capture-screen=true capture-screen-cursor={'true' if s.show_cursor else 'false'} ! videorate ! video/x-raw,framerate={fps}/1"
        w, h = s.size
        return f"videotestsrc name=src is-live=true pattern=ball ! video/x-raw,width={w},height={h},framerate={fps}/1"

    def _build(self, path: str):
        s, o, enc = self.source, self.opts, self.encoder
        parts = [self._video_source(), "videoconvert n-threads=2"]
        sw, sh = s.size
        ow, oh = s.out_size()
        if s.crop:
            x, y, _, _ = s.crop
            parts.append(f"videocrop left={x} top={y} right={max(0, sw - x - ow)} bottom={max(0, sh - y - oh)}")
        elif (ow, oh) != (sw, sh) and sw and sh:
            parts.append(f"videocrop right={sw - ow} bottom={sh - oh}")
        video = " ! ".join(parts) + " ! tee name=vt "
        # ramo de codificação: fila com descarte para a captura nunca travar se a CPU saturar
        video += (
            f"vt. ! queue max-size-buffers={max(6, o.fps // 2)} max-size-time=0 max-size-bytes=0 leaky=downstream ! "
            + ("videoconvert ! video/x-raw,format=BGRx ! cairooverlay name=lens ! " if HAVE_CAIRO else "")
            + f"videoconvert ! video/x-raw,format={enc.raw_format} ! {enc.id} name=venc ! h264parse ! "
            f"queue max-size-time=0 max-size-bytes=0 max-size-buffers=0 ! mux. "
        )
        # ramo de pré-visualização (lupa e desfoque), fechado por válvula quando não usado
        video += (
            "vt. ! queue max-size-buffers=1 leaky=downstream ! valve name=pvalve drop=true drop-mode=transform-to-gap ! videoconvert ! "
            "video/x-raw,format=BGRx ! appsink name=psink max-buffers=1 drop=true sync=false async=false wait-on-eos=false "
        )
        aenc, _codec = encoders.audio_encoder()
        srcs = []
        if o.mic:
            srcs.append(
                f"{audio.source_fragment(o.mic)} ! queue max-size-time=3000000000 ! "
                f"audioconvert ! audioresample ! volume name=micvol volume={o.mic_volume:.3f} ! "
                f"level name=miclevel interval=80000000 post-messages=true ! audio/x-raw,rate=48000,channels=2"
            )
        if o.system:
            srcs.append(
                f"{audio.source_fragment(o.system, loopback=True)} ! queue max-size-time=3000000000 ! "
                f"audioconvert ! audioresample ! volume name=sysvol volume={o.system_volume:.3f} ! "
                f"audio/x-raw,rate=48000,channels=2"
            )
        audio_part = ""
        tail = f"audioconvert ! {aenc} ! queue max-size-time=0 max-size-bytes=0 max-size-buffers=0 ! mux. "
        if len(srcs) == 1:
            audio_part = f"{srcs[0]} ! {tail}"
        elif len(srcs) == 2:
            # folga de 200 ms no misturador: sem ela, blocos são descartados quando uma das fontes
            # entrega os dados com atraso e o som sai "picotado"
            audio_part = f"audiomixer name=amix latency=200000000 ignore-inactive-pads=true ! audio/x-raw,rate=48000,channels=2 ! {tail}" + "".join(f"{s_} ! amix. " for s_ in srcs)
        desc = f"{video} {audio_part} matroskamux name=mux ! filesink name=out sync=false"
        pipe = Gst.parse_launch(desc)
        # o caminho é definido por propriedade: no texto do pipeline a barra invertida é caractere
        # de escape e "C:\Users\..." perderia as barras (o arquivo iria parar em outra pasta)
        pipe.get_by_name("out").set_property("location", path)
        pipe.use_clock(Gst.SystemClock.obtain())
        encoders.configure(pipe.get_by_name("venc"), enc, ow, oh, o.fps, o.quality)
        src = pipe.get_by_name("src")
        if s.kind == "pipewire":
            for prop, val in (("keepalive-time", 250), ("always-copy", True)):
                if src.find_property(prop) is not None:
                    src.set_property(prop, val)
        elif s.kind == "x11" and s.crop:
            # no X11 o recorte é feito na origem (mais leve que capturar a tela toda)
            pass
        pipe.get_by_name("pvalve").set_property("drop", not self._preview_on)
        lens = pipe.get_by_name("lens")
        if lens is not None:
            lens.connect("draw", self._draw_fx)
        return pipe

    # -- controle ------------------------------------------------------------
    def start(self, source: CaptureSource, opts: RecordOptions) -> None:
        if self.state != "idle":
            return
        self.source, self.opts = source, opts
        self.encoder = encoders.pick(opts.encoder)
        if self.encoder is None:
            self.failed.emit("Nenhum codificador de vídeo H.264 disponível. Instale gst-plugins-ugly (x264).")
            return
        os.makedirs(opts.out_dir, exist_ok=True)
        self.segments = []
        self._start_segment()

    def _segment_path(self) -> str:
        return os.path.join(self.opts.out_dir, f".{self.opts.basename}.parte{len(self.segments) + 1:02d}.mkv")

    def _start_segment(self) -> None:
        path = self._segment_path()
        try:
            self.pipe = self._build(path)
        except Exception as exc:  # noqa: BLE001
            self._fail(f"Não foi possível montar a gravação: {exc}")
            return
        self.segments.append(path)
        self._seg_started = time.monotonic()
        self.pipe.set_state(Gst.State.PLAYING)
        self.timer.start()
        first = self.state == "idle"
        self.state = "recording"
        if first:
            self.started.emit()

    def pause(self) -> None:
        if self.state == "recording":
            self.state = "pausing"
            self._send_eos(self._paused)

    def _paused(self) -> None:
        self.state = "paused"
        pending, self._pending = self._pending, None
        if pending == "resume":
            self.resume()
        elif pending == "stop":
            self.stop()

    def resume(self) -> None:
        if self.state == "paused":
            self._start_segment()
        elif self.state == "pausing":
            self._pending = "resume"

    def stop(self) -> None:
        if self.state == "pausing":
            self._pending = "stop"
        elif self.state == "recording":
            self.state = "stopping"
            self._send_eos(self._finalize)
        elif self.state == "paused":
            self.state = "stopping"
            self._finalize()

    def discard(self) -> None:
        """Cancela a gravação e apaga os segmentos."""
        self._teardown()
        for seg in self.segments:
            try:
                os.remove(seg)
            except OSError:
                pass
        self.segments = []
        self.state = "idle"

    def _send_eos(self, then) -> None:
        self._after_eos = then
        self._eos_deadline = time.monotonic() + 4.0
        self.pipe.send_event(Gst.Event.new_eos())

    def _teardown(self) -> None:
        self.timer.stop()
        self._fimg = self._fdata = None
        if self.pipe:
            self.pipe.set_state(Gst.State.NULL)
            self.pipe = None
        self.level.emit(0.0)

    def _fail(self, text: str) -> None:
        self._teardown()
        had = [s for s in self.segments if os.path.exists(s) and os.path.getsize(s) > 4096]
        self.state = "idle"
        self.failed.emit(text)
        if had:
            self.segments = had
            self.state = "stopping"
            self._finalize()

    def _poll_bus(self) -> None:
        if not self.pipe:
            return
        bus = self.pipe.get_bus()
        level = None
        while self.pipe:
            msg = bus.pop()
            if msg is None:
                break
            t = msg.type
            if t == Gst.MessageType.ELEMENT:
                val = audio.level_from_message(msg)
                if val is not None:
                    level = val
            elif t == Gst.MessageType.EOS:
                self._eos_done()
                return
            elif t == Gst.MessageType.ERROR:
                err, dbg = msg.parse_error()
                self._on_error(f"{err.message}", dbg or "")
                return
        if level is not None:
            self.level.emit(level)
        if self._after_eos and time.monotonic() > self._eos_deadline:
            self._eos_done()

    def _eos_done(self) -> None:
        then, self._after_eos = self._after_eos, None
        self._teardown()
        if then:
            then()

    def _on_error(self, message: str, debug: str) -> None:
        early = time.monotonic() - self._seg_started < 4.0
        if early and self.encoder.hardware and self.state == "recording":
            # codificador de GPU falhou ao iniciar: cai para CPU automaticamente
            sw = encoders.software_fallback()
            if sw is not None:
                self._teardown()
                bad = self.segments.pop() if self.segments else None
                if bad:
                    try:
                        os.remove(bad)
                    except OSError:
                        pass
                self.notice.emit(f"{self.encoder.label} indisponível — usando {sw.label}.")
                self.encoder = sw
                self._start_segment()
                return
        sys.stderr.write(f"[recorder] erro: {message}\n{debug}\n")
        self._fail(f"A gravação foi interrompida: {message}")

    # -- pré-visualização ----------------------------------------------------
    def set_preview(self, on: bool) -> None:
        self._preview_on = on
        if self.pipe:
            self.pipe.get_by_name("pvalve").set_property("drop", not on)

    def latest_frame(self) -> QImage | None:
        """Último quadro capturado, sem cópia extra (válido até a próxima chamada). Requer set_preview(True)."""
        if not self.pipe:
            return None
        sink = self.pipe.get_by_name("psink")
        sample = sink.emit("try-pull-sample", 0)
        if sample is None and self._fimg is None:
            sample = sink.get_property("last-sample")
        if sample is None:
            return self._fimg
        caps = sample.get_caps().get_structure(0)
        w, h = caps.get_value("width"), caps.get_value("height")
        buf = sample.get_buffer()
        ok, info = buf.map(Gst.MapFlags.READ)
        if not ok:
            return self._fimg
        try:
            self._fdata = bytes(info.data)
            self._fimg = QImage(self._fdata, w, h, len(self._fdata) // h, QImage.Format_RGB32)
        finally:
            buf.unmap(info)
        return self._fimg

    def grab_frame(self) -> QImage | None:
        """Cópia independente do último quadro capturado."""
        img = self.latest_frame()
        return img.copy() if img is not None else None

    # -- lupa no vídeo -------------------------------------------------------
    @property
    def lens_in_video(self) -> bool:
        return HAVE_CAIRO

    def set_fx(self, pointer: tuple | None, lens: tuple | None, zoom: float) -> None:
        """Efeitos compostos no vídeo. `pointer`: (x, y) em pixels do quadro; `lens`: (raio, ampliação, escala)
        ou None; `zoom`: ampliação do quadro inteiro acompanhando o ponteiro (1.0 = desligado)."""
        if pointer is not None:
            self._ptr = pointer
        self._lens = lens if pointer is not None else None
        self._zoom_target = max(1.0, float(zoom))

    def view_transform(self) -> tuple[float, float, float]:
        """(zoom, x, y) do enquadramento atual: ponto do quadro original no canto superior esquerdo."""
        z, cx, cy = self._cam
        w, h = self.source.out_size() if self.source else (0, 0)
        return z, cx - w / (2 * z), cy - h / (2 * z)

    def _draw_fx(self, _overlay, cr, _ts, _dur) -> None:
        try:
            target = cr.get_target()
            w, h = target.get_width(), target.get_height()
            ptr = self._ptr or (w / 2, h / 2)
            cam = self._cam
            # zoom com "pan": aproxima suavemente e acompanha o ponteiro com uma zona morta central,
            # para o enquadramento não tremer a cada pequeno movimento
            cam[0] += (self._zoom_target - cam[0]) * 0.14
            if abs(cam[0] - self._zoom_target) < 0.004:
                cam[0] = self._zoom_target
            z = cam[0]
            if z <= 1.001:
                cam[1], cam[2] = ptr
                px, py = ptr
            else:
                vw, vh = w / z, h / z
                tx, ty = cam[1], cam[2]
                dx, dy = ptr[0] - tx, ptr[1] - ty
                if abs(dx) > vw * 0.16:
                    tx = ptr[0] - math.copysign(vw * 0.16, dx)
                if abs(dy) > vh * 0.16:
                    ty = ptr[1] - math.copysign(vh * 0.16, dy)
                cam[1] += (tx - cam[1]) * 0.12
                cam[2] += (ty - cam[2]) * 0.12
                cam[1] = min(max(cam[1], vw / 2), w - vw / 2)
                cam[2] = min(max(cam[2], vh / 2), h - vh / 2)
                vx, vy = cam[1] - vw / 2, cam[2] - vh / 2
                iw, ih = int(math.ceil(vw)) + 2, int(math.ceil(vh)) + 2
                view = cairo.ImageSurface(cairo.FORMAT_RGB24, iw, ih)
                t = cairo.Context(view)
                t.set_source_surface(target, -vx, -vy)
                t.paint()
                view.flush()
                cr.save()
                cr.scale(z, z)
                cr.set_source_surface(view, 0, 0)
                cr.get_source().set_filter(cairo.FILTER_BILINEAR)
                cr.paint()
                cr.restore()
                px, py = (ptr[0] - vx) * z, (ptr[1] - vy) * z
            lens = self._lens
            if lens is None:
                return
            rad, zoom, k = lens
            n = int(math.ceil(2 * rad / zoom)) + 2
            tmp = cairo.ImageSurface(cairo.FORMAT_RGB24, n, n)
            t = cairo.Context(tmp)
            t.set_source_rgb(0.05, 0.08, 0.13)
            t.paint()
            t.set_source_surface(target, -(px - n / 2), -(py - n / 2))
            t.paint()
            tmp.flush()
            cr.save()
            cr.arc(px, py, rad, 0, 2 * math.pi)
            cr.clip()
            cr.translate(px, py)
            cr.scale(zoom, zoom)
            cr.translate(-n / 2, -n / 2)
            cr.set_source_surface(tmp, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_BILINEAR)
            cr.paint()
            cr.restore()
            cr.set_source_rgba(0, 0, 0, 0.35)
            cr.set_line_width(6 * k)
            cr.arc(px, py, rad + k, 0, 2 * math.pi)
            cr.stroke()
            cr.set_source_rgb(1, 1, 1)
            cr.set_line_width(2.5 * k)
            cr.arc(px, py, rad, 0, 2 * math.pi)
            cr.stroke()
        except Exception:  # noqa: BLE001
            pass

    # -- finalização ---------------------------------------------------------
    def _final_path(self, ext: str) -> str:
        base = os.path.join(self.opts.out_dir, self.opts.basename)
        path, n = f"{base}.{ext}", 2
        while os.path.exists(path):
            path, n = f"{base} ({n}).{ext}", n + 1
        return path

    def _finalize(self) -> None:
        self.state = "finalizing"
        segs = [s for s in self.segments if os.path.exists(s) and os.path.getsize(s) > 1024]
        if not segs:
            self.state = "idle"
            self.failed.emit("Nada foi gravado.")
            return
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            final = self._final_path("mkv")
            os.replace(segs[0], final)
            self._done(final, segs[1:])
            return
        final = self._final_path("mp4")
        args = ["-hide_banner", "-loglevel", "error", "-y"]
        listfile = None
        if len(segs) == 1:
            args += ["-i", segs[0]]
        else:
            listfile = os.path.join(self.opts.out_dir, f".{self.opts.basename}.lista.txt")
            with open(listfile, "w", encoding="utf-8") as fh:
                for seg in segs:
                    fh.write("file '" + seg.replace("'", "'\\''") + "'\n")
            args += ["-f", "concat", "-safe", "0", "-i", listfile]
        args += ["-c", "copy", "-movflags", "+faststart", final]
        self._proc = QProcess(self)

        def done(code, _status):
            if listfile:
                try:
                    os.remove(listfile)
                except OSError:
                    pass
            if code == 0 and os.path.exists(final) and os.path.getsize(final) > 1024:
                self._done(final, segs)
            else:
                # mantém o material bruto se a conversão falhar
                keep = self._final_path("mkv")
                os.replace(segs[0], keep)
                self._done(keep, [])

        self._proc.finished.connect(done)
        self._proc.start(ffmpeg, args)

    def _done(self, final: str, cleanup: list[str]) -> None:
        for seg in cleanup:
            try:
                os.remove(seg)
            except OSError:
                pass
        self.segments = []
        self.state = "idle"
        self.finished.emit(final)
