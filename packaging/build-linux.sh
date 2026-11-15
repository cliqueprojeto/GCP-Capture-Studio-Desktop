#!/bin/sh
# Gera os instaladores .deb (Debian/Ubuntu/Mint) e .rpm (Fedora/openSUSE) em dist/.
set -e
here="$(cd "$(dirname "$0")" && pwd)"
root="$here/.."
ver="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$root/gcp_capture_studio/__init__.py")"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$root/dist"
desc="Gravador de tela com anotações em tempo real e editor de vídeo integrado"

# ---------------------------------------------------------------- .deb
deb="$root/dist/GCP-Capture-Studio-$ver-linux-all.deb"
sh "$here/stage.sh" "$work/deb"
mkdir -p "$work/deb-control"
size="$(du -sk "$work/deb" | cut -f1)"
cat > "$work/deb-control/control" <<CTRL
Package: gcp-capture-studio
Version: $ver
Section: video
Priority: optional
Architecture: all
Maintainer: Bruno Albertini <cliqueprojeto@users.noreply.github.com>
Installed-Size: $size
Depends: python3 (>= 3.10), python3-pyside6.qtcore, python3-pyside6.qtgui, python3-pyside6.qtwidgets, python3-pyside6.qtnetwork, python3-pyside6.qtmultimedia, python3-pyside6.qtsvg, python3-gi, python3-gi-cairo, python3-cairo, gir1.2-gstreamer-1.0, gir1.2-gst-plugins-base-1.0, gstreamer1.0-plugins-base, gstreamer1.0-plugins-good, gstreamer1.0-plugins-bad, gstreamer1.0-plugins-ugly, gstreamer1.0-libav, gstreamer1.0-pipewire, gstreamer1.0-pulseaudio, pulseaudio-utils, ffmpeg, xdg-user-dirs, xwayland
Recommends: kdenlive, xdg-desktop-portal, pipewire-pulse
Homepage: https://github.com/cliqueprojeto/GCP-Capture-Studio-Desktop
Description: $desc
 Grave a tela com desenhos, lupa, zoom e efeitos do mouse em tempo real
 e envie a gravação direto para a linha do tempo do editor de vídeo.
 Desenvolvido por Bruno Albertini | Gestão Cultural Pro.
CTRL
if command -v dpkg-deb >/dev/null 2>&1; then
  mkdir -p "$work/deb/DEBIAN"
  cp "$work/deb-control/control" "$work/deb/DEBIAN/control"
  dpkg-deb --root-owner-group --build "$work/deb" "$deb" >/dev/null
else
  # sem dpkg: monta o arquivo .deb manualmente (ar + tar)
  (cd "$work/deb-control" && tar --owner=0 --group=0 -cJf "$work/control.tar.xz" ./control)
  (cd "$work/deb" && tar --owner=0 --group=0 -cJf "$work/data.tar.xz" ./usr)
  printf '2.0\n' > "$work/debian-binary"
  rm -f "$deb"
  (cd "$work" && ar rc "$deb" debian-binary control.tar.xz data.tar.xz)
fi
echo "ok: $deb"

# ---------------------------------------------------------------- .rpm
if command -v rpmbuild >/dev/null 2>&1; then
  sh "$here/stage.sh" "$work/rpm-root"
  cat > "$work/app.spec" <<SPEC
Name:           gcp-capture-studio
Version:        $ver
Release:        1
Summary:        $desc
License:        GPL-3.0-or-later
URL:            https://github.com/cliqueprojeto/GCP-Capture-Studio-Desktop
BuildArch:      noarch
AutoReqProv:    no
Requires:       python3 >= 3.10
Requires:       python3-pyside6
Requires:       python3-gobject
Requires:       python3-cairo
Requires:       gstreamer1
Requires:       gstreamer1-plugins-base
Requires:       gstreamer1-plugins-good
Requires:       gstreamer1-plugins-bad-free
Requires:       pipewire-gstreamer
Requires:       pulseaudio-utils
Requires:       xdg-user-dirs
Requires:       xorg-x11-server-Xwayland
Recommends:     gstreamer1-plugins-ugly-free
Recommends:     gstreamer1-plugin-openh264
Recommends:     gstreamer1-plugin-libav
Recommends:     ffmpeg-free
Recommends:     kdenlive
Recommends:     xdg-desktop-portal

%global __os_install_post %{nil}
%global _build_id_links none
%global debug_package %{nil}

%description
Grave a tela com desenhos, lupa, zoom e efeitos do mouse em tempo real
e envie a gravação direto para a linha do tempo do editor de vídeo.
Desenvolvido por Bruno Albertini | Gestão Cultural Pro.

%install
mkdir -p %{buildroot}
cp -a "$work/rpm-root/." %{buildroot}/

%files
/usr/bin/gcp-capture-studio
/usr/lib/gcp-capture-studio
/usr/share/applications/br.com.gestaoculturalpro.CaptureStudio.desktop
/usr/share/icons/hicolor/scalable/apps/gcp-capture-studio.svg
/usr/share/licenses/gcp-capture-studio
SPEC
  rpmbuild -bb --quiet --define "_topdir $work/rpmbuild" --define "_rpmdir $work/out" "$work/app.spec"
  rpm="$root/dist/GCP-Capture-Studio-$ver-linux-noarch.rpm"
  cp "$work"/out/noarch/*.rpm "$rpm"
  echo "ok: $rpm"
else
  echo "rpmbuild não encontrado: o .rpm não foi gerado" >&2
fi
