#!/bin/sh
# Gera o GCP Capture Studio.app e a imagem .dmg para macOS (Apple Silicon).
# Pré-requisitos (Homebrew): gstreamer pygobject3 py3cairo ffmpeg; PyInstaller e PySide6 num venv
# criado com --system-site-packages (veja .github/workflows/macos.yml).
set -e
cd "$(dirname "$0")/../.."
NAME="GCP Capture Studio"
VER=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' gcp_capture_studio/__init__.py)
ARCH=$(uname -m)
rm -rf build "dist/$NAME" "dist/$NAME.app" dist/macos
mkdir -p dist build

# ícone .icns a partir do logotipo
ICONSET=build/app.iconset
mkdir -p "$ICONSET"
python - "$ICONSET" <<'EOF'
import sys
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
app = QGuiApplication(["x", "-platform", "offscreen"])
svg = QSvgRenderer("gcp_capture_studio/assets/logo.svg")
for base in (16, 32, 128, 256, 512):
    for scale in (1, 2):
        px = base * scale
        img = QImage(px, px, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        svg.render(p, QRectF(0, 0, px, px))
        p.end()
        suffix = "" if scale == 1 else "@2x"
        img.save(f"{sys.argv[1]}/icon_{base}x{base}{suffix}.png")
EOF
iconutil -c icns "$ICONSET" -o build/app.icns
export APP_ICNS="$PWD/build/app.icns"

# o GStreamer examina os plugins num processo auxiliar
GST_SCANNER="$(brew --prefix gstreamer)/libexec/gstreamer-1.0/gst-plugin-scanner"
[ -f "$GST_SCANNER" ] || GST_SCANNER="$(find "$(brew --prefix)" -name gst-plugin-scanner -type f 2>/dev/null | head -n 1)"
export GST_SCANNER

# versão mínima do macOS: a mais alta exigida pelas bibliotecas do Homebrew incluídas
MIN_MACOS=$(otool -l "$(brew --prefix gstreamer)/lib/libgstreamer-1.0.0.dylib" | awk '/minos/{print $2; exit}')
export MIN_MACOS="${MIN_MACOS:-14.0}"
echo "macOS mínimo: $MIN_MACOS"

pyinstaller --noconfirm --clean --distpath dist --workpath build/pyi packaging/macos/app.spec

APP="dist/$NAME.app"
# ffmpeg e ffprobe com as próprias bibliotecas, isolados das do Qt Multimedia
FF="$APP/Contents/Frameworks/ffmpeg"
mkdir -p "$FF/lib"
cp "$(brew --prefix)/bin/ffmpeg" "$(brew --prefix)/bin/ffprobe" "$FF/"
chmod u+w "$FF/ffmpeg" "$FF/ffprobe"
dylibbundler -of -b -x "$FF/ffmpeg" -x "$FF/ffprobe" -d "$FF/lib" -p @executable_path/lib/ > build/dylibbundler.log
"$FF/ffmpeg" -hide_banner -version | head -n 1
# assinatura ad hoc de cada binário e do pacote inteiro (exigida para rodar em Apple Silicon)
find "$FF" -type f \( -name "*.dylib" -o -name ffmpeg -o -name ffprobe \) -exec codesign --force --sign - {} \;
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP" && echo "assinatura ok"

# imagem .dmg com atalho para a pasta Aplicativos
STAGE=dist/macos
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Aplicativos"
DMG="dist/GCP-Capture-Studio-$VER-macOS-$ARCH.dmg"
rm -f "$DMG"
hdiutil create -volname "$NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"
ls -la "$DMG"
echo "ok: $DMG"
