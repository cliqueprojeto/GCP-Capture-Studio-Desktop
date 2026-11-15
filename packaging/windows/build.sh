#!/bin/sh
# Gera a pasta do programa para Windows (PyInstaller) dentro do MSYS2 UCRT64.
# Pacotes necessários: veja .github/workflows/release.yml
set -e
cd "$(dirname "$0")/../.."
rm -rf build "dist/GCP Capture Studio"
# o GStreamer examina os plugins num processo auxiliar; sem ele, o exame é feito
# dentro do programa e alguns plugins não aceitam ser carregados duas vezes
SCANNER="$MINGW_PREFIX/libexec/gstreamer-1.0/gst-plugin-scanner.exe"
[ -f "$SCANNER" ] || SCANNER="$(find "$MINGW_PREFIX" -name gst-plugin-scanner.exe | head -n 1)"
[ -f "$SCANNER" ] || { echo "gst-plugin-scanner.exe não encontrado"; exit 1; }
pyinstaller --noconfirm --clean --windowed \
  --name "GCP Capture Studio" \
  --paths . \
  --icon packaging/windows/app.ico \
  --add-data "gcp_capture_studio/assets;gcp_capture_studio/assets" \
  --add-binary "$(cygpath -m "$(command -v ffmpeg.exe)");." \
  --add-binary "$(cygpath -m "$(command -v ffprobe.exe)");." \
  --add-binary "$(cygpath -m "$SCANNER");." \
  --collect-submodules gcp_capture_studio \
  --hidden-import gi --hidden-import cairo --hidden-import gi._gi_cairo \
  --exclude-module tkinter \
  packaging/windows/run.py
# os plugins do GStreamer baseados no FFmpeg não são usados pela gravação e trazem
# bibliotecas que falham ao serem carregadas dentro do programa; o ffmpeg.exe continua incluído
for f in "dist/GCP Capture Studio/_internal"/gst_plugins/*.dll; do
  if objdump -p "$f" 2>/dev/null | grep -qiE "DLL Name: (avfilter|avcodec|avformat)"; then
    echo "removido: $(basename "$f")"; rm -f "$f"
  fi
done
echo "ok: dist/GCP Capture Studio"
