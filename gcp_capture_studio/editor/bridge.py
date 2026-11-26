"""Envio da gravação ao editor de vídeo.

Para Kdenlive, Shotcut e OpenShot gera um projeto do próprio editor com a gravação
já posicionada na linha do tempo e abre o editor nesse projeto. Os editores são
procurados no PATH, em Snap, Flatpak, AppImage e nos atalhos do menu (Linux), em
Arquivos de Programas (Windows) e em /Applications (macOS). O usuário também pode
escolher qualquer outro programa, atalho .desktop/.lnk ou pacote .app.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from xml.sax.saxutils import escape

WINDOWS = sys.platform.startswith("win")
MACOS = sys.platform == "darwin"
CUSTOM = "custom"  # editor escolhido pelo usuário (programa, atalho .desktop/.lnk ou .app)
_FILE = "\0arquivo\0"  # marca a posição do arquivo nos comandos vindos de atalhos .desktop

_WIN_PATHS = {  # pasta de instalação e executável no Windows
    "kdenlive": ("kdenlive.exe", "kdenlive\\bin", "kdenlive"),
    "shotcut": ("shotcut.exe", "Shotcut"),
    "openshot": ("openshot-qt.exe", "OpenShot Video Editor"),
}
_MAC_APPS = {  # pacotes .app no macOS
    "kdenlive": ("Kdenlive.app", "kdenlive.app"),
    "shotcut": ("Shotcut.app",),
    "openshot": ("OpenShot Video Editor.app", "OpenShot.app"),
}

# nome, executáveis possíveis, id do Flatpak
EDITORS = {
    "kdenlive": ("Kdenlive", ["kdenlive"], "org.kde.kdenlive"),
    "shotcut": ("Shotcut", ["shotcut"], "org.shotcut.Shotcut"),
    "openshot": ("OpenShot", ["openshot-qt", "openshot"], "org.openshot.OpenShot"),
}


_PRIVATE_ENV = ("QT_", "QML", "GST_", "GI_", "GIO_", "GDK_", "GTK_", "PYTHON", "_PYI", "_MEI")


def _editor_env() -> dict | None:
    """Ambiente do editor. No executável empacotado, o gravador aponta o Qt, o GStreamer e o PATH
    para as próprias bibliotecas; se o editor herdar isso, tenta carregar os plugins Qt do gravador
    e não abre ("no Qt platform plugin could be initialized")."""
    if not getattr(sys, "frozen", False):
        saved = os.environ.get("GCP_CAPTURE_ORIG_ENV")
        if not saved:
            return None
        # Hyprland: o gravador força o XWayland (e escalas próprias); o editor volta ao ambiente da sessão
        import json

        env = dict(os.environ)
        env.pop("GCP_CAPTURE_ORIG_ENV", None)
        try:
            for key, value in json.loads(saved).items():
                if value is None:
                    env.pop(key, None)
                else:
                    env[key] = value
        except ValueError:
            pass
        return env
    base = os.path.normcase(os.path.dirname(sys.executable))
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(_PRIVATE_ENV)}
    env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep) if p and not os.path.normcase(p).startswith(base))
    return env


def _spawn(args: list[str]) -> None:
    """Abre o editor desacoplado do gravador (ele continua aberto depois que o gravador fecha)."""
    if WINDOWS and args and args[0].lower().endswith(".lnk"):
        # atalho do Windows: o próprio sistema resolve o programa de destino
        args = ["cmd", "/c", "start", "", *args]
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "env": _editor_env()}
    if not WINDOWS:
        kw["start_new_session"] = True
        subprocess.Popen(args, **kw)
        return
    kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    kw["cwd"] = os.path.dirname(args[0]) or None
    frozen = getattr(sys, "frozen", False)
    kernel32 = None
    if frozen:
        # o executável empacotado fixa a própria pasta de DLLs, e os processos filhos a herdam
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetDllDirectoryW(None)
    try:
        subprocess.Popen(args, **kw)
    finally:
        if kernel32 is not None:
            kernel32.SetDllDirectoryW(getattr(sys, "_MEIPASS", None))


def _with_file(cmd: list[str], *files: str) -> list[str]:
    """Põe os arquivos na posição marcada pelo atalho (%f, %F…) ou no fim do comando."""
    if _FILE in cmd:
        i = cmd.index(_FILE)
        return cmd[:i] + list(files) + [a for a in cmd[i + 1:] if a != _FILE]
    return cmd + list(files)


# -- Linux: Snap, Flatpak, AppImage e atalhos .desktop ------------------------------
def _extra_dirs() -> list[str]:
    home = os.path.expanduser("~")
    return [
        "/snap/bin", "/var/lib/snapd/snap/bin",  # Snap (Ubuntu e derivados / Arch, Manjaro, Fedora)
        os.path.join(home, ".local", "bin"), os.path.join(home, "bin"),
        "/var/lib/flatpak/exports/bin", os.path.join(home, ".local", "share", "flatpak", "exports", "bin"),
        "/usr/local/bin", "/opt/bin",
    ]


def _which(name: str) -> str | None:
    return shutil.which(name) or shutil.which(name, path=os.pathsep.join(_extra_dirs()))


def _appimage(names: list[str]) -> str | None:
    home = os.path.expanduser("~")
    folders = [os.path.join(home, d) for d in ("Applications", "AppImages", "Aplicativos", ".local/bin", "Downloads", "Transferências")]
    folders.append("/opt")
    for folder in folders:
        try:
            entries = sorted(os.listdir(folder), reverse=True)  # versão mais nova primeiro
        except OSError:
            continue
        for entry in entries:
            low = entry.lower()
            if low.endswith(".appimage") and any(low.startswith(n.split("-")[0]) for n in names):
                path = os.path.join(folder, entry)
                if os.access(path, os.X_OK):
                    return path
    return None


def _desktop_dirs() -> list[str]:
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    data_dirs = (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    dirs = [data_home, *data_dirs, "/var/lib/flatpak/exports/share", os.path.join(data_home, "flatpak", "exports", "share")]
    out = [os.path.join(d, "applications") for d in dirs]
    out.append("/var/lib/snapd/desktop/applications")
    seen: list[str] = []
    for d in out:
        if d not in seen and os.path.isdir(d):
            seen.append(d)
    return seen


def read_desktop(path: str) -> tuple[str, list[str]] | None:
    """Nome e comando de um atalho .desktop (sem os códigos %f, %U… — o arquivo vai na marca)."""
    import shlex

    name = exec_line = ""
    in_entry = False
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("["):
                    in_entry = line == "[Desktop Entry]"
                elif in_entry and line.startswith("Name=") and not name:
                    name = line[5:].strip()
                elif in_entry and line.startswith("Exec=") and not exec_line:
                    exec_line = line[5:].strip()
    except OSError:
        return None
    if not exec_line:
        return None
    try:
        parts = shlex.split(exec_line)
    except ValueError:
        parts = exec_line.split()
    cmd: list[str] = []
    for part in parts:
        if part in ("%f", "%F", "%u", "%U"):
            if _FILE not in cmd:
                cmd.append(_FILE)
        elif len(part) == 2 and part.startswith("%"):
            continue  # %i, %c, %k e afins não se aplicam aqui
        else:
            cmd.append(part.replace("%%", "%"))
    if not cmd or cmd[0] == _FILE:
        return None
    return name or os.path.splitext(os.path.basename(path))[0], cmd


def _from_desktop(names: list[str], flatpak_id: str) -> list[str] | None:
    """Procura o editor pelos atalhos do menu de aplicativos (pega Snap e instalações fora do PATH)."""
    wanted = {n.lower() for n in names} | {flatpak_id.lower()}
    for folder in _desktop_dirs():
        try:
            entries = os.listdir(folder)
        except OSError:
            continue
        for entry in entries:
            if not entry.endswith(".desktop"):
                continue
            stem = entry[:-8].lower()
            # snap: "openshot-qt_openshot-qt"; flatpak: "org.kde.kdenlive"; distro: "org.kde.kdenlive" / "shotcut"
            keys = {stem, stem.split("_")[-1], stem.rsplit(".", 1)[-1]}
            if not keys & wanted:
                continue
            parsed = read_desktop(os.path.join(folder, entry))
            if not parsed:
                continue
            cmd = parsed[1]
            prog = cmd[0]
            if prog == "env":  # "env VAR=x /snap/bin/app"
                rest = [a for a in cmd[1:] if "=" not in a or a == _FILE]
                prog = rest[0] if rest else ""
            if prog and (os.path.isabs(prog) and os.access(prog, os.X_OK) or _which(prog)):
                return cmd
    return None


def _flatpak_has(app_id: str) -> bool:
    if not shutil.which("flatpak"):
        return False
    try:
        out = subprocess.run(["flatpak", "info", app_id], capture_output=True, timeout=4)
        return out.returncode == 0
    except Exception:
        return False


# -- macOS -----------------------------------------------------------------------------
def _mac_app(bundles: tuple[str, ...]) -> str | None:
    for base in ("/Applications", os.path.expanduser("~/Applications")):
        for bundle in bundles:
            path = os.path.join(base, bundle)
            if os.path.isdir(path):
                return path
    return None


# -- editor escolhido pelo usuário ---------------------------------------------------
def custom_command(path: str) -> list[str] | None:
    """Comando para abrir o programa que o usuário escolheu (executável, AppImage, .desktop, .lnk ou .app)."""
    path = (path or "").strip()
    if not path or not os.path.exists(path):
        return None
    low = path.lower()
    if low.endswith(".desktop"):
        parsed = read_desktop(path)
        return parsed[1] if parsed else None
    if MACOS and low.rstrip("/").endswith(".app"):
        return ["open", "-a", path]
    if WINDOWS and low.endswith(".lnk"):
        return [path]
    if os.path.isfile(path) and (WINDOWS or os.access(path, os.X_OK)):
        return [path]
    return None


def custom_name(path: str) -> str:
    """Nome amigável do programa escolhido."""
    if path.lower().endswith(".desktop"):
        parsed = read_desktop(path)
        if parsed:
            return parsed[0]
    base = os.path.basename(path.rstrip("/\\"))
    for ext in (".desktop", ".appimage", ".exe", ".lnk", ".app"):
        if base.lower().endswith(ext):
            base = base[: -len(ext)]
    return base.split("-x86_64")[0].split("_")[0] or base


def editor_family(cmd: list[str]) -> str | None:
    """Reconhece Kdenlive, Shotcut ou OpenShot num comando qualquer (inclusive o escolhido pelo usuário)."""
    text = " ".join(a.lower() for a in cmd if a != _FILE)
    for key in ("kdenlive", "shotcut", "openshot"):
        if key in text:
            return key
    return None


# -- busca dos editores recomendados -------------------------------------------------
def editor_command(app: str, custom_path: str | None = None) -> list[str] | None:
    if app == CUSTOM:
        return custom_command(custom_path or "")
    name, cmds, flatpak_id = EDITORS.get(app, EDITORS["kdenlive"])
    for c in cmds:
        found = shutil.which(c) if (WINDOWS or MACOS) else _which(c)
        if found:
            return [found]
    if WINDOWS:
        from ..platform.win import find_program

        exe, *folders = _WIN_PATHS.get(app, _WIN_PATHS["kdenlive"])
        path = find_program(exe, *folders)
        return [path] if path else None
    if MACOS:
        bundle = _mac_app(_MAC_APPS.get(app, _MAC_APPS["kdenlive"]))
        return ["open", "-a", bundle] if bundle else None
    if _flatpak_has(flatpak_id):
        return ["flatpak", "run", flatpak_id]
    return _from_desktop(cmds, flatpak_id) or (lambda p: [p] if p else None)(_appimage(cmds))


def installed_editors() -> list[str]:
    return [key for key in EDITORS if editor_command(key)]


def probe(path: str) -> dict:
    """Largura, altura, fps, duração e presença de áudio."""
    info = {
        "width": 1920, "height": 1080, "fps_num": 30, "fps_den": 1, "duration": 0.0, "audio": False, "frames": 0,
        "vcodec": "h264", "acodec": "", "sample_rate": 48000, "channels": 2, "audio_index": -1, "video_index": 0,
    }
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path],
            capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace",
            creationflags=0x08000000 if WINDOWS else 0,  # CREATE_NO_WINDOW: sem janela de console piscando
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
                info["vcodec"] = st.get("codec_name", "h264")
                info["video_index"] = int(st.get("index", 0))
            elif st.get("codec_type") == "audio" and not info["audio"]:
                info["audio"] = True
                info["acodec"] = st.get("codec_name", "")
                info["sample_rate"] = int(st.get("sample_rate") or 48000)
                info["channels"] = int(st.get("channels") or 2)
                info["audio_index"] = int(st.get("index", 1))
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


def kdenlive_profile(info: dict, flatpak: bool = False, snap: bool = False) -> str:
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
    elif snap:
        data = os.path.expanduser("~/snap/kdenlive/current/.local/share")
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


def build_kdenlive_project(video: str, project_path: str, flatpak: bool = False, snap: bool = False) -> str:
    """Cria o arquivo .kdenlive com o clipe na linha do tempo e devolve o caminho."""
    info = probe(video)
    if WINDOWS:
        video = video.replace("\\", "/")  # o MLT/Kdenlive usa barras normais nos caminhos do projeto
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
        "kdenlive:docproperties.profile": kdenlive_profile(info, flatpak, snap),
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


def build_shotcut_project(video: str, project_path: str) -> str:
    """Projeto do Shotcut (MLT XML) com a gravação na trilha V1 da linha do tempo."""
    info = probe(video)
    if WINDOWS:
        video = video.replace("\\", "/")  # o MLT usa barras normais nos caminhos do projeto
    fps = info["fps_num"] / info["fps_den"]
    frames = info["frames"]
    out_tc = _tc(frames - 1, fps)
    zero = "00:00:00.000"
    w, h = info["width"], info["height"]
    pf = _profile_fields(info)
    name = os.path.basename(video)
    clip = {
        "length": frames, "eof": "pause", "resource": video, "mlt_service": "avformat-novalidate", "seekable": 1,
        "audio_index": info["audio_index"] if info["audio"] else -1, "video_index": info["video_index"],
        "mute_on_pause": 0, "shotcut:caption": name, "xml": "was here",
    }
    x = [
        '<?xml version="1.0" standalone="no"?>\n',
        f'<mlt LC_NUMERIC="C" version="7.14.0" title="GCP Capture Studio" producer="main_bin" root="{escape(os.path.dirname(video))}">\n',
        f' <profile description="{escape(pf["description"])}" width="{w}" height="{h}" progressive="1" sample_aspect_num="1" '
        f'sample_aspect_den="1" display_aspect_num="{pf["display_aspect_num"]}" display_aspect_den="{pf["display_aspect_den"]}" '
        f'frame_rate_num="{info["fps_num"]}" frame_rate_den="{info["fps_den"]}" colorspace="709"/>\n',
        f' <producer id="producer0" in="{zero}" out="{out_tc}">\n{_props(clip)} </producer>\n',
        ' <playlist id="main_bin">\n  <property name="xml_retain">1</property>\n'
        f'  <entry producer="producer0" in="{zero}" out="{out_tc}"/>\n </playlist>\n',
        f' <producer id="black" in="{zero}" out="{out_tc}">\n'
        + _props({"length": frames, "eof": "pause", "resource": "0", "aspect_ratio": 1, "mlt_service": "color", "mlt_image_format": "rgba", "set.test_audio": 0})
        + " </producer>\n",
        f' <playlist id="background">\n  <entry producer="black" in="{zero}" out="{out_tc}"/>\n </playlist>\n',
        f' <producer id="producer1" in="{zero}" out="{out_tc}">\n{_props(clip)} </producer>\n',
        ' <playlist id="playlist0">\n  <property name="shotcut:video">1</property>\n  <property name="shotcut:name">V1</property>\n'
        f'  <entry producer="producer1" in="{zero}" out="{out_tc}"/>\n </playlist>\n',
        f' <tractor id="tractor0" title="GCP Capture Studio" in="{zero}" out="{out_tc}">\n'
        '  <property name="shotcut">1</property>\n  <property name="shotcut:projectAudioChannels">2</property>\n'
        '  <property name="shotcut:projectFolder">0</property>\n'
        '  <track producer="background"/>\n  <track producer="playlist0"/>\n'
        '  <transition id="transition0"><property name="a_track">0</property><property name="b_track">1</property>'
        '<property name="mlt_service">mix</property><property name="always_active">1</property><property name="sum">1</property></transition>\n'
        '  <transition id="transition1"><property name="a_track">0</property><property name="b_track">1</property>'
        '<property name="version">0.1</property><property name="mlt_service">frei0r.cairoblend</property>'
        '<property name="threads">0</property><property name="disable">1</property></transition>\n'
        " </tractor>\n</mlt>\n",
    ]
    with open(project_path, "w", encoding="utf-8") as fh:
        fh.write("".join(x))
    return project_path


def build_openshot_project(video: str, project_path: str) -> str:
    """Projeto do OpenShot (.osp) com a gravação no início da trilha de cima da linha do tempo."""
    import uuid

    info = probe(video)
    w, h = info["width"], info["height"]
    pf = _profile_fields(info)
    fps = {"num": info["fps_num"], "den": info["fps_den"]}
    dur = max(info["duration"], info["frames"] * info["fps_den"] / info["fps_num"])
    rid = lambda: uuid.uuid4().hex[:10].upper()  # noqa: E731
    file_id, clip_id = rid(), rid()
    reader = {
        "type": "FFmpegReader", "path": video, "media_type": "video",
        "has_video": True, "has_audio": info["audio"], "has_single_image": False,
        "duration": dur, "file_size": str(os.path.getsize(video)) if os.path.exists(video) else "0",
        "width": w, "height": h, "pixel_format": 0, "fps": fps, "video_bit_rate": 0,
        "pixel_ratio": {"num": 1, "den": 1},
        "display_ratio": {"num": pf["display_aspect_num"], "den": pf["display_aspect_den"]},
        "vcodec": info["vcodec"], "video_length": str(info["frames"]), "video_stream_index": info["video_index"],
        "video_timebase": {"num": info["fps_den"], "den": info["fps_num"]},
        "interlaced_frame": False, "top_field_first": True,
        "acodec": info["acodec"], "audio_bit_rate": 0, "sample_rate": info["sample_rate"], "channels": info["channels"],
        "channel_layout": 3 if info["channels"] == 2 else 4, "audio_stream_index": info["audio_index"] if info["audio"] else -1,
        "audio_timebase": {"num": 1, "den": info["sample_rate"]}, "metadata": {},
    }
    project = {
        "id": rid(),
        "fps": fps, "width": w, "height": h,
        "display_ratio": {"num": pf["display_aspect_num"], "den": pf["display_aspect_den"]},
        "pixel_ratio": {"num": 1, "den": 1},
        "sample_rate": info["sample_rate"], "channels": 2, "channel_layout": 3,
        "profile": pf["description"],
        "duration": max(300.0, dur + 5),
        "files": [{**reader, "id": file_id}],
        "clips": [{
            "id": clip_id, "file_id": file_id, "title": os.path.basename(video),
            "layer": 5000000, "position": 0.0, "start": 0.0, "end": dur, "duration": dur,
            "reader": reader, "effects": [],
        }],
        "effects": [], "markers": [], "history": {"undo": [], "redo": []},
        "version": {"openshot-qt": "3.4.0", "libopenshot": "0.4.0"},
    }
    with open(project_path, "w", encoding="utf-8") as fh:
        json.dump(project, fh, indent=1, ensure_ascii=False)
    return project_path


_PROJECTS = {  # extensão e gerador do projeto de cada família de editor
    "kdenlive": (".kdenlive", None),
    "shotcut": (".mlt", build_shotcut_project),
    "openshot": (".osp", build_openshot_project),
}


def _resolve(app: str, custom_path: str | None) -> tuple[str, list[str]] | None:
    """Editor escolhido; se não estiver disponível, o primeiro recomendado que estiver instalado."""
    cmd = editor_command(app, custom_path)
    if cmd:
        return app, cmd
    for other in installed_editors():
        return other, editor_command(other)
    return None


def editor_name(app: str, custom_path: str | None = None) -> str:
    if app == CUSTOM:
        return custom_name(custom_path or "") or "editor"
    return EDITORS.get(app, EDITORS["kdenlive"])[0]


def open_in_editor(video: str, app: str = "kdenlive", custom_path: str | None = None) -> tuple[bool, str]:
    """Abre a gravação no editor. Retorna (sucesso, mensagem)."""
    found = _resolve(app, custom_path)
    if found is None:
        return False, "Nenhum editor de vídeo encontrado. Instale o Kdenlive ou escolha o seu editor em Configurações › Geral."
    app, cmd = found
    name = editor_name(app, custom_path)
    try:
        # Kdenlive, Shotcut e OpenShot (escolhidos na lista ou como editor personalizado) recebem um
        # projeto próprio com a gravação já na linha do tempo; outros editores recebem o arquivo de vídeo
        family = app if app in _PROJECTS else editor_family(cmd)
        if family:
            ext, builder = _PROJECTS[family]
            project = os.path.splitext(video)[0] + ext
            if not os.path.exists(project):
                if family == "kdenlive":
                    joined = " ".join(cmd)
                    build_kdenlive_project(video, project, flatpak="flatpak" in joined, snap="/snap/" in joined)
                else:
                    builder(video, project)
            args = _with_file(cmd, project)
        else:
            args = _with_file(cmd, video)
        _spawn(args)
        return True, f"Gravação enviada ao {name}."
    except Exception as exc:  # noqa: BLE001
        return False, f"Não foi possível abrir o {name}: {exc}"


def launch_editor(app: str = "kdenlive", custom_path: str | None = None) -> bool:
    found = _resolve(app, custom_path)
    if not found:
        return False
    _spawn([a for a in found[1] if a != _FILE])
    return True
