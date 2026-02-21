from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from PySide6 import QtCore, QtGui, QtWidgets

from arkbreeder.storage.models import Creature
from arkbreeder.storage.repository import list_creatures
from arkbreeder.ui.toast import ToastNotification

logger = logging.getLogger(__name__)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, conn, export_dir: Path) -> None:
        super().__init__()
        self.setWindowTitle("ARK Breeder")
        self._conn = conn
        self._export_dir = export_dir
        self._import_service = None
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
        self.refresh_data()

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
        self._stack.addWidget(self._build_creatures_page())
        self._stack.addWidget(self._build_placeholder_page("Breeding recommendations"))
        self._stack.addWidget(self._build_placeholder_page("Family trees and lineage"))
        self._stack.addWidget(self._build_placeholder_page("Mutation tracking"))
        self._stack.addWidget(self._build_placeholder_page("App settings"))

        content = QtWidgets.QWidget()
        content.setObjectName("contentArea")
        content_layout = QtWidgets.QVBoxLayout(content)
        content_layout.setContentsMargins(24, 24, 24, 24)
        content_layout.setSpacing(16)

        header = QtWidgets.QHBoxLayout()
        self._page_title = QtWidgets.QLabel(self._page_titles[0])
        self._page_title.setStyleSheet("font-size: 22px; font-weight: 600; color: #f8fafc;")
        header.addWidget(self._page_title)
        header.addStretch(1)

        content_layout.addLayout(header)
        content_layout.addWidget(self._stack)

        root.addWidget(self._nav)
        root.addWidget(content)
        self.setCentralWidget(central)

        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.currentRowChanged.connect(self._update_page_title)
        self._nav.setCurrentRow(0)

        central.setStyleSheet(
            """
            #contentArea {
                background: #0b1220;
                color: #e5e7eb;
            }
            #contentArea QLabel {
                color: #e5e7eb;
            }
            #contentArea QPushButton {
                background: #1e293b;
                color: #e5e7eb;
                border: 1px solid #334155;
                padding: 6px 10px;
                border-radius: 6px;
            }
            #contentArea QPushButton:hover {
                background: #243247;
            }
            #contentArea QPushButton:pressed {
                background: #1b2536;
            }
            #contentArea QTableWidget {
                background: #0f172a;
                gridline-color: #1f2937;
                color: #e5e7eb;
                border: 1px solid #1f2937;
            }
            #contentArea QHeaderView::section {
                background: #111827;
                color: #e5e7eb;
                padding: 6px;
                border: 0px;
            }
            """
        )

    def _build_dashboard_page(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setSpacing(16)

        hero = QtWidgets.QFrame()
        hero.setStyleSheet('''
        QFrame { background: #0f172a; border: 1px solid #1f2937; border-radius: 12px; }
        ''')
        hero_layout = QtWidgets.QVBoxLayout(hero)
        hero_title = QtWidgets.QLabel("Welcome to ARK Breeder")
        hero_title.setStyleSheet("font-size: 18px; font-weight: 600; color: #f8fafc;")
        hero_sub = QtWidgets.QLabel(
            "Start by importing creature export files. The app will parse stats, mutations, and lineage."
        )
        hero_sub.setWordWrap(True)
        hero_sub.setStyleSheet("color: #cbd5f5;")
        self._export_dir_label = QtWidgets.QLabel(str(self._export_dir))
        self._export_dir_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self._last_import_label = QtWidgets.QLabel("Last import: --")
        self._last_import_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        hero_layout.addWidget(hero_title)
        hero_layout.addWidget(hero_sub)
        hero_layout.addWidget(self._export_dir_label)
        hero_layout.addWidget(self._last_import_label)

        actions = QtWidgets.QHBoxLayout()
        open_btn = QtWidgets.QPushButton("Open export folder")
        open_btn.clicked.connect(self._open_export_folder)
        actions.addWidget(open_btn)
        actions.addStretch(1)
        hero_layout.addLayout(actions)

        cards = QtWidgets.QHBoxLayout()
        self._creatures_count = QtWidgets.QLabel("0")
        self._species_count = QtWidgets.QLabel("0")
        self._mutations_count = QtWidgets.QLabel("0")
        cards.addWidget(self._build_card("Creatures", self._creatures_count, "Imported creatures"))
        cards.addWidget(self._build_card("Species", self._species_count, "Tracked species"))
        cards.addWidget(self._build_card("Mutations", self._mutations_count, "Recorded mutations"))

        layout.addWidget(hero)
        layout.addLayout(cards)
        layout.addStretch(1)
        return widget

    def _build_card(
        self,
        title: str,
        value_label: QtWidgets.QLabel,
        caption: str,
    ) -> QtWidgets.QWidget:
        card = QtWidgets.QFrame()
        card.setStyleSheet('''
        QFrame { background: #111827; border: 1px solid #1f2937; border-radius: 12px; }
        ''')
        layout = QtWidgets.QVBoxLayout(card)
        title_label = QtWidgets.QLabel(title)
        title_label.setStyleSheet("color: #94a3b8; font-size: 12px; text-transform: uppercase;")
        value_label.setStyleSheet("font-size: 26px; font-weight: 700;")
        caption_label = QtWidgets.QLabel(caption)
        caption_label.setStyleSheet("color: #94a3b8;")
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addWidget(caption_label)
        return card

    def _build_creatures_page(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setSpacing(12)

        toolbar = QtWidgets.QHBoxLayout()
        self._refresh_button = QtWidgets.QPushButton("Refresh list")
        self._refresh_button.clicked.connect(self.refresh_data)
        toolbar.addWidget(self._refresh_button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self._creatures_table = QtWidgets.QTableWidget(0, 9)
        self._creatures_table.setHorizontalHeaderLabels(
            [
                "Name",
                "Species",
                "Sex",
                "Level",
                "Mutations (M/F)",
                "Health",
                "Stamina",
                "Weight",
                "Melee",
            ]
        )
        self._creatures_table.horizontalHeader().setStretchLastSection(True)
        self._creatures_table.setAlternatingRowColors(True)
        self._creatures_table.setStyleSheet(
            """
            QTableWidget::item:selected { background: #1f2937; }
            QTableWidget::item:alternate { background: #0b1324; }
            """
        )
        self._creatures_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._creatures_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._creatures_table.verticalHeader().setVisible(False)

        layout.addWidget(self._creatures_table)
        layout.addStretch(1)
        return widget

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

    def _trigger_import(self) -> None:
        if self._import_service is None:
            self.show_toast("Import service not ready yet.", "error")
            return
        result = self._import_service.poll_once()
        if result.imported or result.failed:
            self._update_last_import_label()
            self.refresh_data()
        if result.imported == 0 and result.failed == 0:
            self.show_toast("No export files found.", "info")

    def _open_export_folder(self) -> None:
        if not self._export_dir.exists():
            self.show_toast("Export folder does not exist yet.", "error")
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self._export_dir)))

    def handle_import_tick(self) -> None:
        if self._import_service is None:
            return
        result = self._import_service.poll_once()
        if result.imported or result.failed:
            self._update_last_import_label()
            self.refresh_data()

    def refresh_data(self) -> None:
        creatures = list_creatures(self._conn)
        self._update_dashboard(creatures)
        self._populate_creatures_table(creatures)

    def _update_dashboard(self, creatures: Iterable[Creature]) -> None:
        creature_list = list(creatures)
        self._creatures_count.setText(str(len(creature_list)))
        species = {creature.species for creature in creature_list if creature.species}
        self._species_count.setText(str(len(species)))
        mutations_total = sum(
            creature.mutations_maternal + creature.mutations_paternal for creature in creature_list
        )
        self._mutations_count.setText(str(mutations_total))

    def _populate_creatures_table(self, creatures: Iterable[Creature]) -> None:
        creature_list = list(creatures)
        self._creatures_table.setRowCount(len(creature_list))
        for row, creature in enumerate(creature_list):
            self._set_table_item(row, 0, creature.name)
            self._set_table_item(row, 1, creature.species)
            self._set_table_item(row, 2, creature.sex)
            self._set_table_item(row, 3, str(creature.level))
            self._set_table_item(
                row,
                4,
                f"{creature.mutations_maternal}/{creature.mutations_paternal}",
            )
            self._set_table_item(row, 5, self._format_stat(creature.stats.get("Health")))
            self._set_table_item(row, 6, self._format_stat(creature.stats.get("Stamina")))
            self._set_table_item(row, 7, self._format_stat(creature.stats.get("Weight")))
            self._set_table_item(row, 8, self._format_stat(creature.stats.get("MeleeDamageMultiplier")))
        self._creatures_table.resizeColumnsToContents()

    def _set_table_item(self, row: int, col: int, value: str) -> None:
        item = QtWidgets.QTableWidgetItem(value)
        item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
        self._creatures_table.setItem(row, col, item)

    def _format_stat(self, value: float | None) -> str:
        if value is None:
            return "-"
        return f"{value:.2f}"

    def _update_last_import_label(self) -> None:
        stamp = QtCore.QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        self._last_import_label.setText(f"Last import: {stamp}")

    def show_toast(self, message: str, kind: str = "info") -> None:
        toast = ToastNotification(self, message=message, kind=kind, duration_ms=5000)
        self._toasts.append(toast)

        def _cleanup(_=None) -> None:
            if toast in self._toasts:
                self._toasts.remove(toast)

        toast.destroyed.connect(_cleanup)
        toast.show_at_bottom_right()
