# Empacotamento do aplicativo do macOS (PyInstaller). Usado por packaging/macos/build.sh.
import os
import re

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))  # noqa: F821 (definido pelo PyInstaller)
NAME = "GCP Capture Studio"
with open(os.path.join(ROOT, "gcp_capture_studio", "__init__.py"), encoding="utf-8") as fh:
    VERSION = re.search(r'__version__ = "([^"]+)"', fh.read()).group(1)

# o ffmpeg/ffprobe vão numa pasta própria (build.sh): o Qt Multimedia traz bibliotecas do FFmpeg
# com os mesmos nomes e versão diferente
binaries = []
scanner = os.environ.get("GST_SCANNER")
if scanner:
    binaries.append((scanner, "."))

# apenas os plugins do GStreamer que a gravação usa (os demais trariam GTK, Qt e Python do sistema)
PLUGINS = [
    "coreelements", "app", "videoconvertscale", "videorate", "videocrop", "videotestsrc", "audiotestsrc",
    "audioconvert", "audioresample", "volume", "level", "audiomixer", "autodetect", "playback",
    "typefindfunctions", "matroska", "isomp4", "videoparsersbad", "audioparsers", "wavenc", "wavparse",
    "cairo", "applemedia", "osxaudio", "x264", "opus",
]

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "packaging", "macos", "run.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=[(os.path.join(ROOT, "gcp_capture_studio", "assets"), "gcp_capture_studio/assets")],
    hiddenimports=collect_submodules("gcp_capture_studio") + ["gi", "cairo", "gi._gi_cairo"],
    hooksconfig={
        "gstreamer": {"include_plugins": PLUGINS},
        "gi": {"module-versions": {"Gst": "1.0"}},
    },
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2"],
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=False, argv_emulation=False,
    codesign_identity=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME)  # noqa: F821
app = BUNDLE(  # noqa: F821
    coll,
    name=f"{NAME}.app",
    icon=os.environ.get("APP_ICNS"),
    bundle_identifier="br.com.gestaoculturalpro.CaptureStudio",
    version=VERSION,
    info_plist={
        "CFBundleName": NAME,
        "CFBundleDisplayName": NAME,
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": os.environ.get("MIN_MACOS", "14.0"),
        "LSApplicationCategoryType": "public.app-category.video",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "Bruno Albertini · Gestão Cultural Pro · GPL-3.0-or-later",
        "NSMicrophoneUsageDescription": "O GCP Capture Studio grava o seu microfone junto com a tela.",
        "NSCameraUsageDescription": "O GCP Capture Studio mostra a sua webcam na gravação.",
        "NSAudioCaptureUsageDescription": "O GCP Capture Studio grava o som do sistema junto com a tela.",
    },
)
