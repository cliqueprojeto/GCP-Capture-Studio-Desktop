"""Configurações: geral, vídeo, áudio (com teste de microfone), efeitos e atalhos personalizáveis."""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QKeySequenceEdit, QLabel,
    QLineEdit, QScrollArea, QSlider, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__, theme
from ..config import SHORTCUT_ACTIONS, default_shortcuts
from ..editor import bridge
from ..engine import audio, encoders
from .widgets import DevFooter, LevelMeter, Swatch, Toggle, button, label, separator


class _Bench(QThread):
    done = Signal(dict)

    def run(self) -> None:
        self.done.emit(encoders.benchmark())


def _row(grid: QGridLayout, r: int, title: str, widget, hint: str = "") -> int:
    col = QVBoxLayout()
    col.setSpacing(1)
    col.addWidget(label(title))
    if hint:
        col.addWidget(label(hint, "small", wrap=True))
    grid.addLayout(col, r, 0)
    if isinstance(widget, QWidget):
        grid.addWidget(widget, r, 1, Qt.AlignRight | Qt.AlignVCenter)
    else:
        grid.addLayout(widget, r, 1)
    return r + 1


def _page() -> tuple[QWidget, QGridLayout]:
    page = QWidget()
    grid = QGridLayout(page)
    grid.setContentsMargins(4, 18, 12, 8)
    grid.setHorizontalSpacing(24)
    grid.setVerticalSpacing(16)
    grid.setColumnStretch(0, 1)
    return page, grid


