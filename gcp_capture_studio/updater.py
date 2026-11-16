"""Atualizações pelo GitHub: consulta a versão publicada, baixa o pacote do sistema e instala.

Só o repositório público do projeto é consultado; nenhum dado do usuário é enviado.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

from PySide6.QtCore import QObject, QProcess, QStandardPaths, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from . import GITHUB_REPO, __version__

API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"
FREQUENCIES = [
    ("Sempre que abrir o programa", "startup"),
    ("Uma vez por dia", "daily"),
    ("Uma vez por semana", "weekly"),
    ("Nunca (só quando eu pedir)", "never"),
]


def parse_version(text: str) -> tuple[int, ...]:
    out = []
    for part in str(text).strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def package_kind() -> str | None:
    """Formato de pacote deste sistema: exe, pkg, deb, rpm (ou None se desconhecido)."""
    if sys.platform.startswith("win"):
        return "exe"
    if sys.platform == "darwin":
        return "dmg"
    if not sys.platform.startswith("linux"):
        return None
    info = {}
    try:
        with open("/etc/os-release", encoding="utf-8") as fh:
            for line in fh:
                if "=" in line:
                    k, v = line.rstrip().split("=", 1)
                    info[k] = v.strip('"').lower()
    except OSError:
        pass
    ids = {info.get("ID", "")} | set(info.get("ID_LIKE", "").split())
    if ids & {"arch", "manjaro", "biglinux", "endeavouros", "cachyos"} or shutil.which("pacman"):
        return "pkg"
    if ids & {"debian", "ubuntu", "linuxmint", "pop"} or shutil.which("apt-get"):
        return "deb"
    if ids & {"fedora", "rhel", "centos", "suse", "opensuse"} or shutil.which("dnf") or shutil.which("zypper"):
        return "rpm"
    return None


_SUFFIX = {"exe": ".exe", "dmg": ".dmg", "pkg": ".pkg.tar.zst", "deb": ".deb", "rpm": ".rpm"}


def install_command(kind: str, path: str) -> list[str] | None:
    """Comando gráfico (pede a senha pelo sistema) que instala o pacote baixado."""
    pkexec = shutil.which("pkexec")
    if kind == "exe" or not pkexec:
        return None
    if kind == "pkg":
        return [pkexec, "pacman", "-U", "--noconfirm", path]
    if kind == "deb":
        return [pkexec, "apt-get", "install", "-y", path]
    if kind == "rpm":
        if shutil.which("dnf"):
            return [pkexec, "dnf", "install", "-y", path]
        if shutil.which("zypper"):
            return [pkexec, "zypper", "--non-interactive", "install", "--allow-unsigned-rpm", path]
    return None


def due(settings) -> bool:
    """Está na hora da verificação automática, conforme a frequência escolhida?"""
    freq = settings.get("updates.frequency", "startup")
    if freq == "never":
        return False
    if freq == "startup":
        return True
    try:
        last = datetime.fromisoformat(settings.get("updates.last_check") or "")
    except ValueError:
        return True
    return datetime.now() - last >= (timedelta(days=1) if freq == "daily" else timedelta(days=7))


class Updater(QObject):
    checked = Signal(dict)  # status: newer | current | error (+ version, notes, url, asset, asset_url, sums_url, message)
    progress = Signal(int)  # 0..100 do download
    installed = Signal(bool, str)  # sucesso, mensagem

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.net = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._file = None
        self._proc: QProcess | None = None
        self.busy = False

    def _request(self, url: str) -> QNetworkRequest:
        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"User-Agent", b"GCP-Capture-Studio-Updater")
        req.setRawHeader(b"Accept", b"application/vnd.github+json" if "api.github.com" in url else b"application/octet-stream")
        req.setTransferTimeout(20000)
        return req

    # -- verificação -----------------------------------------------------------
    def check(self) -> None:
        if self.busy:
            return
        self.busy = True
        reply = self.net.get(self._request(API_LATEST))
        reply.finished.connect(lambda: self._checked(reply))

    def _checked(self, reply: QNetworkReply) -> None:
        self.busy = False
        code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        data = bytes(reply.readAll())
        failed = reply.error() != QNetworkReply.NoError
        reply.deleteLater()
        if code == 404:
            # repositório sem versões publicadas ainda
            self.settings.set("updates.last_check", datetime.now().isoformat(timespec="minutes"))
            self.checked.emit({"status": "current", "version": __version__})
            return
        if failed:
            self.checked.emit({"status": "error", "message": "Não foi possível consultar o GitHub. Verifique a conexão com a internet."})
            return
        try:
            rel = json.loads(data.decode("utf-8"))
            version = str(rel.get("tag_name") or "").lstrip("vV")
        except Exception:  # noqa: BLE001
            self.checked.emit({"status": "error", "message": "Resposta inesperada do GitHub."})
            return
        self.settings.set("updates.last_check", datetime.now().isoformat(timespec="minutes"))
        info = {"status": "current", "version": version, "notes": rel.get("body") or "", "url": rel.get("html_url") or RELEASES_URL}
        if parse_version(version) > parse_version(__version__):
            info["status"] = "newer"
            kind = package_kind()
            suffix = _SUFFIX.get(kind or "")
            for asset in rel.get("assets") or []:
                name = asset.get("name", "")
                if suffix and name.endswith(suffix):
                    info.update(asset=name, asset_url=asset.get("browser_download_url"), kind=kind)
                elif name.upper().startswith("SHA256SUMS"):
                    info["sums_url"] = asset.get("browser_download_url")
        self.checked.emit(info)

    # -- download e instalação ---------------------------------------------------
    def can_install(self, info: dict) -> bool:
        return bool(info.get("asset_url")) and (info.get("kind") in ("exe", "dmg") or install_command(info.get("kind", ""), "x") is not None)

    def download_and_install(self, info: dict) -> None:
        if self.busy or not info.get("asset_url"):
            return
        self.busy = True
        base = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation) or QStandardPaths.writableLocation(QStandardPaths.TempLocation)
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, info["asset"])
        self._file = open(path, "wb")  # noqa: SIM115
        reply = self.net.get(self._request(info["asset_url"]))
        self._reply = reply
        reply.readyRead.connect(lambda: self._file.write(bytes(reply.readAll())))
        reply.downloadProgress.connect(lambda got, total: self.progress.emit(int(got * 100 / total) if total > 0 else 0))
        reply.finished.connect(lambda: self._downloaded(reply, info, path))

    def _fail(self, text: str) -> None:
        self.busy = False
        self.installed.emit(False, text)

    def _downloaded(self, reply: QNetworkReply, info: dict, path: str) -> None:
        self._file.write(bytes(reply.readAll()))
        self._file.close()
        failed = reply.error() != QNetworkReply.NoError
        reply.deleteLater()
        self._reply = None
        if failed:
            self._fail("O download da atualização falhou. Tente de novo ou baixe pelo GitHub.")
            return
        if not info.get("sums_url"):
            self._install(info, path)
            return
        sums = self.net.get(self._request(info["sums_url"]))
        sums.finished.connect(lambda: self._verify(sums, info, path))

    def _verify(self, sums: QNetworkReply, info: dict, path: str) -> None:
        text = bytes(sums.readAll()).decode("utf-8", "replace")
        ok = sums.error() == QNetworkReply.NoError
        sums.deleteLater()
        expected = ""
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[-1].lstrip("*") == info["asset"]:
                expected = parts[0].lower()
        if not ok or not expected:
            self._fail("Não foi possível conferir a integridade do arquivo baixado. Baixe pelo GitHub.")
            return
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            self._fail("O arquivo baixado não confere com o publicado (SHA-256 diferente). A atualização foi cancelada.")
            return
        self._install(info, path)

    def _install(self, info: dict, path: str) -> None:
        kind = info.get("kind")
        if kind == "exe":
            try:
                subprocess.Popen([path], close_fds=True)  # o instalador fecha e substitui o programa
            except OSError as exc:
                self._fail(f"Não foi possível abrir o instalador: {exc}")
                return
            self.busy = False
            self.installed.emit(True, "exe")
            return
        if kind == "dmg":
            try:
                subprocess.Popen(["open", path], close_fds=True)  # abre a imagem: basta arrastar para Aplicativos
            except OSError as exc:
                self._fail(f"Não foi possível abrir o instalador: {exc}")
                return
            self.busy = False
            self.installed.emit(
                True,
                f"Versão {info['version']} baixada. Feche o programa e arraste o GCP Capture Studio da janela aberta "
                "para a pasta Aplicativos, substituindo o anterior.",
            )
            return
        cmd = install_command(kind or "", path)
        if not cmd:
            self._fail(f"Pacote salvo em {path}. Instale-o pelo gerenciador de pacotes do sistema.")
            return
        self._proc = QProcess(self)

        def done(code, _status):
            self.busy = False
            if code == 0:
                self.installed.emit(True, f"Versão {info['version']} instalada. Feche e abra o programa para usar a nova versão.")
            elif code in (126, 127):
                self.installed.emit(False, "A instalação foi cancelada (senha não informada).")
            else:
                self.installed.emit(False, f"A instalação falhou. O pacote está em {path}.")

        self._proc.finished.connect(done)
        self._proc.start(cmd[0], cmd[1:])
