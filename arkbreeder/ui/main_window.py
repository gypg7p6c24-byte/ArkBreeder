from __future__ import annotations

import logging

from PySide6 import QtCore, QtWidgets

from arkbreeder.ui.toast import ToastNotification

logger = logging.getLogger(__name__)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ARK Breeder")
        self._toasts: list[ToastNotification] = []
        self._page_titles = [
            "Dashboard",
            "Creatures",
            "Breeding",
            "Pedigree",
            "Mutations",
            "Settings",
        ]
        self._build_ui()

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)

        self._nav = QtWidgets.QListWidget()
        self._nav.addItems(self._page_titles)
        self._nav.setFixedWidth(180)
        self._nav.setSpacing(6)
        self._nav.setStyleSheet('''
        QListWidget { background: #111827; color: #e5e7eb; border: none; }
        QListWidget::item { padding: 10px 12px; border-radius: 8px; }
        QListWidget::item:selected { background: #1f2937; color: #ffffff; }
        ''')

        self._stack = QtWidgets.QStackedWidget()
        self._stack.addWidget(self._build_dashboard_page())
        self._stack.addWidget(self._build_placeholder_page("Creature registry and search"))
        self._stack.addWidget(self._build_placeholder_page("Breeding recommendations"))
        self._stack.addWidget(self._build_placeholder_page("Family trees and lineage"))
        self._stack.addWidget(self._build_placeholder_page("Mutation tracking"))
        self._stack.addWidget(self._build_placeholder_page("App settings"))

        content = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(content)
        content_layout.setContentsMargins(24, 24, 24, 24)
        content_layout.setSpacing(16)

        header = QtWidgets.QHBoxLayout()
        self._page_title = QtWidgets.QLabel(self._page_titles[0])
        self._page_title.setStyleSheet("font-size: 22px; font-weight: 600;")
        header.addWidget(self._page_title)
        header.addStretch(1)

        self._import_button = QtWidgets.QPushButton("Import creature exports")
        self._import_button.clicked.connect(self._show_not_implemented)
        header.addWidget(self._import_button)

        content_layout.addLayout(header)
        content_layout.addWidget(self._stack)

        root.addWidget(self._nav)
        root.addWidget(content)
        self.setCentralWidget(central)

        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.currentRowChanged.connect(self._update_page_title)
        self._nav.setCurrentRow(0)

    def _build_dashboard_page(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setSpacing(16)

        hero = QtWidgets.QFrame()
        hero.setStyleSheet('''
        QFrame { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; }
        ''')
        hero_layout = QtWidgets.QVBoxLayout(hero)
        hero_title = QtWidgets.QLabel("Welcome to ARK Breeder")
        hero_title.setStyleSheet("font-size: 18px; font-weight: 600;")
        hero_sub = QtWidgets.QLabel(
            "Start by importing creature export files. The app will parse stats, mutations, and lineage."
        )
        hero_sub.setWordWrap(True)
        hero_layout.addWidget(hero_title)
        hero_layout.addWidget(hero_sub)

        actions = QtWidgets.QHBoxLayout()
        import_btn = QtWidgets.QPushButton("Import files")
        import_btn.clicked.connect(self._show_not_implemented)
        open_btn = QtWidgets.QPushButton("Open export folder")
        open_btn.clicked.connect(self._show_not_implemented)
        actions.addWidget(import_btn)
        actions.addWidget(open_btn)
        actions.addStretch(1)
        hero_layout.addLayout(actions)

        cards = QtWidgets.QHBoxLayout()
        cards.addWidget(self._build_card("Creatures", "0", "Imported creatures"))
        cards.addWidget(self._build_card("Species", "0", "Tracked species"))
        cards.addWidget(self._build_card("Mutations", "0", "Recorded mutations"))

        layout.addWidget(hero)
        layout.addLayout(cards)
        layout.addStretch(1)
        return widget

    def _build_card(self, title: str, value: str, caption: str) -> QtWidgets.QWidget:
        card = QtWidgets.QFrame()
        card.setStyleSheet('''
        QFrame { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; }
        ''')
        layout = QtWidgets.QVBoxLayout(card)
        title_label = QtWidgets.QLabel(title)
        title_label.setStyleSheet("color: #64748b; font-size: 12px; text-transform: uppercase;")
        value_label = QtWidgets.QLabel(value)
        value_label.setStyleSheet("font-size: 26px; font-weight: 700;")
        caption_label = QtWidgets.QLabel(caption)
        caption_label.setStyleSheet("color: #64748b;")
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addWidget(caption_label)
        return card

    def _build_placeholder_page(self, subtitle: str) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setSpacing(12)

        label = QtWidgets.QLabel(subtitle)
        label.setStyleSheet("font-size: 16px; font-weight: 500;")
        hint = QtWidgets.QLabel("This area will be implemented in the next iterations.")
        hint.setStyleSheet("color: #6b7280;")
        hint.setWordWrap(True)

        layout.addWidget(label)
        layout.addWidget(hint)
        layout.addStretch(1)
        return widget

    def _update_page_title(self, index: int) -> None:
        if 0 <= index < len(self._page_titles):
            self._page_title.setText(self._page_titles[index])

    def _show_not_implemented(self) -> None:
        logger.info("Placeholder action triggered")
        QtWidgets.QMessageBox.information(
            self,
            "Not implemented",
            "This action is a placeholder and will be wired later.",
        )

    def show_toast(self, message: str, kind: str = "info") -> None:
        toast = ToastNotification(self, message=message, kind=kind, duration_ms=5000)
        self._toasts.append(toast)

        def _cleanup(_=None) -> None:
            if toast in self._toasts:
                self._toasts.remove(toast)

        toast.destroyed.connect(_cleanup)
        toast.show_at_bottom_right()