def _scroll(page: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    holder = QWidget()
    lay = QVBoxLayout(holder)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(page)
    lay.addStretch(1)
    area.setWidget(holder)
    area.viewport().setStyleSheet("background: transparent;")
    holder.setStyleSheet("background: transparent;")
    return area


class SettingsDialog(QDialog):
    donate = Signal()

    def __init__(self, settings, hotkeys=None, parent=None, updater=None):
        super().__init__(parent)
        self.s = settings
        self.hotkeys = hotkeys
        self.updater = updater
        self.setWindowTitle(f"Configurações — {APP_NAME}")
        self.resize(760, 640)
        self.mic_test = audio.MicTest(self)
        self.meter_src = audio.LevelMonitor(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 18)
        root.setSpacing(6)
        root.addWidget(label("Configurações", "title"))
        tabs = QTabWidget()
        tabs.addTab(_scroll(self._general()), "Geral")
        tabs.addTab(_scroll(self._video()), "Vídeo")
        tabs.addTab(_scroll(self._audio()), "Áudio")
        tabs.addTab(_scroll(self._webcam()), "Webcam")
        tabs.addTab(_scroll(self._effects()), "Efeitos do mouse")
        tabs.addTab(_scroll(self._shortcuts()), "Atalhos")
        tabs.addTab(_scroll(self._about()), "Sobre")
        root.addWidget(tabs, 1)
        root.addWidget(separator())
        foot = QHBoxLayout()
        dev = DevFooter()
        dev.donate.connect(self.donate.emit)
        foot.addWidget(dev, 1)
        close = button("Concluir", role="primary")
        close.clicked.connect(self.accept)
        foot.addSpacing(16)
        foot.addWidget(close)
        root.addLayout(foot)

    # -- auxiliares ------------------------------------------------------------
    def _toggle(self, key: str) -> Toggle:
        t = Toggle(bool(self.s.get(key)))
        t.toggled.connect(lambda v: self.s.set(key, bool(v)))
        return t

    def _combo(self, key: str, items: list[tuple[str, object]], width: int = 260) -> QComboBox:
        c = QComboBox()
        c.setFixedWidth(width)
        for text, data in items:
            c.addItem(text, data)
        idx = c.findData(self.s.get(key))
        c.setCurrentIndex(max(0, idx))
        c.activated.connect(lambda _i: self.s.set(key, c.currentData()))
        return c

    def _slider(self, key: str, lo: int, hi: int, suffix: str = "", scale: float = 1.0) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        sl = QSlider(Qt.Horizontal)
        sl.setRange(lo, hi)
        sl.setFixedWidth(200)
        sl.setValue(int(round(float(self.s.get(key)) * scale)))
        txt = label("", "small")
        txt.setFixedWidth(48)
        txt.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        def fmt(v: int) -> None:
            txt.setText((f"{v / scale:.1f}" if scale != 1.0 else str(v)) + suffix)

        def changed(v: int) -> None:
            fmt(v)
            self.s.set(key, v / scale if scale != 1.0 else v)

        fmt(sl.value())
        sl.valueChanged.connect(changed)
        row.addStretch(1)
        row.addWidget(sl)
        row.addWidget(txt)
        return row

    def _color(self, key: str) -> Swatch:
        sw = Swatch(self.s.get(key), 26)
        sw.setCheckable(False)

        def pick() -> None:
            c = QColorDialog.getColor(QColor(self.s.get(key)), self, "Escolher cor")
            if c.isValid():
                self.s.set(key, c.name())
                sw.set_color(c.name())

        sw.clicked.connect(pick)
        return sw

    # -- páginas ---------------------------------------------------------------
    def _general(self) -> QWidget:
        page, g = _page()
        r = 0
        row = QHBoxLayout()
        self.out_dir = QLineEdit(self.s.get("capture.output_dir"))
        self.out_dir.setReadOnly(True)
        self.out_dir.setFixedWidth(300)
        pick = button("Alterar…", "folder")
        pick.clicked.connect(self._pick_dir)
        row.addStretch(1)
        row.addWidget(self.out_dir)
        row.addWidget(pick)
        r = _row(g, r, "Pasta das gravações", row)
        spin = QSpinBox()
        spin.setRange(0, 10)
        spin.setSuffix(" s")
        spin.setFixedWidth(90)
        spin.setValue(int(self.s.get("capture.countdown")))
        spin.valueChanged.connect(lambda v: self.s.set("capture.countdown", v))
        r = _row(g, r, "Contagem regressiva", spin, "Tempo antes de a gravação começar (0 desativa).")
        r = _row(g, r, "Mostrar o cursor do mouse no vídeo", self._toggle("capture.show_cursor"))
        r = _row(
            g, r, "Barra de gravação e ferramentas",
            self._combo("capture.bar_mode", [("Widget discreto (abre quando você expandir)", "widget"), ("Oculta (só bandeja e atalhos)", "hidden")], 300),
            "O widget é semitransparente, pode ser arrastado para qualquer canto e só expande quando você pedir. "
            "Trocar de ferramenta por atalho não abre a barra. No KDE Plasma ela nunca entra no vídeo.",
        )
        g.addWidget(separator(), r, 0, 1, 2)
        r += 1
        installed = bridge.installed_editors()
        items = [(bridge.EDITORS[k][0] + ("" if k in installed else " (não instalado)"), k) for k in bridge.EDITORS]
        r = _row(g, r, "Editor de vídeo integrado", self._combo("editor.app", items), "Kdenlive recebe a gravação já posicionada na linha do tempo.")
        r = _row(g, r, "Enviar ao editor ao terminar a gravação", self._toggle("editor.auto_open"))
        r = _row(
            g, r, "Fechar o gravador ao enviar ao editor", self._toggle("editor.close_after"),
            "Evita gravar por cima sem querer: depois de parar, fica aberto só o editor.",
        )
        if self.updater is not None:
            from .. import GITHUB_REPO
            from ..updater import FREQUENCIES

            g.addWidget(separator(), r, 0, 1, 2)
            r += 1
            self.upd_info = label("", "small", wrap=True)
            self._update_info(GITHUB_REPO)
            head = QVBoxLayout()
            head.setSpacing(3)
            head.addWidget(label("Atualizações"))
            head.addWidget(self.upd_info)
            g.addLayout(head, r, 0, 1, 2)
            r += 1
            r = _row(g, r, "Verificação automática", self._combo("updates.frequency", FREQUENCIES, 300), "Com que frequência procurar uma versão nova.")
            row = QHBoxLayout()
            self.upd_status = label("", "small", wrap=True)
            self.upd_btn = button("Verificar agora", "refresh")
            self.upd_btn.clicked.connect(self._check_updates)
            row.addWidget(self.upd_btn)
            row.addWidget(self.upd_status, 1)
            g.addLayout(row, r, 0, 1, 2)
            r += 1
            self.updater.checked.connect(self._update_checked)
        return page

    def _update_info(self, repo: str) -> None:
        last = self.s.get("updates.last_check") or ""
        try:
            from datetime import datetime

            when = datetime.fromisoformat(last).strftime("%d/%m/%Y, %H:%M")
        except ValueError:
            when = "nunca"
        self.upd_info.setText(
            f"Versão instalada: {__version__} · última verificação: {when}. "
            f"As novas versões vêm do repositório do projeto no GitHub ({repo})."
        )

    def _check_updates(self) -> None:
        self._manual_check = True
        self.upd_btn.setEnabled(False)
        self.upd_status.setText("Consultando o GitHub…")
        self.updater.check()

    def _update_checked(self, info: dict) -> None:
        from .. import GITHUB_REPO

        self.upd_btn.setEnabled(True)
        self._update_info(GITHUB_REPO)
        status = info.get("status")
        if status == "newer":
            self.upd_status.setText(f"Nova versão disponível: {info.get('version')}.")
        elif status == "current":
            self.upd_status.setText("Você já está com a versão mais recente.")
        else:
            self.upd_status.setText(info.get("message", "Não foi possível verificar."))

    def _pick_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Pasta das gravações", self.s.get("capture.output_dir"))
        if d:
            self.s.set("capture.output_dir", d)
            self.out_dir.setText(d)

    def _video(self) -> QWidget:
        page, g = _page()
        r = 0
        r = _row(g, r, "Quadros por segundo", self._combo("video.fps", [(f"{v} fps", v) for v in (15, 24, 30, 60)]), "30 fps é ideal para tutoriais; 60 fps para movimento intenso.")
        r = _row(
            g, r, "Qualidade",
            self._combo("video.quality", [("Leve (arquivos menores)", "baixa"), ("Média", "media"), ("Alta (recomendada)", "alta"), ("Máxima", "maxima")]),
        )
        encs = [("Automático (GPU quando disponível)", "auto")] + [(e.label, e.id) for e in encoders.available()]
        r = _row(g, r, "Codificador", self._combo("video.encoder", encs), "A GPU reduz o uso de CPU durante a gravação. Se falhar, o aplicativo volta para a CPU sozinho.")
        g.addWidget(separator(), r, 0, 1, 2)
        r += 1
        row = QHBoxLayout()
        self.bench_btn = button("Testar desempenho", "gpu")
        self.bench_btn.clicked.connect(self._bench)
        row.addStretch(1)
        row.addWidget(self.bench_btn)
        r = _row(g, r, "Otimização automática", row, "Mede cada codificador em 1080p e escolhe a combinação mais fluida para este computador.")
        self.bench_out = label("", "small", wrap=True)
        g.addWidget(self.bench_out, r, 0, 1, 2)
        if not any(e.hardware for e in encoders.available()):
            r += 1
            tip = label(
                "Nenhum codificador por GPU foi detectado no GStreamer. Em placas AMD/Intel, instale o pacote "
                "gst-plugin-va para habilitar a aceleração VA-API.", "small", wrap=True,
            )
            tip.setStyleSheet(f"color: {theme.WARN};")
            g.addWidget(tip, r, 0, 1, 2)
        return page

    def _bench(self) -> None:
        self.bench_btn.setEnabled(False)
        self.bench_out.setText("Medindo… isso leva alguns segundos.")
        self._bench_thread = _Bench(self)
        self._bench_thread.done.connect(self._bench_done)
        self._bench_thread.start()

    def _bench_done(self, res: dict) -> None:
        self.bench_btn.setEnabled(True)
        if not res:
            self.bench_out.setText("Não foi possível medir os codificadores.")
            return
        lines = [f"{encoders.BY_ID[k].label}: {v:.0f} quadros/s em 1080p" for k, v in sorted(res.items(), key=lambda kv: -kv[1])]
        hw = [k for k in res if encoders.BY_ID[k].hardware and res[k] >= 45]
        best = hw[0] if hw else max(res, key=res.get)
        fps = 60 if res[best] >= 110 else 30
        quality = "alta" if res[best] >= 55 else "media"
        self.s.set("video.encoder", best)
        self.s.set("video.fps", fps)
        self.s.set("video.quality", quality)
        lines.append(f"Aplicado: {encoders.BY_ID[best].label}, {fps} fps, qualidade {quality}.")
        self.bench_out.setText("\n".join(lines))

    def _audio(self) -> QWidget:
        page, g = _page()
        r = 0
        mics = [("Padrão do sistema", "default")] + [(d.label, d.name) for d in audio.microphones()]
        outs = [("Saída padrão do sistema", "default")] + [(d.label, d.name) for d in audio.outputs()]
        r = _row(g, r, "Gravar microfone", self._toggle("audio.mic_enabled"))
        self.mic_combo = self._combo("audio.mic_device", mics, 320)
        self.mic_combo.activated.connect(lambda _i: self._meter())
        r = _row(g, r, "Microfone", self.mic_combo, "Microfones internos, headsets e interfaces de áudio USB.")
        r = _row(g, r, "Volume do microfone", self._slider("audio.mic_volume", 0, 200, "%"))
        meter_row = QHBoxLayout()
        self.meter = LevelMeter(height=10)
        self.meter.setFixedWidth(250)
        meter_row.addStretch(1)
        meter_row.addWidget(self.meter)
        r = _row(g, r, "Nível de entrada", meter_row, "Fale normalmente: o ideal é ficar na faixa verde.")
        test_row = QHBoxLayout()
        self.test_btn = button("Testar microfone", "mic")
        self.test_btn.clicked.connect(self._mic_test)
        self.test_state = label("", "small")
        test_row.addStretch(1)
        test_row.addWidget(self.test_state)
        test_row.addWidget(self.test_btn)
        r = _row(g, r, "Teste de microfone", test_row, "Grava 4 segundos e reproduz em seguida na saída de monitoramento.")
        r = _row(g, r, "Saída para ouvir o teste", self._combo("audio.monitor_device", outs, 320), "Fones ou alto-falantes usados na reprodução do teste.")
        g.addWidget(separator(), r, 0, 1, 2)
        r += 1
        r = _row(g, r, "Gravar som do sistema", self._toggle("audio.sys_enabled"))
        r = _row(g, r, "Saída capturada", self._combo("audio.sys_device", outs, 320), "O áudio que toca nesta saída entra na gravação.")
        r = _row(g, r, "Volume do som do sistema", self._slider("audio.sys_volume", 0, 200, "%"))
        self.meter_src.level.connect(self.meter.set_level)
        self.mic_test.level.connect(self.meter.set_level)
        self.mic_test.state.connect(self._mic_state)
        self.s.changed.connect(lambda k: self._meter() if k in ("audio.mic_volume", "audio.mic_device") else None)
        return page

    def _meter(self) -> None:
        if self.mic_test.mode != "idle" or not self.isVisible():
            return
        self.meter_src.start(audio.resolve_mic(self.s.get("audio.mic_device")), int(self.s.get("audio.mic_volume")) / 100.0)

    def _mic_test(self) -> None:
        if self.mic_test.mode != "idle":
            self.mic_test.cancel()
            return
        self.meter_src.stop()
        self.mic_test.run(
            audio.resolve_mic(self.s.get("audio.mic_device")), int(self.s.get("audio.mic_volume")) / 100.0,
            self.s.get("audio.monitor_device"),
        )

    def _mic_state(self, state: str) -> None:
        self.test_state.setText({"recording": "Gravando… fale agora", "playing": "Reproduzindo…"}.get(state, ""))
        self.test_btn.setText("Cancelar teste" if state != "idle" else "Testar microfone")
        if state == "idle":
            self._meter()

    def _webcam(self) -> QWidget:
        from .webcam import SHAPES, cameras

        page, g = _page()
        r = 0
        r = _row(g, r, "Mostrar webcam", self._toggle("webcam.enabled"), "Aparece na tela assim que é ligada, para você posicionar antes de gravar.")
        cams = cameras()
        items = [("Padrão do sistema", "")] + [(c, c) for c in cams]
        r = _row(g, r, "Câmera", self._combo("webcam.device", items, 320), "" if cams else "Nenhuma webcam detectada.")
        r = _row(g, r, "Formato", self._combo("webcam.shape", [(text, key) for key, text in SHAPES]))
        r = _row(g, r, "Tamanho", self._slider("webcam.size", 120, 640, " px"))
        r = _row(g, r, "Espessura da moldura", self._slider("webcam.border", 0, 16, " px"), "0 remove a moldura.")
        col = QHBoxLayout()
        col.addStretch(1)
        col.addWidget(self._color("webcam.border_color"))
        r = _row(g, r, "Cor da moldura", col)
        r = _row(g, r, "Espelhar imagem", self._toggle("webcam.mirror"))
        tip = label(
            "A webcam fica fixa onde você a deixar e é gravada junto com a tela. Arraste para mover, role o mouse "
            "sobre ela para redimensionar e dê duplo clique para alternar o formato.", "small", wrap=True,
        )
        g.addWidget(tip, r, 0, 1, 2)
        return page

    def _effects(self) -> QWidget:
        page, g = _page()
        r = 0
        r = _row(g, r, "Efeito de clique", self._toggle("effects.click"), "Anel animado a cada clique do mouse.")
        colors = QHBoxLayout()
        colors.addStretch(1)
        colors.addWidget(label("Esquerdo", "small"))
        colors.addWidget(self._color("effects.click_color"))
        colors.addSpacing(10)
        colors.addWidget(label("Direito", "small"))
        colors.addWidget(self._color("effects.click_right_color"))
        r = _row(g, r, "Cores do clique", colors)
        r = _row(g, r, "Tamanho do clique", self._slider("effects.click_size", 16, 80, " px"))
        g.addWidget(separator(), r, 0, 1, 2)
        r += 1
        r = _row(g, r, "Destaque do cursor", self._toggle("effects.highlight"), "Círculo colorido que acompanha o ponteiro.")
        col = QHBoxLayout()
        col.addStretch(1)
        col.addWidget(self._color("effects.highlight_color"))
        r = _row(g, r, "Cor do destaque", col)
        r = _row(g, r, "Tamanho do destaque", self._slider("effects.highlight_size", 14, 90, " px"))
        r = _row(g, r, "Opacidade do destaque", self._slider("effects.highlight_opacity", 10, 90, "%"))
        g.addWidget(separator(), r, 0, 1, 2)
        r += 1
        r = _row(g, r, "Holofote", self._toggle("effects.spotlight"), "Escurece a tela e mantém iluminada a área ao redor do ponteiro.")
        r = _row(g, r, "Raio do holofote", self._slider("effects.spotlight_size", 80, 420, " px"))
        r = _row(g, r, "Escurecimento", self._slider("effects.spotlight_dim", 20, 90, "%"))
        g.addWidget(separator(), r, 0, 1, 2)
        r += 1
        r = _row(g, r, "Lupa", self._toggle("effects.magnifier"), "Lente centralizada no ponteiro, ampliando o que está sob ele.")
        r = _row(g, r, "Tamanho da lupa", self._slider("effects.magnifier_size", 100, 360, " px"))
        r = _row(g, r, "Ampliação", self._slider("effects.magnifier_zoom", 15, 40, "×", scale=10.0))
        g.addWidget(separator(), r, 0, 1, 2)
        r += 1
        r = _row(
            g, r, "Zoom acompanhando o mouse", self._toggle("effects.zoom"),
            "Aproxima o vídeo inteiro e desliza suavemente (pan) para manter em foco o que está perto do ponteiro. "
            "O zoom aparece no vídeo gravado; a sua tela continua normal.",
        )
        r = _row(g, r, "Nível do zoom", self._slider("effects.zoom_level", 12, 40, "×", scale=10.0))
        r = _row(
            g, r, "Moldura do zoom na tela", self._toggle("effects.zoom_frame"),
            "Contorno sobre a tela mostrando a área que o vídeo está enquadrando. Não entra no vídeo.",
        )
        r = _row(
            g, r, "Miniatura ao vivo do zoom", self._toggle("effects.zoom_preview"),
            "Janelinha com o vídeo já ampliado, como está sendo gravado. Arraste para mover; não entra no vídeo.",
        )
        r = _row(g, r, "Tamanho da miniatura", self._slider("effects.zoom_preview_size", 200, 560, " px"))
        g.addWidget(separator(), r, 0, 1, 2)
        r += 1
        r = _row(
            g, r, "Mostrar combinações de teclas", self._toggle("effects.keys"),
            "Exibe na tela, em caixas animadas, atalhos como Ctrl + C ou F5. Digitação comum (inclusive senhas) "
            "nunca é exibida. Requer que o usuário pertença ao grupo “input”.",
        )
        r = _row(g, r, "Estilo das teclas", self._combo("effects.keys_style", [("Teclas em relevo (claro)", "keycap"), ("Faixa escura", "dark")]))
        r = _row(g, r, "Efeito de entrada", self._combo("effects.keys_anim", [("Saltar (pop)", "pop"), ("Deslizar", "slide"), ("Esmaecer", "fade")]))
        r = _row(
            g, r, "Duração após soltar", self._slider("effects.keys_duration", 0, 50, " s", scale=10.0),
            "As teclas aparecem em tempo real enquanto pressionadas, permanecem por esse tempo e somem suavemente.",
        )
        r = _row(g, r, "Tamanho das teclas", self._slider("effects.keys_size", 16, 64, " px"))
        g.addWidget(separator(), r, 0, 1, 2)
        r += 1
        r = _row(g, r, "Tamanho do texto", self._slider("tools.text_size", 14, 72, " px"))
        r = _row(g, r, "Intensidade do desfoque", self._slider("tools.blur_strength", 6, 30, ""))
        return page

    def _shortcuts(self) -> QWidget:
        page, g = _page()
        g.setVerticalSpacing(9)
        r = 0
        kind = getattr(self.hotkeys, "backend", "none")
        note = {
            "kde": "Os atalhos são globais: funcionam com qualquer janela em foco. Os de ferramentas e efeitos ficam ativos apenas durante a gravação.",
            "portal": "Os atalhos são registrados no sistema; o ambiente pode pedir confirmação na primeira vez.",
        }.get(kind, "Neste ambiente os atalhos funcionam quando uma janela do aplicativo está em foco.")
        g.addWidget(label(note, "small", wrap=True), r, 0, 1, 3)
        r += 1
        self.editors: dict[str, QKeySequenceEdit] = {}
        group = None
        for action, (text, grp, _default) in SHORTCUT_ACTIONS.items():
            if grp != group:
                group = grp
                head = label(grp.upper(), "eyebrow")
                head.setContentsMargins(0, 10, 0, 0)
                g.addWidget(head, r, 0, 1, 3)
                r += 1
            g.addWidget(label(text), r, 0)
            ed = QKeySequenceEdit(QKeySequence(self.s.get(f"shortcuts.{action}") or ""))
            ed.setMaximumSequenceLength(1)
            ed.setClearButtonEnabled(True)
            ed.setFixedWidth(190)
            ed.editingFinished.connect(lambda a=action, e=ed: self._set_shortcut(a, e))
            self.editors[action] = ed
            g.addWidget(ed, r, 1)
            r += 1
        self.sc_msg = label("", "small", wrap=True)
        g.addWidget(self.sc_msg, r, 0, 1, 2)
        r += 1
        reset = button("Restaurar atalhos padrão", "undo")
        reset.clicked.connect(self._reset_shortcuts)
        g.addWidget(reset, r, 0, Qt.AlignLeft)
        return page

    def _set_shortcut(self, action: str, ed: QKeySequenceEdit) -> None:
        seq = ed.keySequence().toString()
        if seq:
            for other, cur in self.s.get("shortcuts").items():
                if other != action and cur == seq:
                    self.sc_msg.setStyleSheet(f"color: {theme.WARN};")
                    self.sc_msg.setText(f"“{seq}” já era usado em “{SHORTCUT_ACTIONS[other][0]}”, que ficou sem atalho.")
                    self.s.set(f"shortcuts.{other}", "", save=False)
                    self.editors[other].setKeySequence(QKeySequence())
                    break
            else:
                self.sc_msg.setText("")
        self.s.set(f"shortcuts.{action}", seq)
        self.s.changed.emit("shortcuts")

    def _reset_shortcuts(self) -> None:
        self.s.reset_shortcuts()
        for action, seq in default_shortcuts().items():
            self.editors[action].setKeySequence(QKeySequence(seq))
        self.sc_msg.setStyleSheet(f"color: {theme.OK};")
        self.sc_msg.setText("Atalhos padrão restaurados.")

    def _about(self) -> QWidget:
        from .. import DEVELOPER, DEVELOPER_URL
        from .widgets import open_url

        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(4, 22, 12, 8)
        lay.setSpacing(8)
        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(64))
        lay.addWidget(logo)
        name = label(APP_NAME, "title")
        lay.addWidget(name)
        lay.addWidget(label(f"Versão {__version__}", "muted"))
        lay.addSpacing(6)
        lay.addWidget(label(
            "Gravador de tela para Linux com anotações e efeitos do mouse em tempo real, "
            "captura acelerada por GPU e envio direto ao editor de vídeo.", wrap=True,
        ))
        lay.addSpacing(10)
        row = QHBoxLayout()
        row.addWidget(label(f"Desenvolvido por {DEVELOPER} ·"))
        site = button("gestaoculturalpro.com.br", "external", "link", size=14)
        site.setLayoutDirection(Qt.RightToLeft)
        site.clicked.connect(lambda: open_url(DEVELOPER_URL))
        row.addWidget(site)
        row.addStretch(1)
        lay.addLayout(row)
        support = button("Apoie o projeto", "heart", "primary")
        support.clicked.connect(self.donate.emit)
        lay.addSpacing(6)
        lay.addWidget(support, 0, Qt.AlignLeft)
        lay.addSpacing(14)
        lay.addWidget(label("Tecnologias: Qt 6 · GStreamer · PipeWire · FFmpeg · Kdenlive (editor).", "small", wrap=True))
        return page

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        self._meter()

    def done(self, code: int) -> None:
        if self.updater is not None:
            try:
                self.updater.checked.disconnect(self._update_checked)
            except (RuntimeError, TypeError):
                pass
        self.mic_test.cancel()
        self.meter_src.stop()
        super().done(code)
