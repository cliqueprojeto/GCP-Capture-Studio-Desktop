#!/bin/sh
# Monta a árvore de instalação (/usr/...) em um diretório. Uso: stage.sh <destino>
set -e
here="$(cd "$(dirname "$0")" && pwd)"
src="$here/.."
dest="$1"
install -d "$dest/usr/lib/gcp-capture-studio"
cp -r "$src/gcp_capture_studio" "$dest/usr/lib/gcp-capture-studio/"
find "$dest/usr/lib/gcp-capture-studio" -name '__pycache__' -type d -prune -exec rm -rf {} +
install -Dm755 "$here/gcp-capture-studio" "$dest/usr/bin/gcp-capture-studio"
install -Dm644 "$here/br.com.gestaoculturalpro.CaptureStudio.desktop" \
  "$dest/usr/share/applications/br.com.gestaoculturalpro.CaptureStudio.desktop"
install -Dm644 "$src/gcp_capture_studio/assets/logo.svg" \
  "$dest/usr/share/icons/hicolor/scalable/apps/gcp-capture-studio.svg"
install -Dm644 "$src/LICENSE" "$dest/usr/share/licenses/gcp-capture-studio/LICENSE"
