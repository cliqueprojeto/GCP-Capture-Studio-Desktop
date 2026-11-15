"""Envio da gravação ao editor de vídeo integrado.

Gera um projeto do Kdenlive com a gravação já posicionada na linha do tempo
(vídeo em V1, áudio em A1, agrupados) e abre o editor nesse projeto.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from xml.sax.saxutils import escape

WINDOWS = sys.platform.startswith("win")
_WIN_PATHS = {  # pasta de instalação e executável no Windows
    "kdenlive": ("kdenlive.exe", "kdenlive\\bin", "kdenlive"),
    "shotcut": ("shotcut.exe", "Shotcut"),
    "openshot": ("openshot-qt.exe", "OpenShot Video Editor"),
}


def _spawn(args: list[str]) -> None:
    """Abre o editor desacoplado do gravador (ele continua aberto depois que o gravador fecha)."""
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if WINDOWS:
        kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen(args, **kw)

EDITORS = {
    "kdenlive": ("Kdenlive", ["kdenlive"], "org.kde.kdenlive"),
    "shotcut": ("Shotcut", ["shotcut"], "org.shotcut.Shotcut"),
    "openshot": ("OpenShot", ["openshot-qt"], "org.openshot.OpenShot"),
}


def _flatpak_has(app_id: str) -> bool:
    if not shutil.which("flatpak"):
        return False
    try:
        out = subprocess.run(["flatpak", "info", app_id], capture_output=True, timeout=4)
        return out.returncode == 0
    except Exception:
        return False


def editor_command(app: str) -> list[str] | None:
    name, cmd, flatpak_id = EDITORS.get(app, EDITORS["kdenlive"])
    if shutil.which(cmd[0]):
        return cmd
    if WINDOWS:
        from ..platform.win import find_program

        exe, *folders = _WIN_PATHS.get(app, _WIN_PATHS["kdenlive"])
        path = find_program(exe, *folders)
        return [path] if path else None
    if _flatpak_has(flatpak_id):
        return ["flatpak", "run", flatpak_id]
    return None


def installed_editors() -> list[str]:
    return [key for key in EDITORS if editor_command(key)]


def probe(path: str) -> dict:
    """Largura, altura, fps, duração e presença de áudio."""
    info = {"width": 1920, "height": 1080, "fps_num": 30, "fps_den": 1, "duration": 0.0, "audio": False, "frames": 0}
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path],
            capture_output=True, text=True, timeout=20,
        )
        data = json.loads(out.stdout)
        for st in data.get("streams", []):
            if st.get("codec_type") == "video" and "width" in st:
                info["width"], info["height"] = int(st["width"]), int(st["height"])
                num, den = (st.get("avg_frame_rate") or "30/1").split("/")
                if int(den) and int(num):
                    # gravações têm taxa constante; arredonda para a taxa padrão mais próxima
                    real = int(num) / int(den)
                    info["fps_num"], info["fps_den"] = min((15, 24, 25, 30, 50, 60), key=lambda f: abs(f - real)), 1
                if st.get("nb_frames", "").isdigit():
                    info["frames"] = int(st["nb_frames"])
            elif st.get("codec_type") == "audio":
                info["audio"] = True
        info["duration"] = float(data.get("format", {}).get("duration", 0) or 0)
    except Exception:
        pass
    fps = info["fps_num"] / info["fps_den"]
    if not info["frames"]:
        info["frames"] = max(1, int(round(info["duration"] * fps)))
    return info


def _profile_fields(info: dict) -> dict:
    w, h = info["width"], info["height"]
    a, b = w, h
    while b:
        a, b = b, a % b
    return {
        "description": f"GCP Capture {w}x{h} {info['fps_num']} fps",
        "frame_rate_num": info["fps_num"], "frame_rate_den": info["fps_den"], "width": w, "height": h,
        "progressive": 1, "sample_aspect_num": 1, "sample_aspect_den": 1,
        "display_aspect_num": w // a, "display_aspect_den": h // a, "colorspace": 709,
    }


def _read_profile(path: str) -> dict:
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    out[k] = v
    except Exception:
        pass
    return out


def kdenlive_profile(info: dict, flatpak: bool = False) -> str:
    """Nome de um perfil do Kdenlive que corresponde à gravação (cria um personalizado se preciso)."""
    want = _profile_fields(info)
    keys = ("frame_rate_num", "frame_rate_den", "width", "height", "progressive", "sample_aspect_num", "sample_aspect_den")

    def matches(path: str) -> bool:
        got = _read_profile(path)
        return bool(got) and all(str(got.get(k)) == str(want[k]) for k in keys)

    bases = ["/usr/share/mlt-7/profiles", "/usr/share/kdenlive/profiles", "/usr/local/share/mlt-7/profiles"]
    if WINDOWS:
        exe = (editor_command("kdenlive") or [""])[0]
        root = os.path.dirname(os.path.dirname(exe)) if exe else ""
        bases = [os.path.join(root, *p) for p in (("share", "mlt-7", "profiles"), ("bin", "data", "mlt", "profiles"), ("share", "mlt", "profiles"))]
    for base in bases:
        if os.path.isdir(base):
            for name in sorted(os.listdir(base)):
                if matches(os.path.join(base, name)):
                    return name
    data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    if WINDOWS:
        data = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    if flatpak:
        data = os.path.expanduser("~/.var/app/org.kde.kdenlive/data")
    custom_dir = os.path.join(data, "kdenlive", "profiles")
    path = os.path.join(custom_dir, f"gcp_capture_{want['width']}x{want['height']}_{want['frame_rate_num']}")
    if not matches(path):
        os.makedirs(custom_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("".join(f"{k}={v}\n" for k, v in want.items()))
    return path


def _tc(frame: int, fps: float) -> str:
    seconds = frame / fps
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _props(d: dict) -> str:
    return "".join(f'  <property name="{k}">{escape(str(v))}</property>\n' for k, v in d.items())


_AUDIO_FILTERS = """  <filter id="{p}0"><property name="window">75</property><property name="max_gain">20dB</property><property name="mlt_service">volume</property><property name="internal_added">237</property><property name="disable">1</property></filter>
  <filter id="{p}1"><property name="channel">-1</property><property name="mlt_service">panner</property><property name="internal_added">237</property><property name="start">0.5</property><property name="disable">1</property></filter>
  <filter id="{p}2"><property name="iec_scale">0</property><property name="mlt_service">audiolevel</property><property name="peak">1</property><property name="disable">1</property></filter>
