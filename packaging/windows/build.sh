#!/bin/sh
# Gera a pasta do programa para Windows (PyInstaller) dentro do MSYS2 UCRT64.
# Pacotes necessários: veja .github/workflows/release.yml
set -e
cd "$(dirname "$0")/../.."
rm -rf build "dist/GCP Capture Studio"
pyinstaller --noconfirm --clean --windowed \
  --name "GCP Capture Studio" \
  --paths . \
  --icon packaging/windows/app.ico \
  --add-data "gcp_capture_studio/assets;gcp_capture_studio/assets" \
  --add-binary "$(cygpath -m "$(command -v ffmpeg.exe)");." \
  --add-binary "$(cygpath -m "$(command -v ffprobe.exe)");." \
  --collect-submodules gcp_capture_studio \
  --hidden-import gi --hidden-import cairo --hidden-import gi._gi_cairo \
  --exclude-module tkinter \
  packaging/windows/run.py
echo "ok: dist/GCP Capture Studio"
