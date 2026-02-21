from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from PySide6 import QtCore, QtGui, QtWidgets

from arkbreeder.core.server_settings import parse_ini_file
from arkbreeder.storage.models import Creature
from arkbreeder.storage.repository import list_creatures
from arkbreeder.storage.settings import get_server_settings, set_server_settings
from arkbreeder.ui.radar_chart import RadarChart
from arkbreeder.ui.species_image import SpeciesImageWidget
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
        self._server_settings: dict | None = None
        self._creature_cache: list[Creature] = []
        self._creature_rows: list[Creature] = []
        self._selected_creature: Creature | None = None
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
        self._load_server_settings()

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
        self._stack.addWidget(self._build_breeding_page())
        self._stack.addWidget(self._build_pedigree_page())
        self._stack.addWidget(self._build_mutations_page())
        self._stack.addWidget(self._build_settings_page())

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
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setSpacing(12)

        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setSpacing(12)

        toolbar = QtWidgets.QHBoxLayout()
        self._creature_search = QtWidgets.QLineEdit()
        self._creature_search.setPlaceholderText("Search name or species")
        self._creature_search.textChanged.connect(self._apply_creature_filters)
        toolbar.addWidget(self._creature_search)

        self._creature_species_filter = QtWidgets.QComboBox()
        self._creature_species_filter.currentIndexChanged.connect(self._apply_creature_filters)
        toolbar.addWidget(self._creature_species_filter)

        self._creature_updated_filter = QtWidgets.QComboBox()
        self._creature_updated_filter.addItems(
            ["All updates", "Updated today", "Last 7 days", "Last 30 days"]
        )
        self._creature_updated_filter.currentIndexChanged.connect(self._apply_creature_filters)
        toolbar.addWidget(self._creature_updated_filter)

        self._refresh_button = QtWidgets.QPushButton("Refresh list")
        self._refresh_button.clicked.connect(self.refresh_data)
        toolbar.addWidget(self._refresh_button)
        toolbar.addStretch(1)
        left_layout.addLayout(toolbar)

        self._creatures_table = QtWidgets.QTableWidget(0, 10)
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
                "Updated",
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
        self._creatures_table.setSortingEnabled(True)
        self._creatures_table.itemSelectionChanged.connect(self._on_creature_selected)

        left_layout.addWidget(self._creatures_table)
        left_layout.addStretch(1)

        right = self._build_creature_detail_panel()

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter)
        return widget

    def _build_breeding_page(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setSpacing(12)

        toolbar = QtWidgets.QHBoxLayout()
        self._breeding_species_filter = QtWidgets.QComboBox()
        self._breeding_species_filter.currentIndexChanged.connect(self._update_breeding_pairs)
        toolbar.addWidget(self._breeding_species_filter)

        self._breeding_stat_focus = QtWidgets.QComboBox()
        self._breeding_stat_focus.addItems(
            ["Overall", "Health", "Stamina", "Weight", "Melee"]
        )
        self._breeding_stat_focus.currentIndexChanged.connect(self._update_breeding_pairs)
        toolbar.addWidget(self._breeding_stat_focus)

        self._breeding_refresh_btn = QtWidgets.QPushButton("Suggest pairs")
        self._breeding_refresh_btn.clicked.connect(self._update_breeding_pairs)
        toolbar.addWidget(self._breeding_refresh_btn)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self._breeding_table = QtWidgets.QTableWidget(0, 6)
        self._breeding_table.setHorizontalHeaderLabels(
            ["Male", "Female", "Focus", "Male stat", "Female stat", "Score"]
        )
        self._breeding_table.horizontalHeader().setStretchLastSection(True)
        self._breeding_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._breeding_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._breeding_table.verticalHeader().setVisible(False)
        layout.addWidget(self._breeding_table)
        layout.addStretch(1)
        return widget

    def _build_creature_detail_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QFrame()
        panel.setStyleSheet(
            """
            QFrame {
                background: #0f172a;
                border: 1px solid #1f2937;
                border-radius: 12px;
            }
            """
        )
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setSpacing(12)

        self._detail_title = QtWidgets.QLabel("Select a creature")
        self._detail_title.setStyleSheet("font-size: 16px; font-weight: 600; color: #f8fafc;")
        layout.addWidget(self._detail_title)

        self._detail_subtitle = QtWidgets.QLabel("")
        self._detail_subtitle.setStyleSheet("color: #94a3b8;")
        self._detail_subtitle.setWordWrap(True)
        layout.addWidget(self._detail_subtitle)

        self._detail_image = SpeciesImageWidget()
        layout.addWidget(self._detail_image, alignment=QtCore.Qt.AlignCenter)

        self._detail_radar = RadarChart(["Health", "Stamina", "Weight", "Melee"])
        layout.addWidget(self._detail_radar)

        self._detail_strengths = QtWidgets.QLabel("Strengths: -")
        self._detail_strengths.setStyleSheet("color: #a7f3d0;")
        self._detail_strengths.setWordWrap(True)
        layout.addWidget(self._detail_strengths)

        self._detail_weaknesses = QtWidgets.QLabel("Weaknesses: -")
        self._detail_weaknesses.setStyleSheet("color: #fecaca;")
        self._detail_weaknesses.setWordWrap(True)
        layout.addWidget(self._detail_weaknesses)

        layout.addStretch(1)
        return panel

    def _build_pedigree_page(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setSpacing(12)

        toolbar = QtWidgets.QHBoxLayout()
        self._pedigree_species_filter = QtWidgets.QComboBox()
        self._pedigree_species_filter.currentIndexChanged.connect(self._update_pedigree_table)
        toolbar.addWidget(self._pedigree_species_filter)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self._pedigree_table = QtWidgets.QTableWidget(0, 5)
        self._pedigree_table.setHorizontalHeaderLabels(
            ["Name", "Species", "Mother ID", "Father ID", "External ID"]
        )
        self._pedigree_table.horizontalHeader().setStretchLastSection(True)
        self._pedigree_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._pedigree_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._pedigree_table.verticalHeader().setVisible(False)
        layout.addWidget(self._pedigree_table)
        layout.addStretch(1)
        return widget

    def _build_mutations_page(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setSpacing(12)

        toolbar = QtWidgets.QHBoxLayout()
        self._mutations_species_filter = QtWidgets.QComboBox()
        self._mutations_species_filter.currentIndexChanged.connect(self._update_mutations_table)
        toolbar.addWidget(self._mutations_species_filter)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self._mutations_table = QtWidgets.QTableWidget(0, 6)
        self._mutations_table.setHorizontalHeaderLabels(
            ["Name", "Species", "Sex", "Maternal", "Paternal", "Total"]
        )
        self._mutations_table.horizontalHeader().setStretchLastSection(True)
        self._mutations_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._mutations_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._mutations_table.verticalHeader().setVisible(False)
        layout.addWidget(self._mutations_table)
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

    def _build_settings_page(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setSpacing(12)

        header = QtWidgets.QLabel("Server settings")
        header.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(header)

        helper = QtWidgets.QLabel(
            "Import GameUserSettings.ini or Game.ini to match your server multipliers."
        )
        helper.setWordWrap(True)
        helper.setStyleSheet("color: #cbd5f5;")
        layout.addWidget(helper)

        actions = QtWidgets.QHBoxLayout()
        self._import_user_settings_btn = QtWidgets.QPushButton("Import GameUserSettings.ini")
        self._import_user_settings_btn.clicked.connect(self._import_game_user_settings)
        actions.addWidget(self._import_user_settings_btn)

        self._import_game_ini_btn = QtWidgets.QPushButton("Import Game.ini")
        self._import_game_ini_btn.clicked.connect(self._import_game_ini)
        actions.addWidget(self._import_game_ini_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        self._settings_summary = QtWidgets.QLabel("Using official defaults (x1).")
        self._settings_summary.setWordWrap(True)
        self._settings_summary.setStyleSheet("color: #94a3b8;")
        layout.addWidget(self._settings_summary)

        self._settings_details = QtWidgets.QLabel("")
        self._settings_details.setWordWrap(True)
        self._settings_details.setStyleSheet("color: #94a3b8;")
        layout.addWidget(self._settings_details)

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
        self._creature_cache = list(list_creatures(self._conn))
        self._update_dashboard(self._creature_cache)
        self._update_species_filters()
        self._apply_creature_filters()
        self._update_breeding_pairs()
        self._update_mutations_table()
        self._update_pedigree_table()

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
        self._creature_rows = creature_list
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
            self._set_table_item(row, 9, self._format_updated_at(creature.updated_at))
        self._creatures_table.resizeColumnsToContents()
        self._restore_creature_selection()

    def _restore_creature_selection(self) -> None:
        if not self._creature_rows:
            return
        target_id = self._selected_creature.external_id if self._selected_creature else None
        if target_id:
            for row, creature in enumerate(self._creature_rows):
                if creature.external_id == target_id:
                    self._creatures_table.selectRow(row)
                    return
        self._creatures_table.selectRow(0)

    def _apply_creature_filters(self) -> None:
        text = self._creature_search.text().strip().lower()
        species_filter = self._creature_species_filter.currentText()
        update_filter = self._creature_updated_filter.currentText()
        cutoff = self._updated_cutoff(update_filter)
        filtered = []
        for creature in self._creature_cache:
            if species_filter and species_filter != "All species":
                if creature.species != species_filter:
                    continue
            if text:
                hay = f"{creature.name} {creature.species}".lower()
                if text not in hay:
                    continue
            if cutoff and creature.updated_at:
                try:
                    updated = QtCore.QDateTime.fromString(
                        creature.updated_at, "yyyy-MM-dd HH:mm:ss"
                    )
                except Exception:
                    updated = QtCore.QDateTime()
                if updated.isValid() and updated < cutoff:
                    continue
            filtered.append(creature)
        self._populate_creatures_table(filtered)

    def _update_species_filters(self) -> None:
        species_list = sorted({c.species for c in self._creature_cache if c.species})
        self._update_filter_combo(self._creature_species_filter, species_list)
        self._update_filter_combo(self._breeding_species_filter, species_list)
        self._update_filter_combo(self._mutations_species_filter, species_list)
        self._update_filter_combo(self._pedigree_species_filter, species_list)

    def _update_filter_combo(self, combo: QtWidgets.QComboBox, species: list[str]) -> None:
        current = combo.currentText() if combo.count() else "All species"
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("All species")
        combo.addItems(species)
        if current:
            index = combo.findText(current)
            if index >= 0:
                combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _update_breeding_pairs(self) -> None:
        species = self._breeding_species_filter.currentText()
        focus = self._breeding_stat_focus.currentText()
        creatures = [
            c
            for c in self._creature_cache
            if species == "All species" or c.species == species
        ]
        males = [c for c in creatures if c.sex.lower() == "male"]
        females = [c for c in creatures if c.sex.lower() == "female"]

        pairs: list[tuple[float, Creature, Creature, float, float]] = []
        for male in males:
            for female in females:
                score, male_stat, female_stat = self._score_pair(male, female, focus)
                pairs.append((score, male, female, male_stat, female_stat))

        pairs.sort(key=lambda item: item[0], reverse=True)
        top_pairs = pairs[:10]
        self._breeding_table.setRowCount(len(top_pairs))
        for row, (score, male, female, male_stat, female_stat) in enumerate(top_pairs):
            self._set_table_item(row, 0, male.name)
            self._set_table_item(row, 1, female.name)
            self._set_table_item(row, 2, focus)
            self._set_table_item(row, 3, self._format_score(male_stat))
            self._set_table_item(row, 4, self._format_score(female_stat))
            self._set_table_item(row, 5, self._format_score(score))
        self._breeding_table.resizeColumnsToContents()

    def _score_pair(self, male: Creature, female: Creature, focus: str) -> tuple[float, float, float]:
        if focus == "Overall":
            best_stats = [
                max(self._get_stat_value(male, key), self._get_stat_value(female, key))
                for key in ("Health", "Stamina", "Weight", "MeleeDamageMultiplier")
            ]
            score = sum(best_stats)
            return score, self._overall_score(male), self._overall_score(female)

        key = {
            "Health": "Health",
            "Stamina": "Stamina",
            "Weight": "Weight",
            "Melee": "MeleeDamageMultiplier",
        }.get(focus, "Health")
        male_stat = self._get_stat_value(male, key)
        female_stat = self._get_stat_value(female, key)
        score = max(male_stat, female_stat)
        return score, male_stat, female_stat

    def _overall_score(self, creature: Creature) -> float:
        return sum(
            self._get_stat_value(creature, key)
            for key in ("Health", "Stamina", "Weight", "MeleeDamageMultiplier")
        )

    def _get_stat_value(self, creature: Creature, key: str) -> float:
        value = creature.stats.get(key)
        if value is None:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _format_score(self, value: float) -> str:
        return f"{value:.2f}"

    def _update_mutations_table(self) -> None:
        species = self._mutations_species_filter.currentText()
        creatures = [
            c
            for c in self._creature_cache
            if species == "All species" or c.species == species
        ]
        self._mutations_table.setRowCount(len(creatures))
        for row, creature in enumerate(creatures):
            total = creature.mutations_maternal + creature.mutations_paternal
            self._set_table_item(row, 0, creature.name)
            self._set_table_item(row, 1, creature.species)
            self._set_table_item(row, 2, creature.sex)
            self._set_table_item(row, 3, str(creature.mutations_maternal))
            self._set_table_item(row, 4, str(creature.mutations_paternal))
            self._set_table_item(row, 5, str(total))
        self._mutations_table.resizeColumnsToContents()

    def _update_pedigree_table(self) -> None:
        species = self._pedigree_species_filter.currentText()
        creatures = [
            c
            for c in self._creature_cache
            if species == "All species" or c.species == species
        ]
        self._pedigree_table.setRowCount(len(creatures))
        for row, creature in enumerate(creatures):
            self._set_table_item(row, 0, creature.name)
            self._set_table_item(row, 1, creature.species)
            self._set_table_item(row, 2, str(creature.mother_id or "-"))
            self._set_table_item(row, 3, str(creature.father_id or "-"))
            self._set_table_item(row, 4, creature.external_id or "-")
        self._pedigree_table.resizeColumnsToContents()

    def _set_table_item(self, row: int, col: int, value: str) -> None:
        item = QtWidgets.QTableWidgetItem(value)
        item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
        self._creatures_table.setItem(row, col, item)

    def _format_stat(self, value: float | None) -> str:
        if value is None:
            return "-"
        return f"{value:.2f}"

    def _format_updated_at(self, value: str | None) -> str:
        if not value:
            return "-"
        dt = QtCore.QDateTime.fromString(value, "yyyy-MM-dd HH:mm:ss")
        if not dt.isValid():
            return value
        now = QtCore.QDateTime.currentDateTime()
        seconds = dt.secsTo(now)
        if seconds < 0:
            return value
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} min ago"
        if seconds < 86400:
            hours = seconds // 3600
            return f"{hours} h ago"
        days = seconds // 86400
        return f"{days} d ago"

    def _on_creature_selected(self) -> None:
        rows = self._creatures_table.selectionModel().selectedRows()
        if not rows:
            self._selected_creature = None
            self._detail_title.setText("Select a creature")
            self._detail_subtitle.setText("")
            self._detail_strengths.setText("Strengths: -")
            self._detail_weaknesses.setText("Weaknesses: -")
            return
        row = rows[0].row()
        if row < 0 or row >= len(self._creature_rows):
            return
        creature = self._creature_rows[row]
        self._selected_creature = creature
        self._update_creature_detail(creature)

    def _update_creature_detail(self, creature: Creature) -> None:
        self._detail_title.setText(creature.name or "Unknown")
        subtitle = f"{creature.species} • {creature.sex} • L{creature.level}"
        self._detail_subtitle.setText(subtitle)
        self._detail_image.set_species(creature.species)

        species_group = [c for c in self._creature_cache if c.species == creature.species]
        stats_keys = ["Health", "Stamina", "Weight", "MeleeDamageMultiplier"]
        max_values = {
            key: max((self._get_stat_value(c, key) for c in species_group), default=0.0)
            for key in stats_keys
        }
        values = {
            "Health": self._get_stat_value(creature, "Health"),
            "Stamina": self._get_stat_value(creature, "Stamina"),
            "Weight": self._get_stat_value(creature, "Weight"),
            "Melee": self._get_stat_value(creature, "MeleeDamageMultiplier"),
        }
        radar_max = {
            "Health": max_values.get("Health", 1.0),
            "Stamina": max_values.get("Stamina", 1.0),
            "Weight": max_values.get("Weight", 1.0),
            "Melee": max_values.get("MeleeDamageMultiplier", 1.0),
        }
        self._detail_radar.set_values(values, radar_max)

        strengths, weaknesses = self._compute_strengths_weaknesses(creature, species_group)
        self._detail_strengths.setText("Strengths: " + (", ".join(strengths) if strengths else "-"))
        self._detail_weaknesses.setText("Weaknesses: " + (", ".join(weaknesses) if weaknesses else "-"))

    def _compute_strengths_weaknesses(
        self,
        creature: Creature,
        species_group: list[Creature],
    ) -> tuple[list[str], list[str]]:
        strengths: list[str] = []
        weaknesses: list[str] = []
        stat_map = {
            "Health": "Health",
            "Stamina": "Stamina",
            "Weight": "Weight",
            "Melee": "MeleeDamageMultiplier",
        }
        for label, key in stat_map.items():
            values = [self._get_stat_value(c, key) for c in species_group]
            percentile = self._stat_percentile(self._get_stat_value(creature, key), values)
            if percentile >= 0.9:
                strengths.append(f"{label} (top 10%)")
            elif percentile <= 0.1:
                weaknesses.append(f"{label} (bottom 10%)")
        return strengths, weaknesses

    def _stat_percentile(self, value: float, values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        total = len(values)
        count = sum(1 for v in values if v <= value)
        return count / total

    def _updated_cutoff(self, filter_label: str) -> QtCore.QDateTime | None:
        now = QtCore.QDateTime.currentDateTime()
        if filter_label == "Updated today":
            return now.addDays(-1)
        if filter_label == "Last 7 days":
            return now.addDays(-7)
        if filter_label == "Last 30 days":
            return now.addDays(-30)
        return None

    def _update_last_import_label(self) -> None:
        stamp = QtCore.QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        self._last_import_label.setText(f"Last import: {stamp}")

    def _load_server_settings(self) -> None:
        self._server_settings = get_server_settings(self._conn)
        self._update_settings_view()

    def _update_settings_view(self) -> None:
        if not self._server_settings:
            self._settings_summary.setText("Using official defaults (x1).")
            self._settings_details.setText("")
            return

        sources = self._server_settings.get("sources", {})
        imported_at = self._server_settings.get("imported_at", "unknown time")
        summary_lines = [f"Imported at: {imported_at}"]
        detail_lines = []

        for label, key in (
            ("GameUserSettings.ini", "game_user_settings"),
            ("Game.ini", "game_ini"),
        ):
            data = self._server_settings.get(key)
            if not data:
                detail_lines.append(f"{label}: not provided")
                continue
            sections = len(data)
            keys = sum(len(values) for values in data.values())
            path = sources.get(key, "unknown path")
            detail_lines.append(f"{label}: {sections} sections, {keys} values")
            detail_lines.append(f"Source: {path}")

        self._settings_summary.setText("Server settings loaded.")
        self._settings_details.setText("\n".join(summary_lines + detail_lines))

    def _import_game_user_settings(self) -> None:
        path = self._select_ini_file("Select GameUserSettings.ini")
        if not path:
            return
        payload = self._ensure_server_settings_payload()
        payload["game_user_settings"] = parse_ini_file(Path(path))
        payload["sources"]["game_user_settings"] = path
        self._save_server_settings(payload, "GameUserSettings.ini imported.")

    def _import_game_ini(self) -> None:
        path = self._select_ini_file("Select Game.ini")
        if not path:
            return
        payload = self._ensure_server_settings_payload()
        payload["game_ini"] = parse_ini_file(Path(path))
        payload["sources"]["game_ini"] = path
        self._save_server_settings(payload, "Game.ini imported.")

    def _select_ini_file(self, title: str) -> str | None:
        start_dir = str(Path.home())
        selected, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            title,
            start_dir,
            "INI files (*.ini);;All files (*)",
        )
        if not selected:
            self.show_toast("No settings file selected.", "info")
            return None
        return selected

    def _ensure_server_settings_payload(self) -> dict[str, object]:
        payload: dict[str, object]
        if self._server_settings:
            payload = dict(self._server_settings)
            payload.setdefault("game_user_settings", {})
            payload.setdefault("game_ini", {})
            payload.setdefault("sources", {})
        else:
            payload = {"game_user_settings": {}, "game_ini": {}, "sources": {}}
        payload["imported_at"] = QtCore.QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        return payload

    def _save_server_settings(self, payload: dict[str, object], message: str) -> None:
        set_server_settings(self._conn, payload)
        self._server_settings = payload
        self._update_settings_view()
        self.show_toast(message, "success")

    def show_toast(self, message: str, kind: str = "info") -> None:
        toast = ToastNotification(self, message=message, kind=kind, duration_ms=5000)
        self._toasts.append(toast)

        def _cleanup(_=None) -> None:
            if toast in self._toasts:
                self._toasts.remove(toast)

        toast.destroyed.connect(_cleanup)
        toast.show_at_bottom_right()