"""

_TRACK_PROPS = """  <property name="kdenlive:trackheight">67</property>
  <property name="kdenlive:timeline_active">1</property>
  <property name="kdenlive:collapsed">0</property>
  <property name="kdenlive:thumbs_format"/>
  <property name="kdenlive:audio_rec"/>
"""


def build_kdenlive_project(video: str, project_path: str, flatpak: bool = False) -> str:
    """Cria o arquivo .kdenlive com o clipe na linha do tempo e devolve o caminho."""
    info = probe(video)
    fps = info["fps_num"] / info["fps_den"]
    frames = info["frames"]
    out_tc = _tc(frames - 1, fps)
    zero = "00:00:00.000"
    name = os.path.splitext(os.path.basename(video))[0]
    w, h = info["width"], info["height"]

    def gcd(a, b):
        while b:
            a, b = b, a % b
        return a

    g = gcd(w, h)
    clip_props = {
        "length": frames,
        "eof": "pause",
        "resource": video,
        "mlt_service": "avformat-novalidate",
        "seekable": 1,
        "audio_index": 1 if info["audio"] else -1,
        "video_index": 0,
        "mute_on_pause": 0,
        "kdenlive:clipname": name,
        "kdenlive:clip_type": 0,
        "kdenlive:folderid": -1,
        "kdenlive:id": 2,
    }

    def producer(pid: str, extra: dict) -> str:
        return f' <producer id="{pid}" in="{zero}" out="{out_tc}">\n{_props({**clip_props, **extra})} </producer>\n'

    def entry(pid: str) -> str:
        return f'  <entry producer="{pid}" in="{zero}" out="{out_tc}">\n   <property name="kdenlive:id">2</property>\n  </entry>\n'

    has_audio = info["audio"]
    groups = (
        json.dumps(
            [{"children": [{"data": "1:0", "leaf": "clip", "type": "Leaf"}, {"data": "2:0", "leaf": "clip", "type": "Leaf"}], "type": "AVSplit"}],
            indent=4,
        )
        if has_audio
        else "[]"
    )
    doc_props = {
        "kdenlive:docproperties.activeTrack": 2,
        "kdenlive:docproperties.audioChannels": 2,
        "kdenlive:docproperties.audioTarget": 1,
        "kdenlive:docproperties.disablepreview": 0,
        "kdenlive:docproperties.enableproxy": 0,
        "kdenlive:docproperties.generateproxy": 0,
        "kdenlive:docproperties.kdenliveversion": "22.12.3",
        "kdenlive:docproperties.position": 0,
        "kdenlive:docproperties.profile": kdenlive_profile(info, flatpak),
        "kdenlive:docproperties.version": "1.04",
        "kdenlive:docproperties.verticalzoom": 1,
        "kdenlive:docproperties.videoTarget": 2,
        "kdenlive:docproperties.zonein": 0,
        "kdenlive:docproperties.zoneout": min(frames, int(fps * 5)),
        "kdenlive:docproperties.zoom": 8,
        "kdenlive:docproperties.groups": groups,
        "xml_retain": 1,
    }
    x = []
    x.append("<?xml version='1.0' encoding='utf-8'?>\n")
    x.append(f'<mlt LC_NUMERIC="C" producer="main_bin" version="7.14.0" root="{escape(os.path.dirname(video))}">\n')
    x.append(
        f' <profile frame_rate_num="{info["fps_num"]}" sample_aspect_num="1" display_aspect_den="{h // g}" colorspace="709" '
        f'progressive="1" description="{w}x{h} {fps:.2f}fps" display_aspect_num="{w // g}" frame_rate_den="{info["fps_den"]}" '
        f'width="{w}" height="{h}" sample_aspect_den="1"/>\n'
    )
    x.append(producer("producer0", {}))
    x.append(f' <playlist id="main_bin">\n{_props(doc_props)}  <entry producer="producer0" in="{zero}" out="{out_tc}"/>\n </playlist>\n')
    x.append(
        f' <producer id="black_track" in="{zero}" out="{out_tc}">\n'
        + _props({"length": 2147483647, "eof": "continue", "resource": "black", "aspect_ratio": 1, "mlt_service": "color", "mlt_image_format": "rgba", "set.test_audio": 0})
        + " </producer>\n"
    )
    # A1 — áudio da gravação
    if has_audio:
        x.append(producer("producer1", {"set.test_audio": 0, "set.test_image": 1}))
    x.append(' <playlist id="playlist0">\n  <property name="kdenlive:audio_track">1</property>\n' + (entry("producer1") if has_audio else "") + " </playlist>\n")
    x.append(' <playlist id="playlist1">\n  <property name="kdenlive:audio_track">1</property>\n </playlist>\n')
    x.append(
        f' <tractor id="tractor0" in="{zero}" out="{out_tc}">\n  <property name="kdenlive:audio_track">1</property>\n{_TRACK_PROPS}'
        '  <track hide="video" producer="playlist0"/>\n  <track hide="video" producer="playlist1"/>\n'
        + _AUDIO_FILTERS.format(p="fa")
        + " </tractor>\n"
    )
    # V1 — vídeo da gravação
    x.append(producer("producer2", {"set.test_audio": 1, "set.test_image": 0}))
    x.append(' <playlist id="playlist2">\n' + entry("producer2") + " </playlist>\n")
    x.append(' <playlist id="playlist3"/>\n')
    x.append(
        f' <tractor id="tractor1" in="{zero}" out="{out_tc}">\n{_TRACK_PROPS}'
        '  <track hide="audio" producer="playlist2"/>\n  <track hide="audio" producer="playlist3"/>\n </tractor>\n'
    )
    # V2 — trilha livre para títulos e sobreposições
    x.append(' <playlist id="playlist4"/>\n <playlist id="playlist5"/>\n')
    x.append(
        f' <tractor id="tractor2" in="{zero}">\n{_TRACK_PROPS}'
        '  <track hide="audio" producer="playlist4"/>\n  <track hide="audio" producer="playlist5"/>\n </tractor>\n'
    )
    x.append(
        f' <tractor id="tractor3" in="{zero}" out="{out_tc}">\n'
        '  <track producer="black_track"/>\n  <track producer="tractor0"/>\n  <track producer="tractor1"/>\n  <track producer="tractor2"/>\n'
        '  <transition id="transition0"><property name="a_track">0</property><property name="b_track">1</property><property name="mlt_service">mix</property><property name="kdenlive_id">mix</property><property name="internal_added">237</property><property name="always_active">1</property><property name="accepts_blanks">1</property><property name="sum">1</property></transition>\n'
        '  <transition id="transition1"><property name="a_track">0</property><property name="b_track">2</property><property name="compositing">0</property><property name="distort">0</property><property name="rotate_center">0</property><property name="mlt_service">qtblend</property><property name="kdenlive_id">qtblend</property><property name="internal_added">237</property><property name="always_active">1</property></transition>\n'
        '  <transition id="transition2"><property name="a_track">0</property><property name="b_track">3</property><property name="compositing">0</property><property name="distort">0</property><property name="rotate_center">0</property><property name="mlt_service">qtblend</property><property name="kdenlive_id">qtblend</property><property name="internal_added">237</property><property name="always_active">1</property></transition>\n'
        + _AUDIO_FILTERS.format(p="fm")
        + " </tractor>\n</mlt>\n"
    )
    with open(project_path, "w", encoding="utf-8") as fh:
        fh.write("".join(x))
    return project_path


def open_in_editor(video: str, app: str = "kdenlive") -> tuple[bool, str]:
    """Abre a gravação no editor. Retorna (sucesso, mensagem)."""
    cmd = editor_command(app)
    if cmd is None:
        for other in installed_editors():
            app, cmd = other, editor_command(other)
            break
    if cmd is None:
        return False, "Nenhum editor de vídeo encontrado. Instale o Kdenlive para editar suas gravações."
    name = EDITORS[app][0]
    try:
        if app == "kdenlive":
            project = os.path.splitext(video)[0] + ".kdenlive"
            if not os.path.exists(project):
                build_kdenlive_project(video, project, flatpak=cmd[0] == "flatpak")
            args = cmd + [project]
        else:
            args = cmd + [video]
        _spawn(args)
        return True, f"Gravação enviada ao {name}."
    except Exception as exc:  # noqa: BLE001
        return False, f"Não foi possível abrir o {name}: {exc}"


def launch_editor(app: str = "kdenlive") -> bool:
    cmd = editor_command(app) or next((editor_command(e) for e in installed_editors()), None)
    if not cmd:
        return False
    _spawn(cmd)
    return True
