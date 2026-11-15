#!/bin/sh
# Gera o instalador .pkg.tar.zst (BigLinux / Manjaro / Arch).
set -e
cd "$(dirname "$0")"
rm -rf pkg src ./*.pkg.tar ./*.pkg.tar.zst
PKGEXT='.pkg.tar.zst' makepkg -f -d
rm -rf pkg src
mkdir -p ../dist
mv ./*.pkg.tar.zst ../dist/
echo
echo "Pacote gerado em: $(cd ../dist && pwd)"
ls -1 ../dist
