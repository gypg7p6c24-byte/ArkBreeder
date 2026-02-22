from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable

from PySide6 import QtCore, QtGui, QtWidgets

from arkbreeder.config import bundled_values_path, user_data_dir
from arkbreeder.core.server_settings import parse_ini_file
from arkbreeder.core.species_values import SpeciesValuesStore
from arkbreeder.core.stats import StatMultipliers, compute_wild_levels, extract_stat_multipliers
from arkbreeder.storage.models import Creature
from arkbreeder.storage.repository import list_creatures
from arkbreeder.storage.settings import (
    get_server_settings,
    get_setting,
    set_server_settings,
    set_setting,
)
from arkbreeder.ui.dashboard_charts import BarChartWidget, DonutChartWidget
from arkbreeder.ui.radar_chart import RadarChart
from arkbreeder.ui.species_image import SpeciesImageWidget
from arkbreeder.ui.toast import ToastNotification

logger = logging.getLogger(__name__)

_DASHBOARD_COLORS = [
    "#38bdf8",
    "#f472b6",
    "#facc15",
    "#34d399",
    "#fb923c",
    "#a78bfa",
    "#60a5fa",
    "#f97316",
]

_SPECIES_DISPLAY_OVERRIDES = {
    "Ptero": "Pteranodon",
    "Argent": "Argentavis",
}

_POINT_STAT_CONFIG: list[tuple[str, str, str]] = [
    ("H", "Health", "Health"),
    ("S", "Stamina", "Stamina"),
    ("O", "Oxygen", "Oxygen"),
    ("F", "Food", "Food"),
    ("W", "Weight", "Weight"),
    ("M", "MeleeDamageMultiplier", "Melee"),
    ("Sp", "MovementSpeed", "Speed"),
]

_BREEDING_POINT_STAT_CONFIG: list[tuple[str, str, str]] = [
    (short, key, title)
    for short, key, title in _POINT_STAT_CONFIG
    if key != "MovementSpeed"
]

_BREEDING_FOCUS_OPTIONS = ["Overall"] + [
    title for _short, _key, title in _BREEDING_POINT_STAT_CONFIG
]

_STAT_INDEX_BY_POINT_KEY: dict[str, int] = {
    "Health": 0,
    "Stamina": 1,
    "Oxygen": 3,
    "Food": 4,
    "Weight": 7,
    "MeleeDamageMultiplier": 8,
    "MovementSpeed": 9,
}

_FLYING_SPECIES = {
    "argentavis",
    "pteranodon",
    "quetzal",
    "tapejara",
    "tropeognathus",
    "pelagornis",
    "ichthyornis",
    "dimorphodon",
    "griffin",
    "snow owl",
    "desmodus",
    "wyvern",
    "phoenix",
}

