"""Conferência automática no macOS (usada na geração do instalador).

Grava alguns segundos da tela pelo mesmo motor do programa, confere o arquivo com o ffprobe e testa
os atalhos globais, a leitura de cliques/teclas, a exclusão de janelas da captura e a lista de monitores.
Uso: python packaging/macos/check.py <pasta de saída>
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

app = QApplication(sys.argv[:1])

from gcp_capture_studio.config import default_shortcuts  # noqa: E402
from gcp_capture_studio.engine import audio, encoders  # noqa: E402
from gcp_capture_studio.engine.recorder import CaptureSource, Recorder, RecordOptions  # noqa: E402
from gcp_capture_studio.platform import mac  # noqa: E402
from gcp_capture_studio.platform.clicks import ClickWatcher  # noqa: E402
from gcp_capture_studio.platform.hotkeys import GlobalHotkeys  # noqa: E402

out_dir = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "saida-mac")
results: dict[str, object] = {}
ok = True


def check(name: str, value, good: bool) -> None:
    global ok
    results[name] = value
    ok = ok and good
    print(f"{'ok   ' if good else 'FALHA'} {name}: {value}", flush=True)


screen = app.primaryScreen()
geo, dpr = screen.geometry(), screen.devicePixelRatio()
check("monitores (CoreGraphics)", mac.displays(), bool(mac.displays()))
check("monitor principal no avfvideosrc", mac.display_index(geo.x(), geo.y()), True)
check("codificadores", [e.id for e in encoders.available()], bool(encoders.available()))
check("microfones", [d.label for d in audio.microphones()], True)

hk = GlobalHotkeys()
hk.apply(default_shortcuts())
check("atalhos globais", f"{hk.backend}: {len(hk._win._ids) if hk._win else 0} registrados", hk.backend == "win" and bool(hk._win._ids))
hk.shutdown()

w = QWidget()
w.resize(200, 120)
w.show()
app.processEvents()
check("janela fora da captura", mac.exclude_from_capture(w), mac.exclude_from_capture(w))
w.close()

watch = ClickWatcher()
check("leitura de cliques/teclas", watch.configure(True, True), watch.running)
watch.stop()

rec = Recorder()
size = (round(geo.width() * dpr), round(geo.height() * dpr))
src = CaptureSource(kind="mac", size=size, show_cursor=True, handle=mac.display_index(geo.x(), geo.y()))
opts = RecordOptions(fps=30, quality="media", out_dir=out_dir, basename="teste-mac", mic=audio.resolve_mic("default"))
final: dict[str, str] = {}
rec.finished.connect(lambda p: (final.update(path=p), app.quit()))
rec.failed.connect(lambda m: (final.update(error=m), app.quit()))
rec.started.connect(lambda: QTimer.singleShot(4000, rec.stop))
QTimer.singleShot(0, lambda: rec.start(src, opts))
QTimer.singleShot(60000, app.quit)
app.exec()

if "path" in final:
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", final["path"]],
        capture_output=True, text=True,
    ).stdout or "{}")
    v = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), {})
    au = next((s for s in probe.get("streams", []) if s.get("codec_type") == "audio"), {})
    check("áudio do microfone", f"{au.get('codec_name')} {au.get('sample_rate')} Hz {au.get('channels')} canais", au.get("codec_name") == "aac")
    dur = float(probe.get("format", {}).get("duration", 0) or 0)
    check("gravação da tela", f"{os.path.basename(final['path'])} {v.get('width')}x{v.get('height')} {v.get('codec_name')} {dur:.1f}s",
          v.get("codec_name") == "h264" and dur >= 2.5)
    # quadro do meio salvo para conferência visual
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "2", "-i", final["path"], "-frames:v", "1",
                    os.path.join(out_dir, "quadro.png")])
else:
    check("gravação da tela", final.get("error", "sem resposta"), False)

print("RESULTADO:", "OK" if ok else "FALHOU")
sys.exit(0 if ok else 1)
