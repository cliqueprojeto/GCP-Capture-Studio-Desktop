"""Janela de atualização: mostra as novidades da versão publicada, baixa e instala."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QProgressBar, QTextBrowser, QVBoxLayout

from .. import APP_NAME, __version__
from .widgets import button, label, open_url


class UpdateDialog(QDialog):
    def __init__(self, updater, info: dict, parent=None):
        super().__init__(parent)
        self.updater = updater
        self.info = info
        self.setWindowTitle(f"Atualização — {APP_NAME}")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.resize(560, 460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        lay.addWidget(label(f"Nova versão disponível: {info.get('version')}", "title"))
        lay.addWidget(label(f"Você está usando a versão {__version__}.", "muted"))
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(info.get("notes") or "Sem notas para esta versão.")
        lay.addWidget(notes, 1)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.hide()
        lay.addWidget(self.bar)
        self.status = label("", "small", wrap=True)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        page = button("Ver no GitHub", "external")
        page.clicked.connect(lambda: open_url(info.get("url", "")))
        row.addWidget(page)
        row.addStretch(1)
        later = button("Agora não")
        later.clicked.connect(self.reject)
        row.addWidget(later)
        self.go = button("Atualizar agora", "refresh", "primary")
        self.go.clicked.connect(self._start)
        row.addWidget(self.go)
        lay.addLayout(row)
        if not updater.can_install(info):
            self.go.setText("Baixar pelo GitHub")
            self.status.setText("Para este sistema a atualização é feita baixando o pacote na página de versões do GitHub.")
        updater.progress.connect(self._progress)
        updater.installed.connect(self._installed)

    def _start(self) -> None:
        if not self.updater.can_install(self.info):
            open_url(self.info.get("url", ""))
            self.accept()
            return
        self.go.setEnabled(False)
        self.bar.show()
        self.status.setText("Baixando a atualização…")
        self.updater.download_and_install(self.info)

    def _progress(self, pct: int) -> None:
        self.bar.setValue(pct)
        if pct >= 100:
            self.status.setText("Conferindo e instalando — o sistema pode pedir a sua senha.")

    def _installed(self, ok: bool, message: str) -> None:
        self.bar.hide()
        if ok and message == "exe":
            self.done(2)  # o instalador do Windows assume: o programa se encerra
            return
        self.status.setText(message)
        self.go.setEnabled(not ok)
        if ok:
            self.go.hide()

    def done(self, code: int) -> None:
        for sig, slot in ((self.updater.progress, self._progress), (self.updater.installed, self._installed)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        super().done(code)