_FLYING_BLUEPRINT_HINTS = (
    "/dinos/argent",
    "/dinos/ptero/",
    "/dinos/quetz",
    "/dinos/tapejara",
    "/dinos/tropeo",
    "/dinos/pelagornis",
    "/dinos/ichthyornis",
    "/dinos/dimorphodon",
    "/dinos/griffin",
    "/dinos/snowowl",
    "/dinos/desmodus",
    "/dinos/wyvern",
    "/dinos/phoenix",
)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, conn, export_dir: Path) -> None:
        super().__init__()
        self.setWindowTitle("ARK Breeder")
        self.setMinimumSize(1120, 720)
        self._conn = conn
        self._export_dir = export_dir
        self._import_service = None
        self._toasts: list[ToastNotification] = []
        self._server_settings: dict | None = None
        self._values_store = SpeciesValuesStore()
        self._values_path: str | None = None
        self._values_from_bundle = False
        self._stat_multipliers = StatMultipliers()
        self._stat_points: dict[str, dict[str, int]] = {}
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
        self._load_server_settings()
        self._load_species_values()
        self.refresh_data()

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)

        self._nav = QtWidgets.QListWidget()
        self._nav.addItems(self._page_titles)
        self._nav.setFixedWidth(180)
        self._nav.setSpacing(6)
        self._nav.setFocusPolicy(QtCore.Qt.NoFocus)
        self._nav.setStyleSheet('''
        QListWidget { background: #0b1220; color: #e5e7eb; border: none; }
        QListWidget::item { padding: 10px 12px; margin: 4px 8px; border-radius: 12px; border: 0px; background: transparent; }
        QListWidget::item:hover { background: transparent; color: #ffffff; }
        QListWidget::item:selected { background: #1f2937; color: #ffffff; }
        QListWidget::item:focus { outline: none; }
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
        self._page_title.setStyleSheet("font-size: 30px; font-weight: 700; color: #f8fafc;")
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
            #contentArea QLineEdit, #contentArea QComboBox {
                background: #1e293b;
                color: #e5e7eb;
                border: 1px solid #334155;
                padding: 6px 10px;
                border-radius: 6px;
                min-height: 18px;
            }
            #contentArea QLineEdit:focus, #contentArea QComboBox:focus {
                border: 1px solid #475569;
            }
            #contentArea QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            #contentArea QScrollBar:vertical {
                background: #0f172a;
                width: 10px;
                margin: 2px;
            }
            #contentArea QScrollBar:horizontal {
                background: #0f172a;
                height: 10px;
                margin: 2px;
            }
            #contentArea QScrollBar::handle:vertical {
                background: #334155;
                min-height: 30px;
                border-radius: 5px;
            }
            #contentArea QScrollBar::handle:vertical:hover {
                background: #475569;
            }
            #contentArea QScrollBar::handle:vertical:pressed {
                background: #60a5fa;
            }
            #contentArea QScrollBar::handle:horizontal {
                background: #334155;
                min-width: 30px;
                border-radius: 5px;
            }
            #contentArea QScrollBar::handle:horizontal:hover {
                background: #475569;
            }
            #contentArea QScrollBar::handle:horizontal:pressed {
                background: #60a5fa;
            }
            #contentArea QScrollBar::add-line:vertical,
            #contentArea QScrollBar::sub-line:vertical {
                height: 0px;
            }
            #contentArea QScrollBar::add-line:horizontal,
            #contentArea QScrollBar::sub-line:horizontal {
                width: 0px;
            }
            #contentArea QComboBox QAbstractItemView {
                background: #0f172a;
                color: #e5e7eb;
                border: 1px solid #1f2937;
                selection-background-color: #1f2937;
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
        layout.setSpacing(8)

        hero = QtWidgets.QWidget()
        hero_layout = QtWidgets.QVBoxLayout(hero)
        hero_layout.setContentsMargins(6, 0, 6, 2)
        hero_title = QtWidgets.QLabel("Welcome to ARK Breeder")
        hero_title.setStyleSheet("font-size: 21px; font-weight: 700; color: #f8fafc;")
        hero_layout.addWidget(hero_title)

        charts = QtWidgets.QHBoxLayout()
        charts.setSpacing(8)

        left = QtWidgets.QFrame()
        left.setStyleSheet("QFrame { background: rgba(15, 23, 42, 0.44); border-radius: 16px; }")
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(10, 6, 10, 6)
        left_layout.setSpacing(2)
        left_title = QtWidgets.QLabel("Species distribution")
        left_title.setStyleSheet("color: #e2e8f0; font-weight: 700; font-size: 16px;")
        left_layout.addWidget(left_title)
        self._species_donut = DonutChartWidget()
        self._species_donut.setMinimumSize(96, 96)
        self._species_donut.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding,
        )
        left_layout.addWidget(self._species_donut, 1)
        self._species_legend = QtWidgets.QVBoxLayout()
        self._species_legend.setSpacing(1)
        self._species_legend.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        left_layout.addLayout(self._species_legend)

        right = QtWidgets.QFrame()
        right.setStyleSheet("QFrame { background: rgba(15, 23, 42, 0.44); border-radius: 16px; }")
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(10, 6, 10, 6)
        right_layout.setSpacing(4)
        right_title = QtWidgets.QLabel("Best breeding potential by species")
        right_title.setStyleSheet("color: #e2e8f0; font-weight: 700; font-size: 16px;")
        right_layout.addWidget(right_title)
        self._levels_bar = BarChartWidget()
        right_layout.addWidget(self._levels_bar, 1)

        charts.addWidget(left, 1)
        charts.addWidget(right, 1)

        extras = QtWidgets.QHBoxLayout()
        extras.setSpacing(8)

        gender_panel, self._dashboard_gender_layout = self._dashboard_panel("Gender split")
        self._gender_donut = DonutChartWidget()
        self._gender_donut.setMinimumSize(96, 96)
        self._gender_donut.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding,
        )
        self._dashboard_gender_layout.addWidget(self._gender_donut, 1)
        self._gender_legend = QtWidgets.QVBoxLayout()
        self._gender_legend.setSpacing(2)
        self._gender_legend.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        self._dashboard_gender_layout.addLayout(self._gender_legend)

        mutation_panel, self._dashboard_mutation_layout = self._dashboard_panel("Mutation pressure")
        self._mutation_bar = BarChartWidget()
        self._dashboard_mutation_layout.addWidget(self._mutation_bar, 1)

        points_panel, self._dashboard_points_layout = self._dashboard_panel("Best stat points")

        extras.addWidget(gender_panel, 1)
        extras.addWidget(mutation_panel, 1)
        extras.addWidget(points_panel, 1)

        layout.addWidget(hero)
        layout.addLayout(charts)
        layout.addLayout(extras)
        layout.setStretch(0, 0)
        layout.setStretch(1, 5)
        layout.setStretch(2, 4)
        return widget

    def _build_card(
        self,
        title: str,
        value_label: QtWidgets.QLabel,
        caption: str,
    ) -> QtWidgets.QWidget:
        card = QtWidgets.QFrame()
        card.setStyleSheet('''
        QFrame { background: rgba(15, 23, 42, 0.6); border-radius: 14px; }
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

    def _dashboard_panel(self, title: str) -> tuple[QtWidgets.QFrame, QtWidgets.QVBoxLayout]:
        panel = QtWidgets.QFrame()
        panel.setStyleSheet("QFrame { background: rgba(15, 23, 42, 0.44); border-radius: 16px; }")
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(3)
        title_label = QtWidgets.QLabel(title)
        title_label.setStyleSheet("color: #e2e8f0; font-weight: 700; font-size: 16px;")
        layout.addWidget(title_label)
        content = QtWidgets.QVBoxLayout()
        content.setSpacing(3)
        layout.addLayout(content)
        return panel, content

    def _build_creatures_page(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setSpacing(12)

        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setSpacing(12)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(8)
        self._creature_search = QtWidgets.QLineEdit()
        self._creature_search.setPlaceholderText("Search name or species")
        self._creature_search.setMinimumWidth(260)
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
        self._creatures_table.setAlternatingRowColors(False)
        self._creatures_table.setStyleSheet(
            """
            QTableWidget { background: transparent; border: none; gridline-color: transparent; }
            QTableWidget::item { padding: 6px; border-bottom: 1px solid rgba(148, 163, 184, 0.18); }
            QTableWidget::item:selected { background: #1f2937; color: #f8fafc; }
            QHeaderView::section { background: transparent; border: none; color: #cbd5f5; padding: 4px 6px; }
            """
        )
        self._creatures_table.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._creatures_table.setShowGrid(False)
        self._creatures_table.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._creatures_table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._creatures_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._creatures_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._creatures_table.verticalHeader().setVisible(False)
        header = self._creatures_table.horizontalHeader()
        header.setVisible(True)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self._creatures_table.setSortingEnabled(True)
        self._creatures_table.itemSelectionChanged.connect(self._on_creature_selected)

        left_layout.addWidget(self._creatures_table)

        right_panel = self._build_creature_detail_panel()
        right = QtWidgets.QScrollArea()
        right.setWidgetResizable(True)
        right.setFrameShape(QtWidgets.QFrame.NoFrame)
        right.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        right.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        right.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        right.setWidget(right_panel)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([860, 460])

        layout.addWidget(splitter)
        return widget

    def _build_breeding_page(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setSpacing(6)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(8)
        self._breeding_species_filter = QtWidgets.QComboBox()
        self._breeding_species_filter.currentIndexChanged.connect(self._update_breeding_pairs)
        toolbar.addWidget(self._breeding_species_filter)

        self._breeding_stat_focus = QtWidgets.QComboBox()
        self._breeding_stat_focus.addItems(_BREEDING_FOCUS_OPTIONS)
        self._breeding_stat_focus.currentIndexChanged.connect(self._update_breeding_pairs)
        toolbar.addWidget(self._breeding_stat_focus)

        self._breeding_refresh_btn = QtWidgets.QPushButton("Suggest pairs")
        self._breeding_refresh_btn.clicked.connect(self._update_breeding_pairs)
        toolbar.addWidget(self._breeding_refresh_btn)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self._breeding_points_info = QtWidgets.QLabel(
            "Stat points unavailable — import values.json in Settings."
        )
        self._breeding_points_info.setStyleSheet("color: #fbbf24;")
        self._breeding_points_info.setWordWrap(True)
        layout.addWidget(self._breeding_points_info)

        self._breeding_cards_container = QtWidgets.QWidget()
        self._breeding_cards_container.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding,
        )
        self._breeding_cards_layout = QtWidgets.QGridLayout(self._breeding_cards_container)
        self._breeding_cards_layout.setSpacing(10)
        self._breeding_cards_layout.setContentsMargins(2, 2, 2, 2)
        self._breeding_cards_layout.setAlignment(QtCore.Qt.AlignTop)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        scroll.setWidget(self._breeding_cards_container)
        scroll.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding,
        )
        layout.addWidget(scroll)
        return widget

    def _build_creature_detail_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QFrame()
        panel.setMinimumWidth(360)
        panel.setStyleSheet(
            """
            QFrame {
                background: rgba(15, 23, 42, 0.44);
                border-radius: 16px;
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
        self._detail_image.setStyleSheet("border: none;")
        layout.addWidget(self._detail_image, alignment=QtCore.Qt.AlignCenter)

        self._detail_radar = RadarChart(
            ["Health", "Stamina", "Oxygen", "Food", "Weight", "Melee", "Speed"]
        )
        layout.addWidget(self._detail_radar)

        self._detail_point_badges: dict[str, QtWidgets.QLabel] = {}
        points_grid = QtWidgets.QGridLayout()
        points_grid.setHorizontalSpacing(8)
        points_grid.setVerticalSpacing(8)
        for index, (label, key, _title) in enumerate(_POINT_STAT_CONFIG):
            badge = self._make_point_badge(label)
            self._detail_point_badges[key] = badge
            row = index // 4
            col = index % 4
            points_grid.addWidget(badge, row, col)
        layout.addLayout(points_grid)

        self._detail_stat_values: dict[str, QtWidgets.QLabel] = {}
        stat_rows = QtWidgets.QVBoxLayout()
        stat_rows.setSpacing(4)
        for _short, key, label in _POINT_STAT_CONFIG:
            row_widget = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            name_label = QtWidgets.QLabel(f"{label}:")
            name_label.setStyleSheet("color: #cbd5f5; font-size: 12px; font-weight: 600;")
            value_label = QtWidgets.QLabel("-")
            value_label.setStyleSheet("color: #f8fafc; font-weight: 600;")
            self._detail_stat_values[key] = value_label
            row_layout.addWidget(name_label)
            row_layout.addWidget(value_label)
            row_layout.addStretch(1)
            stat_rows.addWidget(row_widget)
        layout.addLayout(stat_rows)

        self._points_info = QtWidgets.QLabel(
            "Stat points unavailable — import values.json in Settings."
        )
        self._points_info.setStyleSheet("color: #fbbf24;")
        self._points_info.setWordWrap(True)
        layout.addWidget(self._points_info)

        self._detail_strengths = QtWidgets.QLabel("Strengths: -")
        self._detail_strengths.setStyleSheet("color: #a7f3d0; font-size: 15px; font-weight: 600;")
        self._detail_strengths.setTextFormat(QtCore.Qt.RichText)
        self._detail_strengths.setWordWrap(True)
        layout.addWidget(self._detail_strengths)

        self._detail_weaknesses = QtWidgets.QLabel("Weaknesses: -")
        self._detail_weaknesses.setStyleSheet("color: #fecaca; font-size: 15px; font-weight: 600;")
        self._detail_weaknesses.setTextFormat(QtCore.Qt.RichText)
        self._detail_weaknesses.setWordWrap(True)
        layout.addWidget(self._detail_weaknesses)

        layout.addStretch(1)
        return panel

    def _build_pedigree_page(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setSpacing(12)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(8)
        self._pedigree_species_filter = QtWidgets.QComboBox()
        self._pedigree_species_filter.currentIndexChanged.connect(self._update_pedigree_view)
        toolbar.addWidget(self._pedigree_species_filter)

        self._pedigree_creature_picker = QtWidgets.QComboBox()
        self._pedigree_creature_picker.currentIndexChanged.connect(self._update_pedigree_view)
        toolbar.addWidget(self._pedigree_creature_picker)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self._pedigree_tree = QtWidgets.QWidget()
        tree_layout = QtWidgets.QGridLayout(self._pedigree_tree)
        tree_layout.setHorizontalSpacing(12)
        tree_layout.setVerticalSpacing(0)
        tree_layout.setColumnStretch(0, 1)
        tree_layout.setColumnStretch(1, 1)
        tree_layout.setColumnStretch(2, 1)

        self._pedigree_mother_box = self._pedigree_node("Mother", "Unknown", "#f472b6")
        self._pedigree_father_box = self._pedigree_node("Father", "Unknown", "#60a5fa")
        self._pedigree_subject_box = self._pedigree_node("Selected", "Select a creature", "#38bdf8")

        self._pedigree_mother = self._pedigree_mother_box.findChild(QtWidgets.QLabel, "value")
        self._pedigree_father = self._pedigree_father_box.findChild(QtWidgets.QLabel, "value")
        self._pedigree_subject = self._pedigree_subject_box.findChild(QtWidgets.QLabel, "value")
        self._pedigree_mother_meta = self._pedigree_mother_box.findChild(QtWidgets.QLabel, "meta")
        self._pedigree_father_meta = self._pedigree_father_box.findChild(QtWidgets.QLabel, "meta")
        self._pedigree_subject_meta = self._pedigree_subject_box.findChild(QtWidgets.QLabel, "meta")
        self._pedigree_mother_avatar = self._pedigree_mother_box.findChild(QtWidgets.QLabel, "avatar")
        self._pedigree_father_avatar = self._pedigree_father_box.findChild(QtWidgets.QLabel, "avatar")
        self._pedigree_subject_avatar = self._pedigree_subject_box.findChild(QtWidgets.QLabel, "avatar")

        tree_layout.addWidget(self._pedigree_mother_box, 0, 0, alignment=QtCore.Qt.AlignCenter)
        tree_layout.addWidget(self._pedigree_father_box, 0, 2, alignment=QtCore.Qt.AlignCenter)

        tree_layout.addWidget(self._line(True), 1, 0, alignment=QtCore.Qt.AlignCenter)
        tree_layout.addWidget(self._line(True), 1, 2, alignment=QtCore.Qt.AlignCenter)

        tree_layout.addWidget(self._line(False), 2, 0, 1, 3)
        tree_layout.addWidget(self._line(True), 3, 1, alignment=QtCore.Qt.AlignCenter)
        tree_layout.addWidget(self._pedigree_subject_box, 4, 1, alignment=QtCore.Qt.AlignCenter)

        self._pedigree_tree.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding,
        )
        self._pedigree_empty = QtWidgets.QLabel(
            "No creatures with known mother and father found for this filter."
        )
        self._pedigree_empty.setStyleSheet("color: #94a3b8;")
        self._pedigree_empty.setAlignment(QtCore.Qt.AlignCenter)
        self._pedigree_empty.setWordWrap(True)
        self._pedigree_empty.setVisible(False)
        layout.addWidget(self._pedigree_empty)
        layout.addWidget(self._pedigree_tree)
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

        self._mutations_cards_container = QtWidgets.QWidget()
        self._mutations_cards_container.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding,
        )
        self._mutations_cards_layout = QtWidgets.QVBoxLayout(self._mutations_cards_container)
        self._mutations_cards_layout.setSpacing(12)
        self._mutations_cards_layout.addStretch(1)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setWidget(self._mutations_cards_container)
        scroll.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding,
        )
        layout.addWidget(scroll)
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

        export_header = QtWidgets.QLabel("Export watch folder")
        export_header.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(export_header)

        self._settings_export_path = QtWidgets.QLabel(f"Default: {self._export_dir}")
        self._settings_export_path.setWordWrap(True)
        self._settings_export_path.setStyleSheet("color: #94a3b8;")
        layout.addWidget(self._settings_export_path)

        export_actions = QtWidgets.QHBoxLayout()
        self._settings_open_export_btn = QtWidgets.QPushButton("Open export folder")
        self._settings_open_export_btn.clicked.connect(self._open_export_folder)
        export_actions.addWidget(self._settings_open_export_btn)
        export_actions.addStretch(1)
        layout.addLayout(export_actions)

        header = QtWidgets.QLabel("Server settings")
        header.setStyleSheet("font-size: 18px; font-weight: 700;")
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

        values_header = QtWidgets.QLabel("Creature values")
        values_header.setStyleSheet("font-size: 18px; font-weight: 700; margin-top: 12px;")
        layout.addWidget(values_header)

        values_helper = QtWidgets.QLabel(
            "Import values.json from ARKStatsExtractor to calculate stat point distribution."
        )
        values_helper.setWordWrap(True)
        values_helper.setStyleSheet("color: #cbd5f5;")
        layout.addWidget(values_helper)

        values_hint = QtWidgets.QLabel(
            "Hint: values.json usually lives in the ARKStatsExtractor data folder "
            "(for example: %APPDATA%/ARKStatsExtractor or ~/.config/ARKStatsExtractor)."
        )
        values_hint.setWordWrap(True)
        values_hint.setStyleSheet("color: #94a3b8; font-size: 12px;")
        layout.addWidget(values_hint)

        values_actions = QtWidgets.QHBoxLayout()
        self._import_values_btn = QtWidgets.QPushButton("Import values.json")
        self._import_values_btn.clicked.connect(self._import_values_json)
        values_actions.addWidget(self._import_values_btn)
        values_actions.addStretch(1)
        layout.addLayout(values_actions)

        self._values_summary = QtWidgets.QLabel("No values.json loaded.")
        self._values_summary.setWordWrap(True)
        self._values_summary.setStyleSheet("color: #94a3b8;")
        layout.addWidget(self._values_summary)

        self._values_details = QtWidgets.QLabel("")
        self._values_details.setWordWrap(True)
        self._values_details.setStyleSheet("color: #94a3b8;")
        layout.addWidget(self._values_details)

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
        self._recompute_stat_points()
        self._update_points_info_labels()
        self._update_dashboard(self._creature_cache)
        self._update_species_filters()
        self._apply_creature_filters()
        self._update_breeding_pairs()
        self._update_mutations_table()
        self._update_pedigree_view()

    def _update_dashboard(self, creatures: Iterable[Creature]) -> None:
        creature_list = list(creatures)
        species = {
            self._display_species(creature.species)
            for creature in creature_list
            if creature.species
        }
        mutations_total = sum(
            creature.mutations_maternal + creature.mutations_paternal for creature in creature_list
        )
        if hasattr(self, "_creatures_count"):
            self._creatures_count.setText(str(len(creature_list)))
        if hasattr(self, "_species_count"):
            self._species_count.setText(str(len(species)))
        if hasattr(self, "_mutations_count"):
            self._mutations_count.setText(str(mutations_total))

        if not hasattr(self, "_species_donut"):
            return

        species_counts: dict[str, int] = {}
        for creature in creature_list:
            if not creature.species:
                continue
            species_name = self._display_species(creature.species)
            species_counts[species_name] = species_counts.get(species_name, 0) + 1

        sorted_counts = sorted(species_counts.items(), key=lambda item: item[1], reverse=True)
        top_counts = sorted_counts[:6]
        if len(sorted_counts) > 6:
            other_total = sum(count for _, count in sorted_counts[6:])
            top_counts.append(("Other", other_total))

        donut_series = [
            (label, float(count), _DASHBOARD_COLORS[idx % len(_DASHBOARD_COLORS)])
            for idx, (label, count) in enumerate(top_counts)
        ]
        self._species_donut.set_series(donut_series)
        self._update_species_legend(donut_series)

        grouped: dict[str, list[Creature]] = {}
        for creature in creature_list:
            if creature.species:
                grouped.setdefault(self._display_species(creature.species), []).append(creature)

        use_points = self._points_available(creature_list)
        breeding_potential: list[tuple[str, float]] = []
        for label, group in grouped.items():
            males = [c for c in group if c.sex.lower() == "male"]
            females = [c for c in group if c.sex.lower() == "female"]
            if not males or not females:
                continue
            best_score = max(
                self._score_pair(male, female, "Overall", use_points=use_points)[0]
                for male in males
                for female in females
            )
            breeding_potential.append((label, best_score))

        if not breeding_potential:
            for label, count in species_counts.items():
                total_level = sum(
                    creature.level
                    for creature in creature_list
                    if self._display_species(creature.species) == label
                )
                breeding_potential.append((label, total_level / max(count, 1)))

        breeding_potential.sort(key=lambda item: item[1], reverse=True)
        bar_series = [
            (label, value, _DASHBOARD_COLORS[idx % len(_DASHBOARD_COLORS)])
            for idx, (label, value) in enumerate(breeding_potential[:6])
        ]
        self._levels_bar.set_series(bar_series)

        self._update_dashboard_gender(creature_list)
        self._update_dashboard_mutations(creature_list)
        self._update_dashboard_best_points(creature_list)
        self._update_dashboard_pairs(creature_list)
        self._update_dashboard_attention(creature_list)

    def _update_species_legend(self, series: list[tuple[str, float, str]]) -> None:
        if hasattr(self, "_species_legend"):
            self._update_legend(self._species_legend, series)

    def _update_legend(self, layout: QtWidgets.QVBoxLayout, series: list[tuple[str, float, str]]) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        for label, value, color in series:
            row = QtWidgets.QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(3)
            dot = QtWidgets.QLabel("●")
            dot.setStyleSheet(f"color: {color}; font-size: 10px;")
            text = QtWidgets.QLabel(f"{label}: {int(value)}")
            text.setStyleSheet("color: #cbd5f5; font-size: 11px;")
            row.addWidget(dot)
            row.addWidget(text)
            row.addStretch(1)
            container = QtWidgets.QWidget()
            container.setLayout(row)
            layout.addWidget(container)

    def _update_dashboard_gender(self, creatures: list[Creature]) -> None:
        if not hasattr(self, "_gender_donut"):
            return
        counts = {"Male": 0, "Female": 0}
        for creature in creatures:
            sex = (creature.sex or "").lower()
            if sex == "male":
                counts["Male"] += 1
            elif sex == "female":
                counts["Female"] += 1
        series = [
            ("Male", counts["Male"], "#60a5fa"),
            ("Female", counts["Female"], "#f472b6"),
        ]
        self._gender_donut.set_series(series)
        if hasattr(self, "_gender_legend"):
            self._update_legend(self._gender_legend, series)

    def _update_dashboard_mutations(self, creatures: list[Creature]) -> None:
        if not hasattr(self, "_mutation_bar"):
            return
        grouped: dict[str, list[Creature]] = {}
        for creature in creatures:
            if creature.species:
                grouped.setdefault(self._display_species(creature.species), []).append(creature)
        averages = []
        for species, group in grouped.items():
            total = sum(c.mutations_maternal + c.mutations_paternal for c in group)
            avg = total / max(len(group), 1)
            if avg > 0:
                averages.append((species, avg))
        averages.sort(key=lambda item: item[1], reverse=True)
        series = [
            (label, value, _DASHBOARD_COLORS[idx % len(_DASHBOARD_COLORS)])
            for idx, (label, value) in enumerate(averages[:6])
        ]
        self._mutation_bar.set_series(series)

    def _update_dashboard_best_points(self, creatures: list[Creature]) -> None:
        if not hasattr(self, "_dashboard_points_layout"):
            return
        self._clear_layout(self._dashboard_points_layout)
        if self._values_store.count() == 0:
            self._dashboard_points_layout.addWidget(
                self._empty_dashboard_label("Import values.json to compute stat points.")
            )
            return
        if not creatures:
            self._dashboard_points_layout.addWidget(
                self._empty_dashboard_label("No creatures yet.")
            )
            return
        entries = []
        for short, key, label in _POINT_STAT_CONFIG:
            best_value = -1
            best_creature: Creature | None = None
            for creature in creatures:
                value = self._get_stat_points_value(creature, key)
                if value is None:
                    continue
                if value > best_value:
                    best_value = int(value)
                    best_creature = creature
            if best_creature:
                entries.append((short, label, best_value, best_creature))
        if not entries:
            self._dashboard_points_layout.addWidget(
                self._empty_dashboard_label("Stat points unavailable for current creatures.")
            )
            return
        max_points = max(value for _short, _label, value, _creature in entries)
        for short, label, value, creature in entries:
            card = QtWidgets.QFrame()
            card.setStyleSheet(
                "QFrame { background: rgba(11, 19, 36, 0.8); border-radius: 12px; }"
            )
            layout = QtWidgets.QVBoxLayout(card)
            layout.setContentsMargins(8, 6, 8, 6)
            layout.setSpacing(4)
            title = QtWidgets.QLabel(f"{self._point_icon(short)} {label}")
            title.setStyleSheet("color: #93c5fd; font-weight: 700; font-size: 13px;")

            species_text = self._display_species(creature.species)
            owner = QtWidgets.QLabel(f"{creature.name} ({species_text})")
            owner.setStyleSheet("color: #e2e8f0; font-size: 12px; font-weight: 600;")

            ratio = 0.0 if max_points <= 0 else min(max(float(value) / float(max_points), 0.0), 1.0)
            tier = self._tier_color(ratio)
            bar = QtWidgets.QProgressBar()
            bar.setMaximum(100)
            bar.setValue(int(ratio * 100))
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            bar.setStyleSheet(
                f"""
                QProgressBar {{
                    background: #0f172a;
                    border: 1px solid #1f2937;
                    border-radius: 4px;
                }}
                QProgressBar::chunk {{
                    background: {tier};
                    border-radius: 4px;
                }}
                """
            )

            points = QtWidgets.QLabel(str(value))
            points.setStyleSheet(
                f"color: {tier}; font-weight: 800; font-size: 14px;"
            )
            points.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

            points_row = QtWidgets.QHBoxLayout()
            points_row.setContentsMargins(0, 0, 0, 0)
            points_row.setSpacing(6)
            points_row.addWidget(bar, 1)
            points_row.addWidget(points)

            layout.addWidget(title)
            layout.addWidget(owner)
            layout.addLayout(points_row)
            self._dashboard_points_layout.addWidget(card)
        self._dashboard_points_layout.addStretch(1)

    def _update_dashboard_pairs(self, creatures: list[Creature]) -> None:
        if not hasattr(self, "_dashboard_pairs_layout"):
            return
        self._clear_layout(self._dashboard_pairs_layout)
        if not creatures:
            self._dashboard_pairs_layout.addWidget(self._empty_dashboard_label("No creatures yet."))
            return

        use_points = self._points_available(creatures)
        grouped: dict[str, list[Creature]] = {}
        for creature in creatures:
            if creature.species:
                grouped.setdefault(self._display_species(creature.species), []).append(creature)

        best_pairs: list[tuple[float, str, Creature, Creature]] = []
        for species, group in grouped.items():
            males = [c for c in group if c.sex.lower() == "male"]
            females = [c for c in group if c.sex.lower() == "female"]
            if not males or not females:
                continue
            best_score = -1.0
            best_pair: tuple[Creature, Creature] | None = None
            for male in males:
                for female in females:
                    score, _, _ = self._score_pair(male, female, "Overall", use_points=use_points)
                    if score > best_score:
                        best_score = score
                        best_pair = (male, female)
            if best_pair:
                best_pairs.append((best_score, species, best_pair[0], best_pair[1]))

        if not best_pairs:
            self._dashboard_pairs_layout.addWidget(
                self._empty_dashboard_label("No breeding pairs available yet.")
            )
            return

        best_pairs.sort(key=lambda item: item[0], reverse=True)
        for score, species, male, female in best_pairs[:3]:
            card = QtWidgets.QFrame()
            card.setStyleSheet(
                "QFrame { background: rgba(11, 19, 36, 0.8); border-radius: 12px; }"
            )
            card_layout = QtWidgets.QVBoxLayout(card)
            card_layout.setSpacing(6)
            header = QtWidgets.QLabel(species)
            header.setStyleSheet("color: #e2e8f0; font-weight: 600;")
            pair_line = QtWidgets.QLabel(
                f"{self._sex_icon(male.sex)} {male.name}  ×  {self._sex_icon(female.sex)} {female.name}"
            )
            pair_line.setStyleSheet("color: #cbd5f5;")
            suffix = "points" if use_points else "raw"
            score_label = QtWidgets.QLabel(f"Score ({suffix}): {score:.2f}")
            score_label.setStyleSheet("color: #93c5fd; font-weight: 600;")
            card_layout.addWidget(header)
            card_layout.addWidget(pair_line)
            card_layout.addWidget(score_label)
            self._dashboard_pairs_layout.addWidget(card)

    def _update_dashboard_attention(self, creatures: list[Creature]) -> None:
        if not hasattr(self, "_dashboard_attention_layout"):
            return
        self._clear_layout(self._dashboard_attention_layout)
        if not creatures:
            self._dashboard_attention_layout.addWidget(
                self._empty_dashboard_label("Import creatures to unlock insights.")
            )
            return

        grouped: dict[str, list[Creature]] = {}
        for creature in creatures:
            if creature.species:
                grouped.setdefault(self._display_species(creature.species), []).append(creature)

        items: list[str] = []
        for species, group in grouped.items():
            males = [c for c in group if c.sex.lower() == "male"]
            females = [c for c in group if c.sex.lower() == "female"]
            if not males:
                items.append(f"{species}: add a male")
            if not females:
                items.append(f"{species}: add a female")
            if len(group) < 2:
                count = len(group)
                suffix = "creature" if count == 1 else "creatures"
                items.append(f"{species}: only {count} {suffix}")

        if self._values_store.count() == 0:
            items.insert(0, "Import values.json to enable stat points.")

        if not items:
            self._dashboard_attention_layout.addWidget(
                self._empty_dashboard_label("All species have breeding pairs.")
            )
            return

        for text in items[:6]:
            row = QtWidgets.QHBoxLayout()
            dot = QtWidgets.QFrame()
            dot.setFixedSize(8, 8)
            dot.setStyleSheet("QFrame { background: #f97316; border-radius: 4px; }")
            label = QtWidgets.QLabel(text)
            label.setStyleSheet("color: #f8fafc;")
            row.addWidget(dot)
            row.addWidget(label)
            row.addStretch(1)
            container = QtWidgets.QWidget()
            container.setLayout(row)
            self._dashboard_attention_layout.addWidget(container)

    def _clear_layout(self, layout: QtWidgets.QLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
                continue
            child_layout = item.layout()
            if child_layout:
                self._clear_layout(child_layout)

    def _empty_dashboard_label(self, text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        label.setStyleSheet("color: #94a3b8;")
        label.setWordWrap(True)
        return label

    def _update_points_info_labels(self) -> None:
        has_values = self._values_store.count() > 0
        if hasattr(self, "_points_info"):
            self._points_info.setVisible(not has_values)
        if hasattr(self, "_breeding_points_info"):
            self._breeding_points_info.setVisible(not has_values)

    def _recompute_stat_points(self) -> None:
        self._stat_points = {}
        if self._values_store.count() == 0:
            logger.debug("Stat points disabled: no species values loaded.")
            return
        for creature in self._creature_cache:
            points = self._compute_points_for_creature(creature)
            if creature.external_id and points:
                self._stat_points[creature.external_id] = points
        self._apply_lineage_point_consistency()
        logger.debug(
            "Computed stat points for %d/%d creatures.",
            len(self._stat_points),
            len(self._creature_cache),
        )

    def _apply_lineage_point_consistency(self) -> None:
        tracked_keys = {key for _short, key, _title in _POINT_STAT_CONFIG}
        for creature in self._creature_cache:
            if not creature.external_id:
                continue
            child_points = self._stat_points.get(creature.external_id)
            if not child_points:
                continue
            if not creature.mother_external_id or not creature.father_external_id:
                continue
            mother_points = self._stat_points.get(creature.mother_external_id)
            father_points = self._stat_points.get(creature.father_external_id)
            if not mother_points or not father_points:
                continue
            # If no mutation counters are present, a child stat should match one parent stat.
            if creature.mutations_maternal != 0 or creature.mutations_paternal != 0:
                continue

            for key in tracked_keys:
                parent_values = []
                mv = mother_points.get(key)
                fv = father_points.get(key)
                if mv is not None:
                    parent_values.append(int(mv))
                if fv is not None:
                    parent_values.append(int(fv))
                if not parent_values:
                    continue
                current = child_points.get(key)
                if current is None:
                    child_points[key] = parent_values[0]
                    continue
                child_points[key] = min(parent_values, key=lambda value: abs(int(current) - value))

    def _compute_points_for_creature(self, creature: Creature) -> dict[str, int]:
        values = self._resolve_species_values(creature)
        if values is None:
            return {}
        te_hint: float | None = None
        # Bred creatures have fixed tame effectiveness behavior in ARK formulas.
        if (
            creature.imprinting_quality is not None
            and creature.imprinting_quality > 0
        ) or creature.mother_external_id or creature.father_external_id:
            te_hint = 1.0
        return compute_wild_levels(
            creature.stats,
            values,
            self._stat_multipliers,
            creature.imprinting_quality,
            character_level=creature.level,
            taming_effectiveness_hint=te_hint,
        )

    def _resolve_species_values(self, creature: Creature):
        if creature.blueprint:
            values = self._values_store.get_by_blueprint(creature.blueprint)
            if values is not None:
                return values
        values = self._values_store.get_by_species(creature.species)
        if values is not None:
            return values
        display_species = self._display_species(creature.species)
        if display_species != creature.species:
            return self._values_store.get_by_species(display_species)
        return None

    def _get_stat_points(self, creature: Creature) -> dict[str, int]:
        if creature.external_id and creature.external_id in self._stat_points:
            return self._stat_points[creature.external_id]
        return self._compute_points_for_creature(creature)

    def _get_stat_points_value(self, creature: Creature, key: str) -> float | None:
        points = self._get_stat_points(creature)
        if not points:
            return None
        value = points.get(key)
        return float(value) if value is not None else None

    def _points_available(self, creatures: Iterable[Creature]) -> bool:
        for creature in creatures:
            if self._get_stat_points(creature):
                return True
        return False

    def _populate_creatures_table(self, creatures: Iterable[Creature]) -> None:
        creature_list = list(creatures)
        self._creature_rows = creature_list
        sorting = self._creatures_table.isSortingEnabled()
        if sorting:
            self._creatures_table.setSortingEnabled(False)
        self._creatures_table.setRowCount(len(creature_list))
        for row, creature in enumerate(creature_list):
            self._set_table_item(row, 0, creature.name, creature.external_id)
            self._set_table_item(row, 1, self._display_species(creature.species))
            self._set_table_item(row, 2, creature.sex)
            self._set_table_item(row, 3, str(creature.level))
            self._set_table_item(
                row,
                4,
                f"{creature.mutations_maternal}/{creature.mutations_paternal}",
            )
            self._set_table_item(row, 5, self._format_stat(creature.stats.get("Health"), "Health"))
            self._set_table_item(row, 6, self._format_stat(creature.stats.get("Stamina"), "Stamina"))
            self._set_table_item(row, 7, self._format_stat(creature.stats.get("Weight"), "Weight"))
            self._set_table_item(
                row,
                8,
                self._format_stat(creature.stats.get("MeleeDamageMultiplier"), "MeleeDamageMultiplier"),
            )
            self._set_table_item(row, 9, self._format_updated_at(creature.updated_at))
        if sorting:
            self._creatures_table.setSortingEnabled(True)
        self._restore_creature_selection()

    def _restore_creature_selection(self) -> None:
        if not self._creature_rows:
            return
        target_id = self._selected_creature.external_id if self._selected_creature else None
        if target_id:
            for row in range(self._creatures_table.rowCount()):
                item = self._creatures_table.item(row, 0)
                if item and item.data(QtCore.Qt.UserRole) == target_id:
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
                if self._display_species(creature.species) != species_filter:
                    continue
            if text:
                hay = f"{creature.name} {self._display_species(creature.species)}".lower()
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
        species_list = sorted(
            {
                self._display_species(c.species)
                for c in self._creature_cache
                if c.species
            }
        )
        self._update_filter_combo(self._creature_species_filter, species_list)
        self._update_filter_combo(self._breeding_species_filter, species_list)
        self._update_filter_combo(self._mutations_species_filter, species_list)
        self._update_filter_combo(self._pedigree_species_filter, species_list)
        self._update_pedigree_creature_picker()

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

    def _update_pedigree_creature_picker(self) -> None:
        species = self._pedigree_species_filter.currentText()
        candidates = self._pedigree_candidates(species)
        current = (
            self._pedigree_creature_picker.currentText()
            if self._pedigree_creature_picker.count()
            else ""
        )
        self._pedigree_creature_picker.blockSignals(True)
        self._pedigree_creature_picker.clear()
        for creature in candidates:
            label = f"{creature.name} ({creature.sex})"
            self._pedigree_creature_picker.addItem(label, creature)
        index = -1
        if current:
            index = self._pedigree_creature_picker.findText(current)
        if index < 0 and self._pedigree_creature_picker.count() > 0:
            index = 0
        if index >= 0:
            self._pedigree_creature_picker.setCurrentIndex(index)
        self._pedigree_creature_picker.blockSignals(False)

    def _pedigree_candidates(self, species_filter: str) -> list[Creature]:
        candidates: list[Creature] = []
        for creature in self._creature_cache:
            if species_filter != "All species" and self._display_species(creature.species) != species_filter:
                continue
            mother = self._find_creature_by_id(creature.mother_id) or self._find_creature_by_external_id(
                creature.mother_external_id
            )
            father = self._find_creature_by_id(creature.father_id) or self._find_creature_by_external_id(
                creature.father_external_id
            )
            if mother and father:
                candidates.append(creature)
        return candidates

    def _update_breeding_pairs(self) -> None:
        species = self._breeding_species_filter.currentText()
        focus = self._breeding_stat_focus.currentText()
        show_ranking = species != "All species"
        creatures = [
            c
            for c in self._creature_cache
            if species == "All species" or self._display_species(c.species) == species
        ]
        grouped: dict[str, list[Creature]] = {}
        for creature in creatures:
            key = self._display_species(creature.species)
            grouped.setdefault(key, []).append(creature)
        use_points = True
        rows: list[tuple[str, list[tuple[str, int]], list[tuple[int, float, Creature, Creature]]]] = []
        for species_name, group in grouped.items():
            males = [c for c in group if c.sex.lower() == "male"]
            females = [c for c in group if c.sex.lower() == "female"]
            if not males or not females:
                continue
            all_pairs: list[tuple[float, Creature, Creature]] = []
            for male in males:
                for female in females:
                    score, _, _ = self._score_pair(
                        male,
                        female,
                        focus,
                        use_points=use_points,
                    )
                    all_pairs.append((score, male, female))

            if not all_pairs:
                continue
            all_pairs.sort(
                key=lambda item: (
                    -item[0],
                    item[1].name.lower(),
                    item[2].name.lower(),
                )
            )

            limit = 1 if not show_ranking else min(12, len(all_pairs))
            ranked_pairs = [
                (rank + 1, score, male, female)
                for rank, (score, male, female) in enumerate(all_pairs[:limit])
            ]
            targets = self._species_target_points(group)
            rows.append((species_name, targets, ranked_pairs))

        rows.sort(key=lambda item: item[2][0][1] if item[2] else -1.0, reverse=True)
        self._render_breeding_cards(rows, focus, use_points, show_ranking=show_ranking)

    def _species_target_points(self, group: list[Creature]) -> list[tuple[str, int]]:
        targets: list[tuple[str, int]] = []
        for short, key, _title in _BREEDING_POINT_STAT_CONFIG:
            values = [
                int(value)
                for creature in group
                if (value := self._get_stat_points_value(creature, key)) is not None
            ]
            if not values:
                continue
            targets.append((short, max(values)))
        return targets

    def _score_pair(
        self,
        male: Creature,
        female: Creature,
        focus: str,
        use_points: bool = False,
    ) -> tuple[float, float, float]:
        score_keys = [key for _short, key, _title in _BREEDING_POINT_STAT_CONFIG]
        if focus == "Overall":
            best_stats = [
                max(
                    self._get_stat_value(male, key, use_points=use_points),
                    self._get_stat_value(female, key, use_points=use_points),
                )
                for key in score_keys
            ]
            score = sum(best_stats)
            return score, self._overall_score(male, use_points), self._overall_score(female, use_points)

        focus_to_key = {title: key for _short, key, title in _BREEDING_POINT_STAT_CONFIG}
        key = focus_to_key.get(focus, "Health")
        male_stat = self._get_stat_value(male, key, use_points=use_points)
        female_stat = self._get_stat_value(female, key, use_points=use_points)
        score = max(male_stat, female_stat)
        return score, male_stat, female_stat

    def _overall_score(self, creature: Creature, use_points: bool = False) -> float:
        return sum(
            self._get_stat_value(creature, key, use_points=use_points)
            for _short, key, _title in _POINT_STAT_CONFIG
        )

    def _species_max_stats(self, species: str, use_points: bool = False) -> dict[str, float]:
        candidates = [
            c
            for c in self._creature_cache
            if self._display_species(c.species) == self._display_species(species)
        ]
        stat_keys = {key for _short, key, _title in _POINT_STAT_CONFIG}
        if not use_points:
            for creature in candidates:
                stat_keys.update(creature.stats.keys())

        stats: dict[str, float] = {}
        for key in stat_keys:
            stats[key] = max(
                (
                    self._get_stat_value(
                        c,
                        key,
                        use_points=use_points,
                        points_only=use_points,
                    )
                    for c in candidates
                ),
                default=1.0,
            )
        return stats

    def _get_stat_value(
        self,
        creature: Creature,
        key: str,
        use_points: bool = False,
        points_only: bool = False,
    ) -> float:
        if use_points:
            points_value = self._get_stat_points_value(creature, key)
            if points_value is not None:
                return points_value
            if points_only:
                return 0.0
        value = creature.stats.get(key)
        if value is None:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _format_score(self, value: float) -> str:
        return f"{value:.2f}"

    def _display_species(self, species: str) -> str:
        if not species:
            return "Unknown"
        return _SPECIES_DISPLAY_OVERRIDES.get(species, species)

    def _is_flying_creature(self, creature: Creature) -> bool:
        species = self._display_species(creature.species).strip().lower()
        if species in _FLYING_SPECIES:
            return True
        blueprint = (creature.blueprint or "").strip().lower()
        return any(token in blueprint for token in _FLYING_BLUEPRINT_HINTS)

    def _line(self, vertical: bool) -> QtWidgets.QFrame:
        line = QtWidgets.QFrame()
        if vertical:
            line.setFixedWidth(3)
            line.setFixedHeight(40)
        else:
            line.setFixedHeight(3)
        line.setStyleSheet("QFrame { background: #334155; border-radius: 1px; }")
        return line

    def _pedigree_node(self, title: str, value: str, accent: str) -> QtWidgets.QFrame:
        node = QtWidgets.QFrame()
        node.setMinimumWidth(180)
        node.setMaximumWidth(240)
        node.setStyleSheet(
            f"QFrame {{ background: rgba(11, 19, 36, 0.9); border: 1px solid {accent}; border-radius: 14px; }}"
        )
        layout = QtWidgets.QVBoxLayout(node)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 10, 10, 10)
        label = QtWidgets.QLabel(title)
        label.setStyleSheet("color: #94a3b8; font-size: 11px; text-transform: uppercase;")
        avatar = QtWidgets.QLabel()
        avatar.setObjectName("avatar")
        avatar.setFixedSize(60, 44)
        avatar.setAlignment(QtCore.Qt.AlignCenter)
        avatar.setStyleSheet("background: #0b1324; border-radius: 8px; color: #94a3b8;")
        value_label = QtWidgets.QLabel(value)
        value_label.setObjectName("value")
        value_label.setAlignment(QtCore.Qt.AlignCenter)
        value_label.setStyleSheet("color: #f8fafc; font-weight: 700; font-size: 14px;")
        meta_label = QtWidgets.QLabel("")
        meta_label.setObjectName("meta")
        meta_label.setAlignment(QtCore.Qt.AlignCenter)
        meta_label.setWordWrap(True)
        meta_label.setStyleSheet("color: #94a3b8; font-size: 11px;")
        layout.addWidget(label, alignment=QtCore.Qt.AlignCenter)
        layout.addWidget(avatar, alignment=QtCore.Qt.AlignCenter)
        layout.addWidget(value_label)
        layout.addWidget(meta_label)
        return node

    def _render_breeding_cards(
        self,
        rows: list[tuple[str, list[tuple[str, int]], list[tuple[int, float, Creature, Creature]]]],
        focus: str,
        use_points: bool,
        show_ranking: bool = True,
    ) -> None:
        layout = self._breeding_cards_layout
        self._clear_layout(layout)

        if not rows:
            empty = QtWidgets.QLabel("No breeding pairs found for this filter.")
            empty.setStyleSheet("color: #94a3b8;")
            layout.addWidget(empty, 0, 0)
            return

        row_index = 0
        for species_name, targets, ranked_pairs in rows:
            row_card = QtWidgets.QWidget()
            row_card.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding,
                QtWidgets.QSizePolicy.Maximum,
            )
            row_layout = QtWidgets.QVBoxLayout(row_card)
            row_layout.setSpacing(2)
            row_layout.setContentsMargins(0, 0, 0, 8)

            header = QtWidgets.QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            species_label = QtWidgets.QLabel(species_name)
            species_label.setStyleSheet("color: #cbd5f5; font-weight: 700; font-size: 13px;")
            header.addWidget(species_label)
            header.addStretch(1)
            row_layout.addLayout(header)

            if targets:
                target_row = QtWidgets.QHBoxLayout()
                target_row.setContentsMargins(0, 0, 0, 0)
                target_row.setSpacing(4)
                target_label = QtWidgets.QLabel("Target:")
                target_label.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600;")
                target_row.addWidget(target_label)
                for short, value in targets:
                    chip = QtWidgets.QLabel(f"{self._point_icon(short)} {value}")
                    chip.setStyleSheet(
                        "color: #67e8f9; font-size: 11px; font-weight: 700;"
                        "background: rgba(103, 232, 249, 26); border: 1px solid #67e8f9; border-radius: 7px;"
                        "padding: 1px 6px;"
                    )
                    target_row.addWidget(chip)
                target_row.addStretch(1)
                row_layout.addLayout(target_row)

            if show_ranking:
                hint = self._next_plan_hint(ranked_pairs, targets, use_points=use_points)
                if hint:
                    hint_label = QtWidgets.QLabel(hint)
                    hint_label.setStyleSheet("color: #93c5fd; font-size: 11px;")
                    hint_label.setWordWrap(True)
                    row_layout.addWidget(hint_label)

            max_stats = self._species_max_stats(species_name, use_points=use_points)
            for rank, _score, male, female in ranked_pairs:
                pair_layout = QtWidgets.QHBoxLayout()
                pair_layout.setSpacing(2)
                pair_layout.setContentsMargins(0, 0, 0, 0)
                if show_ranking:
                    rank_label = QtWidgets.QLabel(f"#{rank}")
                    rank_label.setAlignment(QtCore.Qt.AlignCenter)
                    rank_label.setFixedWidth(28)
                    rank_label.setStyleSheet(
                        "color: #facc15; font-size: 11px; font-weight: 700;"
                        "background: #0f172a; border: 1px solid #1f2937; border-radius: 7px;"
                    )
                    pair_layout.addWidget(rank_label)
                male_box = self._pair_info_box(male, max_stats, use_points=use_points, points_only=True)
                female_box = self._pair_info_box(female, max_stats, use_points=use_points, points_only=True)
                child_box = self._pair_child_box(
                    male,
                    female,
                    max_stats,
                    use_points=use_points,
                )
                pair_layout.addWidget(male_box)
                plus = QtWidgets.QLabel("+")
                plus.setAlignment(QtCore.Qt.AlignCenter)
                plus.setFixedWidth(18)
                plus.setStyleSheet("color: #cbd5f5; font-size: 16px; font-weight: 700;")
                pair_layout.addWidget(plus)
                pair_layout.addWidget(female_box)
                arrow = QtWidgets.QLabel("⟶")
                arrow.setAlignment(QtCore.Qt.AlignCenter)
                arrow.setFixedWidth(28)
                arrow.setStyleSheet("color: #93c5fd; font-size: 20px; font-weight: 700;")
                pair_layout.addWidget(arrow)
                pair_layout.addWidget(child_box)
                pair_layout.addStretch(1)
                row_layout.addLayout(pair_layout)
            layout.addWidget(row_card, row_index, 0)
            row_index += 1

    def _pair_info_box(
        self,
        creature: Creature,
        max_stats: dict[str, float],
        use_points: bool = False,
        points_only: bool = False,
    ) -> QtWidgets.QWidget:
        sex_lower = creature.sex.lower() if creature.sex else ""
        accent = "#94a3b8"
        if sex_lower == "male":
            accent = "#60a5fa"
        elif sex_lower == "female":
            accent = "#f472b6"
        box = QtWidgets.QFrame()
        box.setObjectName("pairCard")
        box.setMinimumWidth(168)
        box.setMaximumWidth(184)
        box.setStyleSheet(
            "#pairCard {"
            "background: rgba(11, 19, 36, 0.85);"
            f"border: 1px solid {accent};"
            "border-radius: 14px;"
            "}"
        )
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(2)
        name_label = QtWidgets.QLabel(f"{self._sex_icon(creature.sex)} {creature.name}")
        name_label.setStyleSheet(
            f"color: {accent}; font-weight: 700; font-size: 13px; background: transparent; border: none;"
        )
        layout.addWidget(name_label)

        avatar = self._small_species_image(self._display_species(creature.species), size=100)
        layout.addWidget(avatar, alignment=QtCore.Qt.AlignCenter)

        colors = {
            "Health": "#22c55e",
            "Stamina": "#38bdf8",
            "Oxygen": "#14b8a6",
            "Food": "#facc15",
            "Weight": "#f59e0b",
            "MeleeDamageMultiplier": "#f97316",
            "MovementSpeed": "#a78bfa",
        }
        for short_label, key, _title in _BREEDING_POINT_STAT_CONFIG:
            layout.addWidget(
                self._stat_bar_row(
                    short_label,
                    creature,
                    key,
                    max_stats.get(key, 1.0),
                    colors.get(key, "#64748b"),
                    use_points,
                    points_only=points_only,
                )
            )
        return box

    def _pair_child_box(
        self,
        male: Creature,
        female: Creature,
        max_stats: dict[str, float],
        use_points: bool = False,
    ) -> QtWidgets.QWidget:
        box = QtWidgets.QFrame()
        box.setObjectName("pairCardChild")
        box.setMinimumWidth(168)
        box.setMaximumWidth(184)
        box.setStyleSheet(
            "#pairCardChild {"
            "background: rgba(11, 19, 36, 0.85);"
            "border: 1px solid #64748b;"
            "border-radius: 14px;"
            "}"
        )
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(2)
        name_label = QtWidgets.QLabel("◌ Expected")
        name_label.setStyleSheet(
            "color: #cbd5f5; font-weight: 700; font-size: 13px; background: transparent; border: none;"
        )
        layout.addWidget(name_label)
        species_label = self._display_species(male.species or female.species)
        avatar = self._small_species_image(species_label, size=100)
        layout.addWidget(avatar, alignment=QtCore.Qt.AlignCenter)

        child_points = self._expected_child_points(male, female, use_points=use_points)
        colors = {
            "Health": "#22c55e",
            "Stamina": "#38bdf8",
            "Oxygen": "#14b8a6",
            "Food": "#facc15",
            "Weight": "#f59e0b",
            "MeleeDamageMultiplier": "#f97316",
            "MovementSpeed": "#a78bfa",
        }
        for short_label, key, _title in _BREEDING_POINT_STAT_CONFIG:
            layout.addWidget(
                self._stat_bar_value_row(
                    short_label,
                    float(child_points.get(key, 0.0)),
                    max_stats.get(key, 1.0),
                    colors.get(key, "#64748b"),
                )
            )
        return box

    def _expected_child_points(
        self,
        male: Creature,
        female: Creature,
        use_points: bool = False,
    ) -> dict[str, float]:
        result: dict[str, float] = {}
        for _short, key, _title in _BREEDING_POINT_STAT_CONFIG:
            male_value = self._get_stat_value(male, key, use_points=use_points, points_only=use_points)
            female_value = self._get_stat_value(female, key, use_points=use_points, points_only=use_points)
            result[key] = max(float(male_value), float(female_value))
        return result

    def _next_plan_hint(
        self,
        ranked_pairs: list[tuple[int, float, Creature, Creature]],
        targets: list[tuple[str, int]],
        use_points: bool = False,
    ) -> str | None:
        if len(ranked_pairs) <= 1 or not targets:
            return None
        first_male = ranked_pairs[0][2]
        first_female = ranked_pairs[0][3]
        expected = self._expected_child_points(first_male, first_female, use_points=use_points)
        short_to_key = {short: key for short, key, _title in _BREEDING_POINT_STAT_CONFIG}
        pending = [
            (short, short_to_key[short], target)
            for short, target in targets
            if short in short_to_key and expected.get(short_to_key[short], 0.0) + 0.001 < float(target)
        ]
        if not pending:
            return "Plan: #1 already matches all current target stats."

        best_rank = None
        best_gain = 0.0
        best_stats: list[str] = []
        for rank, _score, male, female in ranked_pairs[1:]:
            gained_stats: list[str] = []
            gain_total = 0.0
            for short, key, _target in pending:
                donor = max(
                    self._get_stat_value(male, key, use_points=use_points, points_only=use_points),
                    self._get_stat_value(female, key, use_points=use_points, points_only=use_points),
                )
                delta = donor - expected.get(key, 0.0)
                if delta > 0:
                    gain_total += delta
                    gained_stats.append(short)
            if gain_total > best_gain:
                best_gain = gain_total
                best_rank = rank
                best_stats = gained_stats

        if best_rank is None or not best_stats:
            pending_labels = ", ".join(short for short, _key, _target in pending)
            return f"Plan: keep #1 and look for donor lines improving {pending_labels}."
        boosted = ", ".join(best_stats)
        return f"Plan: breed Expected #1 with donor from #{best_rank} to push {boosted}."

    def _stat_bar_row(
        self,
        label: str,
        creature: Creature,
        key: str,
        max_value: float,
        color: str,
        use_points: bool = False,
        points_only: bool = False,
    ) -> QtWidgets.QWidget:
        row = QtWidgets.QWidget()
        row_layout = QtWidgets.QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)
        tag = QtWidgets.QLabel(self._point_icon(label))
        tag.setAlignment(QtCore.Qt.AlignCenter)
        tag.setFixedWidth(20)
        tag.setStyleSheet(
            "color: #e2e8f0; font-size: 11px; font-weight: 700;"
            "background: #0f172a; border: 1px solid #1f2937; border-radius: 6px;"
        )
        bar = QtWidgets.QProgressBar()
        bar.setMaximum(100)
        value = self._get_stat_value(
            creature,
            key,
            use_points=use_points,
            points_only=points_only,
        )
        is_top_value = max_value > 0 and value >= (max_value - 0.001)
        ratio = 0.0 if max_value <= 0 else min(max(value / max_value, 0.0), 1.0)
        tier_color = self._tier_color(ratio)
        bar.setValue(int(ratio * 100))
        bar.setTextVisible(False)
        bar.setFixedHeight(7)
        bar.setStyleSheet(
            f"""
            QProgressBar {{
                background: #0f172a;
                border: 1px solid #1f2937;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background: {color};
                border-radius: 4px;
            }}
            """
        )
        row_layout.addWidget(tag)
        row_layout.addWidget(bar, 1)
        points_value = self._get_stat_points_value(creature, key) if use_points else None
        if points_value is not None:
            displayed_value = str(int(points_value))
        elif points_only:
            displayed_value = "-"
        else:
            displayed_value = self._format_stat(creature.stats.get(key), key, creature=creature)
        value_label = QtWidgets.QLabel(displayed_value)
        if points_only or use_points:
            tag.setStyleSheet(
                f"color: {tier_color}; font-size: 11px; font-weight: 700;"
                "background: #0f172a; border: 1px solid #1f2937; border-radius: 6px;"
            )
            value_label.setStyleSheet(
                f"color: {tier_color}; font-size: 11px; font-weight: 700;"
                "background: #0f172a; border: 1px solid #1f2937; border-radius: 6px; padding: 1px 4px;"
            )
        if not (points_only or use_points):
            value_label.setStyleSheet(
                "color: #cbd5f5; font-size: 11px; font-weight: 700;"
                "background: #0f172a; border: 1px solid #1f2937; border-radius: 6px; padding: 1px 4px;"
            )
        if is_top_value and (points_only or use_points):
            value_label.setStyleSheet(
                f"color: {tier_color}; font-size: 11px; font-weight: 800;"
                f"background: rgba(103, 232, 249, 30); border: 1px solid {tier_color};"
                "border-radius: 6px; padding: 1px 4px;"
            )
        value_label.setMinimumWidth(34)
        value_label.setAlignment(QtCore.Qt.AlignCenter)
        row_layout.addWidget(value_label)
        return row

    def _stat_bar_value_row(
        self,
        label: str,
        value: float,
        max_value: float,
        color: str,
    ) -> QtWidgets.QWidget:
        row = QtWidgets.QWidget()
        row_layout = QtWidgets.QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)
        tag = QtWidgets.QLabel(self._point_icon(label))
        tag.setAlignment(QtCore.Qt.AlignCenter)
        tag.setFixedWidth(20)
        tag.setStyleSheet(
            "color: #e2e8f0; font-size: 11px; font-weight: 700;"
            "background: #0f172a; border: 1px solid #1f2937; border-radius: 6px;"
        )
        bar = QtWidgets.QProgressBar()
        bar.setMaximum(100)
        ratio = 0.0 if max_value <= 0 else min(max(float(value) / float(max_value), 0.0), 1.0)
        is_top_value = max_value > 0 and value >= (max_value - 0.001)
        tier_color = self._tier_color(ratio)
        bar.setValue(int(ratio * 100))
        bar.setTextVisible(False)
        bar.setFixedHeight(7)
        bar.setStyleSheet(
            f"""
            QProgressBar {{
                background: #0f172a;
                border: 1px solid #1f2937;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background: {color};
                border-radius: 4px;
            }}
            """
        )
        row_layout.addWidget(tag)
        row_layout.addWidget(bar, 1)
        value_label = QtWidgets.QLabel(str(int(round(value))))
        tag.setStyleSheet(
            f"color: {tier_color}; font-size: 11px; font-weight: 700;"
            "background: #0f172a; border: 1px solid #1f2937; border-radius: 6px;"
        )
        value_label.setStyleSheet(
            f"color: {tier_color}; font-size: 11px; font-weight: 700;"
            "background: #0f172a; border: 1px solid #1f2937; border-radius: 6px; padding: 1px 4px;"
        )
        if is_top_value:
            value_label.setStyleSheet(
                f"color: {tier_color}; font-size: 11px; font-weight: 800;"
                f"background: rgba(103, 232, 249, 30); border: 1px solid {tier_color};"
                "border-radius: 6px; padding: 1px 4px;"
            )
        value_label.setMinimumWidth(34)
        value_label.setAlignment(QtCore.Qt.AlignCenter)
        row_layout.addWidget(value_label)
        return row

    def _make_point_badge(self, label: str) -> QtWidgets.QLabel:
        badge = QtWidgets.QLabel(self._point_icon(label))
        badge.setAlignment(QtCore.Qt.AlignCenter)
        badge.setMinimumWidth(76)
        badge.setStyleSheet(
            """
            QLabel {
                background: #111827;
                border: 1px solid #1f2937;
                border-radius: 10px;
                padding: 6px 8px;
                font-weight: 600;
            }
            """
        )
        return badge

    def _point_icon(self, code: str) -> str:
        icons = {
            "H": "✚",
            "S": "⚗",
            "O": "O₂",
            "F": "♨",
            "W": "⚖",
            "M": "🗡︎",
            "Sp": "≫",
        }
        return icons.get(code, code)

    def _small_species_image(self, species: str, size: int = 48) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel()
        label.setFixedSize(size, int(size * 0.75))
        label.setAlignment(QtCore.Qt.AlignCenter)
        label.setStyleSheet("background: #0b1324; border-radius: 8px; color: #94a3b8;")
        cache_path = self._species_cache_path(species)
        if cache_path.exists():
            pixmap = QtGui.QPixmap(str(cache_path))
            if not pixmap.isNull():
                label.setPixmap(
                    pixmap.scaled(
                        label.size(),
                        QtCore.Qt.KeepAspectRatio,
                        QtCore.Qt.SmoothTransformation,
                    )
                )
                return label
        label.setText(species[:1].upper() if species else "?")
        return label

    def _species_cache_path(self, species: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", species).lower()
        cache_dir = user_data_dir() / "cache" / "images"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"{safe}.png"

    def _update_point_badges(self, creature: Creature, species_group: list[Creature]) -> None:
        labels = {key: short for short, key, _title in _POINT_STAT_CONFIG}
        points = self._get_stat_points(creature)
        max_points_by_key: dict[str, int] = {}
        for _short, key, _title in _POINT_STAT_CONFIG:
            values = [
                int(value)
                for candidate in species_group
                if (value := self._get_stat_points_value(candidate, key)) is not None
            ]
            if values:
                max_points_by_key[key] = max(values)
        for key, badge in self._detail_point_badges.items():
            label = labels.get(key, "?")
            icon = self._point_icon(label)
            value = points.get(key) if points else None
            raw_value = self._get_stat_value(creature, key, use_points=False)
            raw_text = self._format_stat(raw_value, key, creature=creature)
            if value is None:
                badge.setText(icon)
                badge.setStyleSheet(self._point_badge_style("#111827", "#94a3b8"))
                badge.setToolTip(f"Raw: {raw_text}\nPoints: -")
                continue
            badge.setText(f"{icon} {int(value)}")
            max_value = max_points_by_key.get(key)
            if max_value is not None and max_value > 0:
                ratio = min(max(float(value) / float(max_value), 0.0), 1.0)
                tier = self._tier_color(ratio)
                if int(value) >= max_value:
                    badge.setStyleSheet(
                        self._point_badge_style("rgba(103, 232, 249, 30)", tier, tier)
                    )
                else:
                    badge.setStyleSheet(self._point_badge_style("#111827", tier, "#1f2937"))
            else:
                badge.setStyleSheet(self._point_badge_style("#111827", "#e5e7eb"))
            badge.setToolTip(f"Raw: {raw_text}\nPoints: {int(value)}")

    def _point_badge_color(self, ratio: float) -> str:
        if ratio >= 0.85:
            return "#22c55e"
        if ratio >= 0.65:
            return "#84cc16"
        if ratio >= 0.45:
            return "#facc15"
        if ratio >= 0.25:
            return "#f97316"
        return "#ef4444"

    def _tier_color(self, ratio: float) -> str:
        # Requested progression from low to high:
        # white -> green -> dark blue -> violet -> yellow -> red -> light blue
        palette = [
            "#e5e7eb",
            "#22c55e",
            "#1d4ed8",
            "#a855f7",
            "#facc15",
            "#ef4444",
            "#67e8f9",
        ]
        idx = int(round(max(0.0, min(1.0, ratio)) * (len(palette) - 1)))
        return palette[idx]

    def _point_badge_style(
        self,
        background: str,
        text_color: str,
        border_color: str = "#1f2937",
    ) -> str:
        return (
            "QLabel {"
            f"background: {background};"
            f"color: {text_color};"
            f"border: 1px solid {border_color};"
            "border-radius: 10px;"
            "padding: 6px 8px;"
            "font-weight: 600;"
            "}"
        )

    def _sex_icon(self, sex: str | None) -> str:
        if not sex:
            return "•"
        lowered = sex.lower()
        if lowered == "male":
            return "♂"
        if lowered == "female":
            return "♀"
        return "•"

    def _render_mutation_cards(self, creatures: list[Creature]) -> None:
        layout = self._mutations_cards_layout
        while layout.count() > 1:
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if not creatures:
            empty = QtWidgets.QLabel("No mutations data available for this filter.")
            empty.setStyleSheet("color: #94a3b8;")
            layout.insertWidget(0, empty)
            return

        creatures = sorted(
            creatures,
            key=lambda c: c.mutations_maternal + c.mutations_paternal,
            reverse=True,
        )
        for creature in creatures[:10]:
            total = creature.mutations_maternal + creature.mutations_paternal
            card = QtWidgets.QFrame()
            card.setStyleSheet(
                "QFrame { background: #0f172a; border: 1px solid #1f2937; border-radius: 12px; }"
            )
            card.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding,
                QtWidgets.QSizePolicy.Minimum,
            )
            card_layout = QtWidgets.QHBoxLayout(card)
            title = QtWidgets.QLabel(f"{creature.name} ({creature.species})")
            title.setStyleSheet("color: #f8fafc; font-weight: 600;")
            counts = QtWidgets.QLabel(
                f"Maternal {creature.mutations_maternal} • "
                f"Paternal {creature.mutations_paternal} • Total {total}"
            )
            counts.setStyleSheet("color: #94a3b8;")
            card_layout.addWidget(title)
            card_layout.addStretch(1)
            card_layout.addWidget(
                self._build_mutation_bar(
                    creature.mutations_maternal,
                    creature.mutations_paternal,
                )
            )
            card_layout.addWidget(counts)
            layout.insertWidget(layout.count() - 1, card)

    def _find_creature_by_id(self, creature_id: int | None) -> Creature | None:
        if creature_id is None:
            return None
        for creature in self._creature_cache:
            if creature.id == creature_id:
                return creature
        return None

    def _find_creature_by_external_id(self, external_id: str | None) -> Creature | None:
        if not external_id:
            return None
        for creature in self._creature_cache:
            if creature.external_id == external_id:
                return creature
        return None

    def _build_mutation_bar(self, maternal: int, paternal: int) -> QtWidgets.QWidget:
        if maternal + paternal == 0:
            maternal = 1
            paternal = 0
            empty = True
        else:
            empty = False
        container = QtWidgets.QFrame()
        container.setFixedWidth(120)
        container.setFixedHeight(10)
        container.setStyleSheet("QFrame { background: #0f172a; border: 1px solid #1f2937; border-radius: 5px; }")
        layout = QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        maternal_bar = QtWidgets.QFrame()
        maternal_color = "#334155" if empty else "#f472b6"
        paternal_color = "#334155" if empty else "#60a5fa"
        maternal_bar.setStyleSheet(f"QFrame {{ background: {maternal_color}; border-radius: 4px; }}")
        paternal_bar = QtWidgets.QFrame()
        paternal_bar.setStyleSheet(f"QFrame {{ background: {paternal_color}; border-radius: 4px; }}")
        layout.addWidget(maternal_bar, maternal)
        layout.addWidget(paternal_bar, paternal)
        return container

    def _update_mutations_table(self) -> None:
        species = self._mutations_species_filter.currentText()
        creatures = [
            c
            for c in self._creature_cache
            if species == "All species" or self._display_species(c.species) == species
        ]
        self._render_mutation_cards(creatures)

    def _update_pedigree_view(self) -> None:
        species = self._pedigree_species_filter.currentText()
        candidates = self._pedigree_candidates(species)
        if not candidates:
            self._pedigree_tree.setVisible(False)
            self._pedigree_empty.setVisible(True)
            if self._pedigree_subject:
                self._pedigree_subject.setText("Select a creature")
            if self._pedigree_subject_meta:
                self._pedigree_subject_meta.setText("")
            self._set_pedigree_avatar(self._pedigree_subject_avatar, None)
            if self._pedigree_mother:
                self._pedigree_mother.setText("Unknown")
            if self._pedigree_mother_meta:
                self._pedigree_mother_meta.setText("")
            self._set_pedigree_avatar(self._pedigree_mother_avatar, None)
            if self._pedigree_father:
                self._pedigree_father.setText("Unknown")
            if self._pedigree_father_meta:
                self._pedigree_father_meta.setText("")
            self._set_pedigree_avatar(self._pedigree_father_avatar, None)
            return
        self._pedigree_tree.setVisible(True)
        self._pedigree_empty.setVisible(False)
        selected = self._pedigree_creature_picker.currentData()
        creature = selected if isinstance(selected, Creature) and selected in candidates else candidates[0]
        if self._pedigree_subject:
            self._pedigree_subject.setText(creature.name)
        if self._pedigree_subject_meta:
            self._pedigree_subject_meta.setText(
                f"{self._sex_icon(creature.sex)} {creature.sex} • L{creature.level} • {self._display_species(creature.species)}"
            )
        self._set_pedigree_avatar(self._pedigree_subject_avatar, creature)
        mother = self._find_creature_by_id(creature.mother_id) or self._find_creature_by_external_id(
            creature.mother_external_id
        )
        father = self._find_creature_by_id(creature.father_id) or self._find_creature_by_external_id(
            creature.father_external_id
        )
        if self._pedigree_mother:
            self._pedigree_mother.setText(mother.name if mother else "Unknown")
        if self._pedigree_mother_meta:
            if mother:
                self._pedigree_mother_meta.setText(
                    f"{self._sex_icon(mother.sex)} {mother.sex} • L{mother.level} • {self._display_species(mother.species)}"
                )
            else:
                self._pedigree_mother_meta.setText("")
        self._set_pedigree_avatar(self._pedigree_mother_avatar, mother)
        if self._pedigree_father:
            self._pedigree_father.setText(father.name if father else "Unknown")
        if self._pedigree_father_meta:
            if father:
                self._pedigree_father_meta.setText(
                    f"{self._sex_icon(father.sex)} {father.sex} • L{father.level} • {self._display_species(father.species)}"
                )
            else:
                self._pedigree_father_meta.setText("")
        self._set_pedigree_avatar(self._pedigree_father_avatar, father)

    def _set_pedigree_avatar(self, label: QtWidgets.QLabel | None, creature: Creature | None) -> None:
        if label is None:
            return
        label.setPixmap(QtGui.QPixmap())
        if creature is None:
            label.setText("?")
            return
        avatar = self._small_species_image(self._display_species(creature.species), size=60)
        pixmap = avatar.pixmap()
        if pixmap and not pixmap.isNull():
            label.setPixmap(pixmap)
            label.setText("")
        else:
            label.setText(self._display_species(creature.species)[:1].upper())

    def _set_table_item(self, row: int, col: int, value: str, external_id: str | None = None) -> None:
        item = QtWidgets.QTableWidgetItem(value)
        item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
        if external_id:
            item.setData(QtCore.Qt.UserRole, external_id)
        self._creatures_table.setItem(row, col, item)

    def _format_stat(
        self,
        value: float | None,
        key: str | None = None,
        creature: Creature | None = None,
    ) -> str:
        if key == "MovementSpeed" and value is None:
            return "100.0%"
        if value is None:
            return "-"
        if key == "MeleeDamageMultiplier":
            return f"{(value + 1.0) * 100:.1f}%"
        if key == "MovementSpeed":
            if creature is not None and self._is_flying_creature(creature):
                return "100.0%"
            return f"{(value + 1.0) * 100:.1f}%"
        precision = 3 if key in {"MeleeDamageMultiplier", "MovementSpeed"} else 2
        return QtCore.QLocale.system().toString(float(value), "f", precision)

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
        item = self._creatures_table.item(row, 0)
        target_id = item.data(QtCore.Qt.UserRole) if item else None
        creature = None
        if target_id:
            for candidate in self._creature_cache:
                if candidate.external_id == target_id:
                    creature = candidate
                    break
        if creature is None:
            if row < 0 or row >= len(self._creature_rows):
                return
            creature = self._creature_rows[row]
        self._selected_creature = creature
        self._update_creature_detail(creature)

    def _update_creature_detail(self, creature: Creature) -> None:
        self._detail_title.setText(creature.name or "Unknown")
        subtitle = f"{self._display_species(creature.species)} • {creature.sex} • L{creature.level}"
        self._detail_subtitle.setText(subtitle)
        self._detail_image.set_species(self._display_species(creature.species))

        species_group = [
            c
            for c in self._creature_cache
            if self._display_species(c.species) == self._display_species(creature.species)
        ]
        use_points = self._points_available(species_group)
        self._update_point_badges(creature, species_group)
        radar_axes = [
            ("Health", "Health"),
            ("Stamina", "Stamina"),
            ("Oxygen", "Oxygen"),
            ("Food", "Food"),
            ("Weight", "Weight"),
            ("Melee", "MeleeDamageMultiplier"),
            ("Speed", "MovementSpeed"),
        ]
        max_values = {
            label: max(
                (self._get_stat_value(c, key, use_points=use_points) for c in species_group),
                default=0.0,
            )
            for label, key in radar_axes
        }
        values = {
            label: self._get_stat_value(creature, key, use_points=use_points)
            for label, key in radar_axes
        }
        radar_max = {label: max_values.get(label, 1.0) for label, _key in radar_axes}
        self._detail_radar.set_values(values, radar_max)

        for key, label in self._detail_stat_values.items():
            raw_value = creature.stats.get(key)
            label.setText(self._format_stat(raw_value, key, creature=creature))
            label.setToolTip("")

        strengths, weaknesses = self._compute_strengths_weaknesses(
            creature,
            species_group,
            use_points=use_points,
        )
        if len(species_group) <= 1:
            self._detail_strengths.setText("Strengths: Add more of this species for comparison.")
            self._detail_weaknesses.setText("Weaknesses: Add more of this species for comparison.")
            return

        self._detail_strengths.setText(
            "Strengths: "
            + (
                self._render_stat_badges(strengths, "#22c55e")
                if strengths
                else "No standout strengths."
            )
        )
        self._detail_weaknesses.setText(
            "Weaknesses: "
            + (
                self._render_stat_badges(weaknesses, "#ef4444")
                if weaknesses
                else "No clear weaknesses."
            )
        )

    def _compute_strengths_weaknesses(
        self,
        creature: Creature,
        species_group: list[Creature],
        use_points: bool = False,
    ) -> tuple[list[str], list[str]]:
        strengths: list[str] = []
        weaknesses: list[str] = []
        stat_map = [(short, key) for short, key, _title in _POINT_STAT_CONFIG]

        if len(species_group) <= 1:
            return [short for short, _key in stat_map], []

        for short, key in stat_map:
            values = [self._get_stat_value(c, key, use_points=use_points) for c in species_group]
            if not values:
                continue
            current = self._get_stat_value(creature, key, use_points=use_points)
            max_value = max(values)
            min_value = min(values)
            if abs(current - max_value) < 1e-6:
                strengths.append(short)
            if abs(current - min_value) < 1e-6 and abs(max_value - min_value) > 1e-6:
                weaknesses.append(short)
        return strengths, weaknesses

    def _render_stat_badges(self, labels: list[str], color: str) -> str:
        badges = []
        for label in labels:
            icon_path = self._stat_badge_icon_path(label, color)
            badges.append(f"<img src=\"{icon_path.as_posix()}\" width=\"24\" height=\"24\" />")
        return "&nbsp;".join(badges)

    def _stat_badge_icon_path(self, label: str, color: str) -> Path:
        safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "_", label).lower() or "x"
        safe_color = re.sub(r"[^a-zA-Z0-9]+", "", color).lower() or "default"
        cache_dir = user_data_dir() / "cache" / "badges"
        cache_dir.mkdir(parents=True, exist_ok=True)
        target = cache_dir / f"{safe_label}_{safe_color}_v3.png"
        if target.exists():
            return target

        pixmap = QtGui.QPixmap(96, 96)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtCore.Qt.NoPen)
        fill = QtGui.QColor(color)
        painter.setBrush(fill)
        diamond = QtGui.QPolygonF(
            [
                QtCore.QPointF(48, 6),
                QtCore.QPointF(90, 48),
                QtCore.QPointF(48, 90),
                QtCore.QPointF(6, 48),
            ]
        )
        painter.drawPolygon(diamond)
        text_color = QtGui.QColor("#0b1220")
        painter.setPen(text_color)
        font = painter.font()
        font.setBold(True)
        font.setPointSize(34)
        painter.setFont(font)
        painter.drawText(QtCore.QRectF(0, 0, 96, 96), QtCore.Qt.AlignCenter, label[:1].upper())
        painter.end()
        pixmap.save(str(target))
        return target

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
        if hasattr(self, "_last_import_label"):
            stamp = QtCore.QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
            self._last_import_label.setText(f"Last import: {stamp}")

    def _load_server_settings(self) -> None:
        self._server_settings = get_server_settings(self._conn)
        self._stat_multipliers = extract_stat_multipliers(self._server_settings)
        self._update_settings_view()

    def _update_settings_view(self) -> None:
        if not self._server_settings:
            self._settings_summary.setText("Using official defaults (x1).")
            self._settings_details.setText("Stat calculation: official defaults.")
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

        calc_lines = self._calc_multiplier_lines()
        detail_lines.append("")
        detail_lines.extend(calc_lines)

        self._settings_summary.setText("Server settings loaded.")
        self._settings_details.setText("\n".join(summary_lines + detail_lines))

    def _calc_multiplier_lines(self) -> list[str]:
        multipliers = self._stat_multipliers
        if not multipliers:
            return ["Stat calculation: official defaults."]

        non_default_count = 0
        lines = ["Stat calculation inputs:"]
        if abs(float(multipliers.imprinting) - 1.0) > 0.0001:
            non_default_count += 1
        lines.append(f"- Imprinting scale: x{self._fmt_multiplier(multipliers.imprinting)}")

        for short, key, title in _POINT_STAT_CONFIG:
            idx = _STAT_INDEX_BY_POINT_KEY.get(key)
            if idx is None:
                continue
            wild = float(multipliers.wild.get(idx, 1.0))
            tamed = float(multipliers.tamed.get(idx, 1.0))
            add = float(multipliers.tamed_add.get(idx, 1.0))
            affinity = float(multipliers.tamed_affinity.get(idx, 1.0))
            is_custom = any(abs(value - 1.0) > 0.0001 for value in (wild, tamed, add, affinity))
            if is_custom:
                non_default_count += 1
            if not is_custom:
                continue
            lines.append(
                f"- {short} {title}: "
                f"Wild x{self._fmt_multiplier(wild)}, "
                f"Tamed x{self._fmt_multiplier(tamed)}, "
                f"Add x{self._fmt_multiplier(add)}, "
                f"Affinity x{self._fmt_multiplier(affinity)}"
            )

        if len(lines) == 2 and non_default_count == 0:
            lines.append("- All tracked stat multipliers are at official defaults (x1).")
        lines.insert(1, f"- Non-default inputs detected: {non_default_count}")
        return lines

    def _fmt_multiplier(self, value: float) -> str:
        formatted = f"{value:.4f}".rstrip("0").rstrip(".")
        return formatted or "0"

    def _load_species_values(self) -> None:
        self._values_store = SpeciesValuesStore()
        self._values_from_bundle = False
        self._values_path = get_setting(self._conn, "values_json_path")
        loaded = False
        if self._values_path:
            custom_path = Path(self._values_path)
            if custom_path.exists():
                try:
                    self._values_store.load_values_file(custom_path)
                    loaded = self._values_store.count() > 0
                except Exception:
                    logger.exception("Failed to load values.json from %s", custom_path)
        if not loaded:
            default_path = bundled_values_path()
            if default_path.exists():
                try:
                    self._values_store.load_values_file(default_path)
                    loaded = self._values_store.count() > 0
                except Exception:
                    logger.exception("Failed to load bundled values from %s", default_path)
                if loaded:
                    self._values_from_bundle = True
                    self._values_path = str(default_path)
        self._update_values_view()
        self._update_points_info_labels()
        self._recompute_stat_points()

    def _update_values_view(self) -> None:
        count = self._values_store.count()
        if count == 0:
            self._values_summary.setText("No values.json loaded.")
            self._values_details.setText("")
            return
        source = self._values_path or "unknown path"
        if self._values_from_bundle:
            self._values_summary.setText(f"Loaded {count} built-in species values.")
            self._values_details.setText(
                "Source: bundled defaults (import your own values.json to override)."
            )
            return
        self._values_summary.setText(f"Loaded {count} species values.")
        self._values_details.setText(f"Source: {source}")

    def _import_game_user_settings(self) -> None:
        path = self._select_ini_file("Select GameUserSettings.ini")
        if not path:
            return
        parsed = parse_ini_file(Path(path))
        if not self._is_valid_game_user_settings_ini(parsed, path):
            self.show_toast("Fichier non conforme (GameUserSettings.ini attendu).", "error")
            return
        payload = self._ensure_server_settings_payload()
        payload["game_user_settings"] = parsed
        payload["sources"]["game_user_settings"] = path
        self._save_server_settings(payload, "GameUserSettings.ini imported.")

    def _import_game_ini(self) -> None:
        path = self._select_ini_file("Select Game.ini")
        if not path:
            return
        parsed = parse_ini_file(Path(path))
        if not self._is_valid_game_ini(parsed, path):
            self.show_toast("Fichier non conforme (Game.ini attendu).", "error")
            return
        payload = self._ensure_server_settings_payload()
        payload["game_ini"] = parsed
        payload["sources"]["game_ini"] = path
        self._save_server_settings(payload, "Game.ini imported.")

    def _is_valid_game_user_settings_ini(self, data: dict[str, dict[str, str]], _path: str) -> bool:
        if not data:
            return False
        sections = [section.lower() for section in data.keys()]
        known_sections = ("serversettings", "shootergameusersettings")
        if any(any(token in section for token in known_sections) for section in sections):
            return True

        known_keys = {
            "sessionname",
            "serverpassword",
            "serveradminpassword",
            "difficultyoffset",
            "xpmultiplier",
            "tamingspeedmultiplier",
            "harvestamountmultiplier",
            "allowflyerspeedleveling",
        }
        keys = {
            key.strip().lower()
            for section in data.values()
            for key in section.keys()
            if isinstance(key, str)
        }
        return any(key in known_keys for key in keys)

    def _is_valid_game_ini(self, data: dict[str, dict[str, str]], _path: str) -> bool:
        if not data:
            return False
        sections = [section.lower() for section in data.keys()]
        known_sections = ("shootergamemode", "shootergame")
        if any(any(token in section for token in known_sections) for section in sections):
            return True

        keys = {
            key.strip().lower()
            for section in data.values()
            for key in section.keys()
            if isinstance(key, str)
        }
        return any(
            key.startswith("perlevelstatsmultiplier_")
            or key.startswith("babyimprintingstatscale")
            or key.startswith("matingintervalmultiplier")
            or key.startswith("ballowspeedleveling")
            for key in keys
        )

    def _import_values_json(self) -> None:
        path = self._select_values_file("Select values.json")
        if not path:
            return
        store = SpeciesValuesStore()
        try:
            store.load_values_file(Path(path))
        except Exception:
            logger.exception("Failed to load values.json from %s", path)
            self.show_toast("Failed to import values.json.", "error")
            return
        if store.count() == 0:
            self.show_toast("values.json did not contain species data.", "error")
            return
        self._values_store = store
        self._values_path = path
        self._values_from_bundle = False
        set_setting(self._conn, "values_json_path", path)
        self._update_values_view()
        self._update_points_info_labels()
        self._recompute_stat_points()
        self.refresh_data()
        self.show_toast("values.json imported.", "success")

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

    def _select_values_file(self, title: str) -> str | None:
        start_dir = str(Path.home())
        selected, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            title,
            start_dir,
            "JSON files (*.json);;All files (*)",
        )
        if not selected:
            self.show_toast("No values.json selected.", "info")
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
        self._stat_multipliers = extract_stat_multipliers(self._server_settings)
        self._update_settings_view()
        self._recompute_stat_points()
        self.refresh_data()
        self.show_toast(message, "success")

    def show_toast(self, message: str, kind: str = "info") -> None:
        toast = ToastNotification(self, message=message, kind=kind, duration_ms=5000)
        self._toasts.append(toast)

        def _cleanup(_=None) -> None:
            if toast in self._toasts:
                self._toasts.remove(toast)

        toast.destroyed.connect(_cleanup)
        toast.show_at_bottom_right()
