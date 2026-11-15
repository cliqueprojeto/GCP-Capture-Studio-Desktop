"""Janela "Apoie o projeto": PIX (QR Code + copia e cola) e Stripe."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout

from .. import APP_NAME, DEVELOPER, DEVELOPER_SITE_LABEL, DEVELOPER_URL, PIX_CODE, STRIPE_URL, theme
from .widgets import button, label, open_url


class DonateDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Apoie o projeto")
        self.setModal(True)
        self.setFixedWidth(840)
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 26, 30, 28)
        root.setSpacing(0)

        head = QHBoxLayout()
        title = label("Apoie o projeto", "title")
        head.addWidget(title)
        head.addStretch(1)
        close = button("", "x", "ghost", theme.MUTED, 20)
        close.setToolTip("Fechar")
        close.clicked.connect(self.accept)
        head.addWidget(close)
        root.addLayout(head)
        root.addSpacing(4)
        root.addWidget(label(f"Sua contribuição ajuda a manter o {APP_NAME} aberto e em evolução.", "muted"))
        root.addSpacing(20)

        dev = QHBoxLayout()
        dev.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(52))
        dev.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(2)
        name = label(f"Desenvolvido por {DEVELOPER}")
        name.setStyleSheet("font-size: 14px; font-weight: 600;")
        col.addWidget(name)
        site = button(DEVELOPER_SITE_LABEL, "external", "link", size=14)
        site.setLayoutDirection(Qt.RightToLeft)
        site.setToolTip(DEVELOPER_URL)
        site.clicked.connect(lambda: open_url(DEVELOPER_URL))
        row = QHBoxLayout()
        row.addWidget(site)
        row.addStretch(1)
        col.addLayout(row)
        dev.addLayout(col, 1)
        root.addLayout(dev)
        root.addSpacing(20)

        cards = QHBoxLayout()
        cards.setSpacing(18)
        cards.addWidget(self._pix_card(), 1)
        cards.addWidget(self._stripe_card(), 1)
        root.addLayout(cards)

    def _card(self) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setProperty("role", "card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(10)
        return card, lay

    def _pix_card(self) -> QFrame:
        card, lay = self._card()
        lay.addWidget(label("PIX · BRASIL", "eyebrow"))
        lay.addSpacing(4)
        qr = QLabel()
        pm = QPixmap(str(theme.ASSETS / "pix-qrcode.png")).scaled(600, 600, Qt.KeepAspectRatio, Qt.FastTransformation)
        pm.setDevicePixelRatio(2)
        qr.setPixmap(pm)
        qr.setFixedSize(300, 300)
        qr.setStyleSheet("background: white; border-radius: 6px;")
        qr.setAlignment(Qt.AlignCenter)
        lay.addWidget(qr, 0, Qt.AlignLeft)
        lay.addWidget(label("Escaneie com o aplicativo do seu banco.", "small"))
        self.copy_pix = button("Copiar PIX", "copy", "primary")
        self.copy_pix.setMinimumHeight(42)
        self.copy_pix.clicked.connect(lambda: self._copy(PIX_CODE, self.copy_pix, "Copiar PIX"))
        lay.addWidget(self.copy_pix)
        self.show_code = button("▸ Ver código PIX", role="link")
        self.show_code.setStyleSheet(f"color: {theme.MUTED}; font-size: 11.5px; font-weight: 500;")
        self.code = QPlainTextEdit(PIX_CODE)
        self.code.setReadOnly(True)
        self.code.setFixedHeight(64)
        self.code.hide()
        self.show_code.clicked.connect(self._toggle_code)
        lay.addWidget(self.show_code)
        lay.addWidget(self.code)
        lay.addStretch(1)
        return card

    def _stripe_card(self) -> QFrame:
        card, lay = self._card()
        lay.addWidget(label("STRIPE · INTERNACIONAL", "eyebrow"))
        lay.addSpacing(14)
        heart = QLabel()
        heart.setPixmap(theme.pixmap("heart", theme.ACCENT, 38))
        heart.setFixedSize(84, 84)
        heart.setAlignment(Qt.AlignCenter)
        heart.setStyleSheet(f"background: {theme.CARD_HI}; border-radius: 22px;")
        lay.addWidget(heart)
        lay.addSpacing(14)
        h = label("Faça parte dessa construção")
        h.setStyleSheet("font-size: 19px; font-weight: 600;")
        lay.addWidget(h)
        lay.addWidget(label("Contribua com qualquer valor pelo checkout seguro do Stripe.", "small", wrap=True))
        lay.addSpacing(8)
        go = button("Contribuir via Stripe", "external")
        go.setLayoutDirection(Qt.RightToLeft)
        go.setMinimumHeight(44)
        go.setStyleSheet("font-size: 14px;")
        go.clicked.connect(lambda: open_url(STRIPE_URL))
        lay.addWidget(go)
        self.copy_stripe = button("Copiar link do Stripe", "copy", "link", size=16)
        self.copy_stripe.clicked.connect(lambda: self._copy(STRIPE_URL, self.copy_stripe, "Copiar link do Stripe"))
        lay.addWidget(self.copy_stripe)
        lay.addStretch(1)
        lay.addWidget(label("O apoio é voluntário. As funções do aplicativo estão disponíveis sem contribuição.", "small", wrap=True))
        return card

    def _toggle_code(self) -> None:
        show = not self.code.isVisible()
        self.code.setVisible(show)
        self.show_code.setText(("▾" if show else "▸") + " Ver código PIX")
        self.adjustSize()

    def _copy(self, text: str, btn, original: str) -> None:
        QGuiApplication.clipboard().setText(text)
        btn.setText("Copiado!")
        QTimer.singleShot(1600, lambda: btn.setText(original))
