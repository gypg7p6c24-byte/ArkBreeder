from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable

from PySide6 import QtCore, QtGui, QtWidgets

from arkbreedingtool.config import bundled_values_path, user_data_dir
from arkbreedingtool.core.parser import parse_creature_file
from arkbreedingtool.core.server_settings import parse_ini_file
from arkbreedingtool.core.species_values import SpeciesValuesStore
from arkbreedingtool.core.stats import StatMultipliers, compute_wild_levels, extract_stat_multipliers
from arkbreedingtool.storage.models import Creature
from arkbreedingtool.storage.repository import delete_creature, list_creatures
from arkbreedingtool.storage.settings import (
    get_server_settings,
    get_setting,
    set_server_settings,
    set_setting,
)
from arkbreedingtool.ui.dashboard_charts import BarChartWidget, DonutChartWidget
from arkbreedingtool.ui.radar_chart import RadarChart
from arkbreedingtool.ui.species_image import SpeciesImageWidget
from arkbreedingtool.ui.toast import ToastNotification

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

_DETAIL_POINT_STAT_CONFIG: list[tuple[str, str, str]] = [
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
        self.setWindowTitle("Ark Breeding Tool")
        self.setMinimumSize(1240, 760)
        self._conn = conn
        self._export_dir = export_dir
        self._import_service = None
        self._toasts: list[ToastNotification] = []
        self._server_settings: dict | None = None
        self._values_store = SpeciesValuesStore()
        self._values_path: str | None = None
        self._values_from_bundle = False
        self._manual_max_level_input: QtWidgets.QSpinBox | None = None
        self._manual_override_difficulty_input: QtWidgets.QDoubleSpinBox | None = None
        self._manual_difficulty_offset_input: QtWidgets.QDoubleSpinBox | None = None
        self._manual_imprint_input: QtWidgets.QDoubleSpinBox | None = None
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
        hero_title = QtWidgets.QLabel("Welcome to Ark Breeding Tool")
        hero_title.setStyleSheet("font-size: 21px; font-weight: 700; color: #f8fafc;")
        hero_layout.addWidget(hero_title)

        charts = QtWidgets.QHBoxLayout()
        charts.setSpacing(8)

        left = QtWidgets.QFrame()
        left.setObjectName("dashboardTile")
        left.setStyleSheet(
            "#dashboardTile { background: rgba(15, 23, 42, 0.44); border: 1px solid #334155; border-radius: 16px; }"
        )
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
        right.setObjectName("dashboardTile")
        right.setStyleSheet(
            "#dashboardTile { background: rgba(15, 23, 42, 0.44); border: 1px solid #334155; border-radius: 16px; }"
        )
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

        mutation_panel, self._dashboard_mutation_layout = self._dashboard_panel("Mutation pressure")
        self._mutation_bar = BarChartWidget()
        self._dashboard_mutation_layout.addWidget(self._mutation_bar, 1)

        points_panel, self._dashboard_points_layout = self._dashboard_panel("Best stat points")

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
        panel.setObjectName("dashboardPanel")
        panel.setStyleSheet(
            "#dashboardPanel { background: rgba(15, 23, 42, 0.44); border: 1px solid #334155; border-radius: 16px; }"
        )
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
        toolbar.addStretch(1)
        left_layout.addLayout(toolbar)

        self._creatures_table = QtWidgets.QTableWidget(0, 8)
        self._creatures_table.setHorizontalHeaderLabels(
            [
                "Name",
                "Species",
                "Level",
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
            QTableWidget {
                background: rgba(30, 41, 59, 0.75);
                border: none;
                border-radius: 9px;
                gridline-color: transparent;
            }
            QTableWidget::item { padding: 6px; border-bottom: 1px solid rgba(148, 163, 184, 0.18); }
            QTableWidget::item:selected { background: #1f2937; color: #f8fafc; }
            QHeaderView {
                background: transparent;
                border: none;
            }
            QHeaderView::section {
                background: rgba(30, 41, 59, 0.75);
                border: none;
                border-bottom: 1px solid #334155;
                color: #dbeafe;
                padding: 6px 8px;
                font-weight: 700;
            }
            QHeaderView::section:first {
                border-top-left-radius: 9px;
            }
            QHeaderView::section:last {
                border-top-right-radius: 9px;
            }
            QTableCornerButton::section {
                background: rgba(30, 41, 59, 0.75);
                border: none;
                border-bottom: 1px solid #334155;
                border-top-left-radius: 9px;
            }
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
        header.setSortIndicatorShown(False)
        self._creatures_table.setCornerButtonEnabled(False)
        self._creatures_table.itemSelectionChanged.connect(self._on_creature_selected)

        table_shell = QtWidgets.QFrame()
        table_shell.setObjectName("creaturesTableShell")
        table_shell.setStyleSheet(
            "#creaturesTableShell {"
            "background: rgba(30, 41, 59, 0.75);"
            "border: 1px solid #334155;"
            "border-radius: 10px;"
            "}"
        )
        table_shell_layout = QtWidgets.QVBoxLayout(table_shell)
        table_shell_layout.setContentsMargins(1, 1, 1, 1)
        table_shell_layout.setSpacing(0)
        table_shell_layout.addWidget(self._creatures_table)
        left_layout.addWidget(table_shell)

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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        layout.setAlignment(QtCore.Qt.AlignTop)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(4)
        self._breeding_back_btn = QtWidgets.QPushButton("← Back to overview")
        self._breeding_back_btn.clicked.connect(lambda: self._open_breeding_species_plan("All species"))
        self._breeding_back_btn.setVisible(False)
        toolbar.addWidget(self._breeding_back_btn)

        self._breeding_scope_label = QtWidgets.QLabel("Overview")
        self._breeding_scope_label.setStyleSheet("color: #e2e8f0; font-size: 23px; font-weight: 900;")
        toolbar.addWidget(self._breeding_scope_label)

        self._breeding_species_filter = QtWidgets.QComboBox()
        self._breeding_species_filter.currentIndexChanged.connect(self._update_breeding_pairs)
        self._breeding_species_filter.setVisible(False)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self._breeding_points_info = QtWidgets.QLabel(
            "Stat points unavailable — species reference values are missing."
        )
        self._breeding_points_info.setStyleSheet("color: #fbbf24;")
        self._breeding_points_info.setWordWrap(True)
        layout.addWidget(self._breeding_points_info)

        self._breeding_overview_panel = QtWidgets.QFrame()
        self._breeding_overview_panel.setObjectName("breedingOverviewPanel")
        self._breeding_overview_panel.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Maximum,
        )
        self._breeding_overview_panel.setStyleSheet(
            """
            #breedingOverviewPanel {
                background: transparent;
                border: none;
            }
            """
        )
        overview_layout = QtWidgets.QVBoxLayout(self._breeding_overview_panel)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        overview_layout.setSpacing(1)
        overview_layout.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        overview_title = QtWidgets.QLabel("Breeding actions overview")
        overview_title.setStyleSheet("color: #cbd5f5; font-size: 34px; font-weight: 900;")
        overview_layout.addWidget(overview_title)
        self._breeding_overview_grid = QtWidgets.QGridLayout()
        self._breeding_overview_grid.setContentsMargins(0, 0, 0, 0)
        self._breeding_overview_grid.setHorizontalSpacing(8)
        self._breeding_overview_grid.setVerticalSpacing(2)
        self._breeding_overview_grid.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        overview_layout.addLayout(self._breeding_overview_grid)
        self._breeding_overview_panel.setVisible(False)
        layout.addWidget(self._breeding_overview_panel)

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
        self._breeding_cards_scroll = scroll
        layout.addWidget(scroll)
        return widget

    def _build_creature_detail_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QFrame()
        self._detail_panel = panel
        panel.setObjectName("detailPanel")
        panel.setMinimumWidth(360)
        panel.setStyleSheet(
            """
            #detailPanel {
                background: rgba(15, 23, 42, 0.44);
                border: 1px solid rgba(148, 163, 184, 0.25);
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

        self._detail_rank_note = QtWidgets.QLabel("")
        self._detail_rank_note.setStyleSheet("color: #93c5fd; font-size: 12px; font-weight: 600;")
        self._detail_rank_note.setWordWrap(True)
        layout.addWidget(self._detail_rank_note)

        self._detail_crown = QtWidgets.QLabel("♛")
        self._detail_crown.setStyleSheet(
            "color: rgba(103, 232, 249, 0.96);"
            "font-size: 86px;"
            "font-weight: 800;"
            "padding: 0px 2px 0px 2px;"
            "background: rgba(11, 19, 36, 0.42);"
            "border: 1px solid rgba(103, 232, 249, 0.35);"
            "border-radius: 18px;"
        )
        self._detail_crown.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignRight)
        self._detail_crown.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self._detail_crown.setParent(panel)
        self._detail_crown.raise_()
        self._detail_crown.setVisible(False)
        panel.installEventFilter(self)

        self._detail_image = SpeciesImageWidget()
        self._detail_image.setStyleSheet("border: none;")
        layout.addWidget(self._detail_image, alignment=QtCore.Qt.AlignCenter)

        self._detail_radar = RadarChart(
            ["Health", "Stamina", "Oxygen", "Food", "Weight", "Melee", "Speed"]
        )
        layout.addWidget(self._detail_radar)

        self._detail_point_badges: dict[str, QtWidgets.QLabel] = {}
        points_row = QtWidgets.QHBoxLayout()
        points_row.setContentsMargins(0, 0, 0, 0)
        points_row.setSpacing(6)
        points_row.addStretch(1)
        for label, key, _title in _DETAIL_POINT_STAT_CONFIG:
            badge = self._make_point_badge(label)
            self._detail_point_badges[key] = badge
            points_row.addWidget(badge)
        points_row.addStretch(1)
        layout.addLayout(points_row)

        self._detail_stat_values: dict[str, QtWidgets.QLabel] = {}
        stat_rows = QtWidgets.QVBoxLayout()
        stat_rows.setSpacing(4)
        for _short, key, label in _POINT_STAT_CONFIG:
            row_widget = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)
            name_label = QtWidgets.QLabel(f"{label}:")
            name_label.setStyleSheet("color: #cbd5f5; font-size: 12px; font-weight: 600;")
            name_label.setMinimumWidth(74)
            name_label.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
            value_label = QtWidgets.QLabel("-")
            value_label.setStyleSheet("color: #f8fafc; font-weight: 600; font-family: 'DejaVu Sans Mono';")
            value_label.setMinimumWidth(96)
            value_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            value_label.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
            self._detail_stat_values[key] = value_label
            row_layout.addWidget(name_label)
            row_layout.addStretch(1)
            row_layout.addWidget(value_label)
            stat_rows.addWidget(row_widget)
        stat_rows.addStretch(1)
        stats_container = QtWidgets.QWidget()
        stats_container.setLayout(stat_rows)

        insights_card = QtWidgets.QWidget()
        insights_layout = QtWidgets.QVBoxLayout(insights_card)
        insights_layout.setContentsMargins(6, 0, 0, 0)
        insights_layout.setSpacing(4)
        insights_title = QtWidgets.QLabel("Breeding insights")
        insights_title.setStyleSheet("color: #93c5fd; font-size: 12px; font-weight: 700;")
        self._detail_insights = QtWidgets.QLabel("Select a creature to see insights.")
        self._detail_insights.setStyleSheet("color: #cbd5f5; font-size: 11px;")
        self._detail_insights.setTextFormat(QtCore.Qt.RichText)
        self._detail_insights.setWordWrap(True)
        insights_layout.addWidget(insights_title)
        insights_layout.addWidget(self._detail_insights)
        insights_layout.addStretch(1)

        stats_insights_row = QtWidgets.QHBoxLayout()
        stats_insights_row.setContentsMargins(0, 0, 0, 0)
        stats_insights_row.setSpacing(6)
        stats_container.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        insights_card.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        stats_insights_row.addWidget(stats_container, 1)
        separator = QtWidgets.QFrame()
        separator.setFixedWidth(1)
        separator.setStyleSheet("QFrame { background: #334155; border-radius: 0px; }")
        stats_insights_row.addWidget(separator)
        stats_insights_row.addWidget(insights_card, 1)
        stats_insights_row.setStretch(0, 1)
        stats_insights_row.setStretch(2, 1)
        layout.addLayout(stats_insights_row)

        self._points_info = QtWidgets.QLabel(
            "Stat points unavailable — species reference values are missing."
        )
        self._points_info.setStyleSheet("color: #fbbf24;")
        self._points_info.setWordWrap(True)
        layout.addWidget(self._points_info)

        self._detail_strengths = QtWidgets.QLabel("Strengths: -")
        self._detail_strengths.setStyleSheet("color: #67e8f9; font-size: 16px; font-weight: 700;")
        self._detail_strengths.setTextFormat(QtCore.Qt.RichText)
        self._detail_strengths.setWordWrap(True)
        layout.addWidget(self._detail_strengths)

        self._detail_weaknesses = QtWidgets.QLabel("Weaknesses: -")
        self._detail_weaknesses.setStyleSheet("color: #fecaca; font-size: 16px; font-weight: 700;")
        self._detail_weaknesses.setTextFormat(QtCore.Qt.RichText)
        self._detail_weaknesses.setWordWrap(True)
        layout.addWidget(self._detail_weaknesses)

        self._detail_delete_btn = QtWidgets.QPushButton("Delete creature")
        self._detail_delete_btn.setStyleSheet(
            "QPushButton { background: #7f1d1d; border: 1px solid #991b1b; color: #fee2e2; }"
            "QPushButton:hover { background: #991b1b; }"
        )
        self._detail_delete_btn.setEnabled(False)
        self._detail_delete_btn.clicked.connect(self._delete_selected_creature)
        layout.addWidget(self._detail_delete_btn, alignment=QtCore.Qt.AlignRight)

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

        manual_frame = QtWidgets.QFrame()
        manual_frame.setStyleSheet(
            "QFrame { background: rgba(15, 23, 42, 0.32); border: 1px solid #334155; border-radius: 10px; }"
        )
        manual_layout = QtWidgets.QVBoxLayout(manual_frame)
        manual_layout.setContentsMargins(12, 10, 12, 10)
        manual_layout.setSpacing(8)

        manual_header = QtWidgets.QLabel("Manual overrides")
        manual_header.setStyleSheet("font-size: 16px; font-weight: 700;")
        manual_layout.addWidget(manual_header)

        manual_helper = QtWidgets.QLabel(
            "Use this if imported INI values are missing or your server is custom."
        )
        manual_helper.setWordWrap(True)
        manual_helper.setStyleSheet("color: #cbd5f5;")
        manual_layout.addWidget(manual_helper)

        cap_row = QtWidgets.QHBoxLayout()
        cap_row.setSpacing(8)
        max_level_label = QtWidgets.QLabel("Max wild level cap")
        max_level_label.setStyleSheet("color: #cbd5f5;")
        cap_row.addWidget(max_level_label)
        max_level_spin = QtWidgets.QSpinBox()
        max_level_spin.setRange(0, 10000)
        max_level_spin.setValue(0)
        max_level_spin.setFixedWidth(120)
        max_level_spin.setStyleSheet(
            "QSpinBox { background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 4px; }"
        )
        self._manual_max_level_input = max_level_spin
        cap_row.addWidget(max_level_spin)
        cap_row.addStretch(1)
        manual_layout.addLayout(cap_row)

        difficulty_row = QtWidgets.QHBoxLayout()
        difficulty_row.setSpacing(8)
        override_label = QtWidgets.QLabel("OverrideOfficialDifficulty")
        override_label.setStyleSheet("color: #cbd5f5;")
        difficulty_row.addWidget(override_label)
        override_spin = QtWidgets.QDoubleSpinBox()
        override_spin.setDecimals(4)
        override_spin.setRange(0.0, 1000.0)
        override_spin.setSingleStep(0.1)
        override_spin.setValue(0.0)
        override_spin.setFixedWidth(120)
        override_spin.setStyleSheet(
            "QDoubleSpinBox { background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 4px; }"
        )
        self._manual_override_difficulty_input = override_spin
        difficulty_row.addWidget(override_spin)

        offset_label = QtWidgets.QLabel("DifficultyOffset")
        offset_label.setStyleSheet("color: #cbd5f5;")
        difficulty_row.addWidget(offset_label)
        offset_spin = QtWidgets.QDoubleSpinBox()
        offset_spin.setDecimals(4)
        offset_spin.setRange(0.0, 100.0)
        offset_spin.setSingleStep(0.05)
        offset_spin.setValue(0.0)
        offset_spin.setFixedWidth(110)
        offset_spin.setStyleSheet(
            "QDoubleSpinBox { background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 4px; }"
        )
        self._manual_difficulty_offset_input = offset_spin
        difficulty_row.addWidget(offset_spin)
        difficulty_row.addStretch(1)
        manual_layout.addLayout(difficulty_row)

        imprint_row = QtWidgets.QHBoxLayout()
        imprint_row.setSpacing(8)
        imprint_label = QtWidgets.QLabel("BabyImprintingStatScale")
        imprint_label.setStyleSheet("color: #cbd5f5;")
        imprint_row.addWidget(imprint_label)
        imprint_spin = QtWidgets.QDoubleSpinBox()
        imprint_spin.setDecimals(4)
        imprint_spin.setRange(0.0, 1000.0)
        imprint_spin.setSingleStep(0.05)
        imprint_spin.setValue(1.0)
        imprint_spin.setFixedWidth(120)
        imprint_spin.setStyleSheet(
            "QDoubleSpinBox { background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 4px; }"
        )
        self._manual_imprint_input = imprint_spin
        imprint_row.addWidget(imprint_spin)
        imprint_row.addStretch(1)
        manual_layout.addLayout(imprint_row)

        manual_hint = QtWidgets.QLabel(
            "Max wild level is used by the solver. 0 means auto-detect from imported INI."
        )
        manual_hint.setWordWrap(True)
        manual_hint.setStyleSheet("color: #94a3b8; font-size: 12px;")
        manual_layout.addWidget(manual_hint)

        manual_actions = QtWidgets.QHBoxLayout()
        self._manual_apply_btn = QtWidgets.QPushButton("Apply manual overrides")
        self._manual_apply_btn.clicked.connect(self._apply_manual_overrides)
        manual_actions.addWidget(self._manual_apply_btn)
        self._manual_reset_btn = QtWidgets.QPushButton("Reset overrides")
        self._manual_reset_btn.clicked.connect(self._reset_manual_overrides)
        manual_actions.addWidget(self._manual_reset_btn)
        manual_actions.addStretch(1)
        manual_layout.addLayout(manual_actions)

        layout.addWidget(manual_frame)

        self._settings_warning = QtWidgets.QLabel("")
        self._settings_warning.setWordWrap(True)
        self._settings_warning.setStyleSheet("color: #fbbf24;")
        layout.addWidget(self._settings_warning)

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
        self._recompute_stat_points()
        self._update_points_info_labels()
        self._update_settings_view()
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
            text.setStyleSheet("color: #cbd5f5; font-size: 12px; font-weight: 600;")
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
                self._empty_dashboard_label("Species reference values are missing, stat points disabled.")
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
            card = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(card)
            layout.setContentsMargins(2, 2, 2, 2)
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
            items.insert(0, "Species reference values missing: stat points are disabled.")

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
            self._breeding_points_info.setMaximumHeight(0 if has_values else 16777215)

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
            self._set_table_item(row, 2, str(creature.level))
            self._set_table_item(row, 3, self._format_stat(creature.stats.get("Health"), "Health"))
            self._set_table_item(row, 4, self._format_stat(creature.stats.get("Stamina"), "Stamina"))
            self._set_table_item(row, 5, self._format_stat(creature.stats.get("Weight"), "Weight"))
            self._set_table_item(
                row,
                6,
                self._format_stat(creature.stats.get("MeleeDamageMultiplier"), "MeleeDamageMultiplier"),
            )
            self._set_table_item(row, 7, self._format_updated_at(creature.updated_at))
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
        focus = "Overall"
        show_ranking = species != "All species"
        if hasattr(self, "_breeding_back_btn"):
            self._breeding_back_btn.setVisible(show_ranking)
        if hasattr(self, "_breeding_scope_label"):
            self._breeding_scope_label.setText(
                f"Detailed plan: {species}" if show_ranking else "Overview"
            )
        if hasattr(self, "_breeding_cards_scroll"):
            self._breeding_cards_scroll.setVisible(show_ranking)
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
        overview_items: list[dict[str, object]] = []
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

            plan_limit = min(30, len(all_pairs))
            plan_ranked_pairs = [
                (rank + 1, score, male, female)
                for rank, (score, male, female) in enumerate(all_pairs[:plan_limit])
            ]
            targets = self._species_target_points(group)
            sequence, pending = self._build_breeding_plan_sequence(
                plan_ranked_pairs,
                targets,
                use_points=use_points,
            )
            if plan_ranked_pairs:
                lead_male = plan_ranked_pairs[0][2]
                lead_female = plan_ranked_pairs[0][3]
                overview_items.append(
                    {
                        "species": species_name,
                        "score": plan_ranked_pairs[0][1],
                        "step_count": max(1, len(sequence)),
                        "pending": pending,
                        "lead_male_name": lead_male.name or "Male",
                        "lead_female_name": lead_female.name or "Female",
                        "next_action": (
                            f"{self._truncate_text(lead_male.name or 'Male', 10)} + "
                            f"{self._truncate_text(lead_female.name or 'Female', 10)}"
                        ),
                    }
                )
            limit = 1 if not show_ranking else plan_limit
            ranked_pairs = plan_ranked_pairs[:limit]
            rows.append((species_name, targets, ranked_pairs))

        rows.sort(key=lambda item: item[2][0][1] if item[2] else -1.0, reverse=True)
        overview_items.sort(
            key=lambda item: (
                int(item.get("pending") is not None and len(item.get("pending", [])) == 0),
                len(item.get("pending", [])),
                -float(item.get("score", 0.0)),
            ),
            reverse=True,
        )
        self._render_breeding_overview(
            overview_items,
            show_overview=(species == "All species"),
        )
        if not show_ranking:
            self._render_breeding_cards([], focus, use_points, show_ranking=False)
            return
        self._render_breeding_cards(rows, focus, use_points, show_ranking=show_ranking)

    def _render_breeding_overview(
        self,
        items: list[dict[str, object]],
        show_overview: bool,
    ) -> None:
        if not hasattr(self, "_breeding_overview_panel"):
            return
        self._breeding_overview_panel.setVisible(show_overview)
        grid = self._breeding_overview_grid
        self._clear_layout(grid)
        if not show_overview:
            return

        if not items:
            empty = QtWidgets.QLabel("No species with valid male/female pairs yet.")
            empty.setStyleSheet("color: #94a3b8;")
            grid.addWidget(empty, 0, 0)
            return

        columns = 1
        if len(items) >= 2:
            columns = 2
        if len(items) >= 7:
            columns = 3
        for idx, item in enumerate(items):
            species_name = str(item.get("species", "Unknown"))
            step_count = int(item.get("step_count", 1))
            pending = [
                str(value)
                for value in item.get("pending", [])
                if isinstance(value, str)
            ]
            next_action = str(item.get("next_action", ""))
            is_ready = len(pending) == 0
            status_color = "#67e8f9" if is_ready else "#fbbf24"
            lead_male_name = str(item.get("lead_male_name", "Male"))
            lead_female_name = str(item.get("lead_female_name", "Female"))
            lead_male = self._truncate_text(lead_male_name or "Male", 10)
            lead_female = self._truncate_text(lead_female_name or "Female", 10)

            card = QtWidgets.QWidget()
            card.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Maximum)
            card_layout = QtWidgets.QVBoxLayout(card)
            card_layout.setContentsMargins(2, 2, 2, 2)
            card_layout.setSpacing(3)

            plan_frame = QtWidgets.QFrame()
            plan_frame.setMinimumWidth(470)
            plan_frame.setStyleSheet(
                "QFrame {"
                "background: rgba(11, 19, 36, 0.28);"
                "border: 1px solid #334155;"
                "border-radius: 11px;"
                "}"
            )
            plan_layout = QtWidgets.QVBoxLayout(plan_frame)
            plan_layout.setContentsMargins(8, 7, 8, 7)
            plan_layout.setSpacing(4)

            title_row = QtWidgets.QHBoxLayout()
            title_row.setContentsMargins(0, 0, 0, 0)
            title_row.setSpacing(4)
            species_label = QtWidgets.QLabel(species_name)
            species_label.setStyleSheet(
                "color: #f8fafc; font-size: 16px; font-weight: 900;"
                "background: transparent; border: none;"
            )
            title_row.addWidget(species_label, alignment=QtCore.Qt.AlignLeft)
            title_row.addStretch(1)
            plan_layout.addLayout(title_row)

            pair_row = QtWidgets.QHBoxLayout()
            pair_row.setContentsMargins(1, 1, 1, 1)
            pair_row.setSpacing(5)
            pair_row.addWidget(
                self._overview_mini_breeder_card(
                    species_name,
                    lead_male,
                    "male",
                )
            )
            plus = QtWidgets.QLabel("+")
            plus.setStyleSheet(
                "color: #cbd5f5; font-size: 16px; font-weight: 800;"
                "background: transparent; border: none;"
            )
            plus.setAlignment(QtCore.Qt.AlignCenter)
            pair_row.addWidget(plus)
            pair_row.addWidget(
                self._overview_mini_breeder_card(
                    species_name,
                    lead_female,
                    "female",
                )
            )
            plan_layout.addLayout(pair_row)
            card_layout.addWidget(plan_frame)

            next_label = QtWidgets.QLabel(f"Next action: {next_action}")
            next_label.setStyleSheet("color: #cbd5f5; font-size: 12px; font-weight: 700;")
            card_layout.addWidget(next_label)

            steps_label = QtWidgets.QLabel(f"Estimated steps: {step_count}")
            steps_label.setStyleSheet("color: #93c5fd; font-size: 12px; font-weight: 600;")
            card_layout.addWidget(steps_label)

            if pending:
                pending_label = QtWidgets.QLabel(f"Missing: {', '.join(pending)}")
                pending_label.setStyleSheet("color: #fbbf24; font-size: 12px; font-weight: 600;")
            else:
                pending_label = QtWidgets.QLabel("All target stats currently coverable.")
                pending_label.setStyleSheet("color: #67e8f9; font-size: 12px; font-weight: 600;")
            pending_label.setWordWrap(True)
            card_layout.addWidget(pending_label)

            open_btn = QtWidgets.QPushButton("Open detailed plan")
            open_btn.setStyleSheet(
                "QPushButton { background: #1e293b; border: 1px solid #334155; color: #e2e8f0; }"
                "QPushButton:hover { background: #243247; }"
            )
            open_btn.clicked.connect(
                lambda _checked=False, sp=species_name: self._open_breeding_species_plan(sp)
            )
            card_layout.addWidget(open_btn, alignment=QtCore.Qt.AlignLeft)

            row = idx // columns
            col = idx % columns
            grid.addWidget(card, row, col)

    def _overview_mini_breeder_card(
        self,
        species_name: str,
        breeder_name: str,
        sex: str,
    ) -> QtWidgets.QWidget:
        border_color = "#60a5fa" if sex == "male" else "#f472b6"
        text_color = "#dbeafe" if sex == "male" else "#fce7f3"
        box = QtWidgets.QFrame()
        box.setMinimumWidth(132)
        box.setStyleSheet(
            "QFrame {"
            "background: rgba(15, 23, 42, 0.36);"
            f"border: 1px solid {border_color};"
            "border-radius: 8px;"
            "}"
        )
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)

        name = QtWidgets.QLabel(f"{self._sex_icon(sex)} {self._truncate_text(breeder_name, 10)}")
        name.setAlignment(QtCore.Qt.AlignCenter)
        name.setStyleSheet(
            f"color: {text_color}; font-size: 11px; font-weight: 700;"
            "background: transparent; border: none;"
        )
        layout.addWidget(name)

        avatar = self._overview_species_image(species_name, size=62)
        layout.addWidget(avatar, alignment=QtCore.Qt.AlignCenter)
        return box

    def _overview_species_image(self, species: str, size: int = 48) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel()
        label.setFixedSize(size, int(size * 0.75))
        label.setAlignment(QtCore.Qt.AlignCenter)
        label.setStyleSheet("background: transparent; border: none; color: #94a3b8;")
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

    def _open_breeding_species_plan(self, species: str) -> None:
        if not hasattr(self, "_breeding_species_filter"):
            return
        index = self._breeding_species_filter.findText(species)
        if index >= 0:
            if self._breeding_species_filter.currentIndex() == index:
                self._update_breeding_pairs()
                return
            self._breeding_species_filter.setCurrentIndex(index)

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

    def _breeding_creature_score(self, creature: Creature, use_points: bool = False) -> float:
        return sum(
            self._get_stat_value(creature, key, use_points=use_points, points_only=use_points)
            for _short, key, _title in _BREEDING_POINT_STAT_CONFIG
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
            row_layout.setSpacing(6)
            row_layout.setContentsMargins(0, 0, 0, 12)

            header = QtWidgets.QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            species_label = QtWidgets.QLabel(species_name)
            species_label.setStyleSheet("color: #cbd5f5; font-weight: 800; font-size: 16px;")
            header.addWidget(species_label)
            header.addStretch(1)
            row_layout.addLayout(header)

            if targets and show_ranking:
                compare_widget = self._build_breeding_target_compare(
                    species_name,
                    targets,
                    use_points=use_points,
                )
                if compare_widget is not None:
                    row_layout.addWidget(compare_widget)
            elif targets:
                target_row = QtWidgets.QHBoxLayout()
                target_row.setContentsMargins(0, 0, 0, 0)
                target_row.setSpacing(6)
                target_label = QtWidgets.QLabel("⦿ Target")
                target_label.setStyleSheet("color: #67e8f9; font-size: 14px; font-weight: 800;")
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

            max_stats = self._species_max_stats(species_name, use_points=use_points)
            male_candidates: dict[str, Creature] = {}
            female_candidates: dict[str, Creature] = {}
            for _rank, _score, male, female in ranked_pairs:
                male_key = male.external_id or f"male:{male.id}"
                female_key = female.external_id or f"female:{female.id}"
                male_candidates[male_key] = male
                female_candidates[female_key] = female

            best_male_key = None
            if male_candidates:
                best_male_key = max(
                    male_candidates.keys(),
                    key=lambda item: self._breeding_creature_score(
                        male_candidates[item],
                        use_points=use_points,
                    ),
                )
            best_female_key = None
            if female_candidates:
                best_female_key = max(
                    female_candidates.keys(),
                    key=lambda item: self._breeding_creature_score(
                        female_candidates[item],
                        use_points=use_points,
                    ),
                )

            if show_ranking:
                self._render_breeding_plan_chain(
                    row_layout,
                    ranked_pairs,
                    targets,
                    max_stats=max_stats,
                    use_points=use_points,
                    best_male_key=best_male_key,
                    best_female_key=best_female_key,
                )
                layout.addWidget(row_card, row_index, 0)
                row_index += 1
                continue

            for rank, _score, male, female in ranked_pairs:
                pair_layout = QtWidgets.QHBoxLayout()
                pair_layout.setSpacing(10)
                pair_layout.setContentsMargins(0, 0, 0, 0)
                if show_ranking:
                    pair_layout.addWidget(self._rank_badge(rank))
                male_key = male.external_id or f"male:{male.id}"
                female_key = female.external_id or f"female:{female.id}"
                male_box = self._pair_info_box(
                    male,
                    max_stats,
                    use_points=use_points,
                    points_only=True,
                    targets=targets,
                    highlighted=(best_male_key == male_key),
                )
                female_box = self._pair_info_box(
                    female,
                    max_stats,
                    use_points=use_points,
                    points_only=True,
                    targets=targets,
                    highlighted=(best_female_key == female_key),
                )
                child_box = self._pair_child_box(
                    male,
                    female,
                    max_stats,
                    targets,
                    use_points=use_points,
                )
                pair_layout.addWidget(male_box)
                plus = QtWidgets.QLabel("+")
                plus.setAlignment(QtCore.Qt.AlignCenter)
                plus.setFixedWidth(18)
                plus.setStyleSheet(
                    "color: #cbd5f5; font-size: 16px; font-weight: 700;"
                    "background: transparent; border: none;"
                )
                pair_layout.addWidget(plus)
                pair_layout.addWidget(female_box)
                arrow = QtWidgets.QLabel("⟶")
                arrow.setAlignment(QtCore.Qt.AlignCenter)
                arrow.setFixedWidth(28)
                arrow.setStyleSheet(
                    "color: #93c5fd; font-size: 20px; font-weight: 700;"
                    "background: transparent; border: none;"
                )
                pair_layout.addWidget(arrow)
                pair_layout.addWidget(child_box)
                pair_layout.addStretch(1)
                row_layout.addLayout(pair_layout)
            layout.addWidget(row_card, row_index, 0)
            row_index += 1

    def _build_breeding_target_compare(
        self,
        species_name: str,
        targets: list[tuple[str, int]],
        use_points: bool = False,
    ) -> QtWidgets.QWidget | None:
        if not targets:
            return None

        candidates = [
            creature
            for creature in self._creature_cache
            if self._display_species(creature.species) == species_name
        ]
        if not candidates:
            return None

        best_creature = max(
            candidates,
            key=lambda creature: self._breeding_creature_score(creature, use_points=use_points),
        )
        best_points = self._creature_breeding_points(best_creature, use_points=use_points)
        target_by_short = {short: float(value) for short, value in targets}

        axes = [title for _short, _key, title in _BREEDING_POINT_STAT_CONFIG]
        current_values: dict[str, float] = {}
        target_values: dict[str, float] = {}
        axis_max: dict[str, float] = {}
        for short, key, title in _BREEDING_POINT_STAT_CONFIG:
            current_value = float(best_points.get(key, 0.0))
            target_value = float(target_by_short.get(short, 0.0))
            current_values[title] = current_value
            target_values[title] = target_value
            axis_max[title] = max(current_value, target_value, 1.0)

        wrapper = QtWidgets.QWidget()
        wrapper_layout = QtWidgets.QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(6)

        title = QtWidgets.QLabel("Current best vs target")
        title.setStyleSheet(
            "color: #93c5fd; font-size: 14px; font-weight: 800;"
            "background: transparent; border: none;"
        )
        wrapper_layout.addWidget(title)

        charts_row = QtWidgets.QHBoxLayout()
        charts_row.setContentsMargins(0, 0, 0, 0)
        charts_row.setSpacing(10)

        current_col = QtWidgets.QVBoxLayout()
        current_col.setContentsMargins(0, 0, 0, 0)
        current_col.setSpacing(4)
        current_chart = RadarChart(axes)
        current_chart.setMinimumSize(180, 180)
        current_chart.setMaximumSize(220, 220)
        current_chart.set_values(current_values, axis_max)
        current_col.addWidget(current_chart, alignment=QtCore.Qt.AlignCenter)
        current_label = QtWidgets.QLabel(
            f"Current best: {self._sex_icon(best_creature.sex)} {self._truncate_text(best_creature.name or 'Unknown', 16)}"
        )
        current_label.setAlignment(QtCore.Qt.AlignCenter)
        current_label.setStyleSheet(
            "color: #cbd5f5; font-size: 11px; font-weight: 700;"
            "background: transparent; border: none;"
        )
        current_col.addWidget(current_label)
        current_badges = QtWidgets.QHBoxLayout()
        current_badges.setContentsMargins(0, 0, 0, 0)
        current_badges.setSpacing(4)
        current_badges.addStretch(1)
        for short, key, _title in _BREEDING_POINT_STAT_CONFIG:
            chip = QtWidgets.QLabel(f"{self._point_icon(short)} {int(round(best_points.get(key, 0.0)))}")
            chip.setStyleSheet(
                "color: #cbd5f5; font-size: 10px; font-weight: 700;"
                "border: none; background: transparent;"
            )
            current_badges.addWidget(chip)
        current_badges.addStretch(1)
        current_col.addLayout(current_badges)
        charts_row.addLayout(current_col, 1)

        target_col = QtWidgets.QVBoxLayout()
        target_col.setContentsMargins(0, 0, 0, 0)
        target_col.setSpacing(4)
        target_chart = RadarChart(axes)
        target_chart.setMinimumSize(180, 180)
        target_chart.setMaximumSize(220, 220)
        target_chart.set_values(target_values, axis_max)
        target_col.addWidget(target_chart, alignment=QtCore.Qt.AlignCenter)
        target_label = QtWidgets.QLabel("Target")
        target_label.setAlignment(QtCore.Qt.AlignCenter)
        target_label.setStyleSheet(
            "color: #67e8f9; font-size: 11px; font-weight: 800;"
            "background: transparent; border: none;"
        )
        target_col.addWidget(target_label)
        target_badges = QtWidgets.QHBoxLayout()
        target_badges.setContentsMargins(0, 0, 0, 0)
        target_badges.setSpacing(4)
        target_badges.addStretch(1)
        for short, value in targets:
            chip = QtWidgets.QLabel(f"{self._point_icon(short)} {value}")
            chip.setStyleSheet(
                "color: #67e8f9; font-size: 10px; font-weight: 700;"
                "border: none; background: transparent;"
            )
            target_badges.addWidget(chip)
        target_badges.addStretch(1)
        target_col.addLayout(target_badges)
        charts_row.addLayout(target_col, 1)

        wrapper_layout.addLayout(charts_row)

        return wrapper

    def _pair_info_box(
        self,
        creature: Creature,
        max_stats: dict[str, float],
        use_points: bool = False,
        points_only: bool = False,
        targets: list[tuple[str, int]] | None = None,
        highlighted: bool = False,
    ) -> QtWidgets.QWidget:
        sex_lower = creature.sex.lower() if creature.sex else ""
        accent = "#94a3b8"
        if sex_lower == "male":
            accent = "#60a5fa"
        elif sex_lower == "female":
            accent = "#f472b6"
        reached_target = bool(
            targets
            and self._is_target_reached(
                self._creature_breeding_points(creature, use_points=use_points),
                targets,
            )
        )
        box = QtWidgets.QFrame()
        box.setObjectName("pairCard")
        box.setMinimumWidth(168)
        box.setMaximumWidth(184)
        border_width = 2 if highlighted or reached_target else 1
        if reached_target:
            accent = "#67e8f9"
            box_bg = "rgba(103, 232, 249, 0.14)"
        elif not highlighted:
            box_bg = "rgba(11, 19, 36, 0.85)"
        elif sex_lower == "male":
            box_bg = "rgba(96, 165, 250, 0.14)"
        elif sex_lower == "female":
            box_bg = "rgba(244, 114, 182, 0.14)"
        else:
            box_bg = "rgba(11, 19, 36, 0.92)"
        box.setStyleSheet(
            "#pairCard {"
            f"background: {box_bg};"
            f"border: {border_width}px solid {accent};"
            "border-radius: 14px;"
            "}"
        )
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(2)
        title_row = QtWidgets.QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(4)
        display_name = self._truncate_text(creature.name or "Unknown", 10)
        title_text = f"{self._sex_icon(creature.sex)} {display_name}"
        name_label = QtWidgets.QLabel(title_text)
        name_label.setStyleSheet(
            f"color: {accent}; font-weight: 700; font-size: 13px; background: transparent; border: none;"
        )
        title_row.addWidget(name_label)
        title_row.addStretch(1)
        crown_label = QtWidgets.QLabel("♛")
        crown_label.setStyleSheet("color: #67e8f9; font-size: 18px; font-weight: 800;")
        crown_label.setVisible(reached_target)
        title_row.addWidget(crown_label, alignment=QtCore.Qt.AlignTop | QtCore.Qt.AlignRight)
        layout.addLayout(title_row)

        if highlighted or reached_target:
            glow = QtWidgets.QGraphicsDropShadowEffect(box)
            glow.setBlurRadius(28 if reached_target else 24)
            glow.setOffset(0, 0)
            color = QtGui.QColor(accent)
            color.setAlpha(235 if reached_target else 220)
            glow.setColor(color)
            box.setGraphicsEffect(glow)
        if reached_target:
            text_glow = QtWidgets.QGraphicsDropShadowEffect(name_label)
            text_glow.setBlurRadius(8)
            text_glow.setOffset(0, 0)
            text_glow.setColor(QtGui.QColor(255, 255, 255, 180))
            name_label.setGraphicsEffect(text_glow)
            crown_glow = QtWidgets.QGraphicsDropShadowEffect(crown_label)
            crown_glow.setBlurRadius(14)
            crown_glow.setOffset(0, 0)
            crown_glow.setColor(QtGui.QColor(103, 232, 249, 240))
            crown_label.setGraphicsEffect(crown_glow)

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
        targets: list[tuple[str, int]],
        use_points: bool = False,
        override_points: dict[str, float] | None = None,
        title_override: str | None = None,
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
        child_points = (
            dict(override_points)
            if override_points is not None
            else self._expected_child_points(male, female, use_points=use_points)
        )
        is_perfect = self._is_target_reached(child_points, targets)
        expected_title = title_override or "♂/♀ Expected"
        title_row = QtWidgets.QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(4)
        name_label = QtWidgets.QLabel(expected_title)
        name_label.setStyleSheet(
            "color: #cbd5f5; font-weight: 700; font-size: 13px; background: transparent; border: none;"
        )
        title_row.addWidget(name_label)
        title_row.addStretch(1)
        crown_label = QtWidgets.QLabel("♛")
        crown_label.setStyleSheet("color: #67e8f9; font-size: 18px; font-weight: 800;")
        crown_label.setVisible(is_perfect)
        title_row.addWidget(crown_label, alignment=QtCore.Qt.AlignTop | QtCore.Qt.AlignRight)
        layout.addLayout(title_row)
        species_label = self._display_species(male.species or female.species)
        avatar = self._small_species_image(species_label, size=100)
        layout.addWidget(avatar, alignment=QtCore.Qt.AlignCenter)

        if is_perfect:
            box.setStyleSheet(
                "#pairCardChild {"
                "background: rgba(103, 232, 249, 0.14);"
                "border: 2px solid #67e8f9;"
                "border-radius: 14px;"
                "}"
            )
            glow = QtWidgets.QGraphicsDropShadowEffect(box)
            glow.setBlurRadius(22)
            glow.setOffset(0, 0)
            glow.setColor(QtGui.QColor(103, 232, 249, 235))
            box.setGraphicsEffect(glow)
            text_glow = QtWidgets.QGraphicsDropShadowEffect(name_label)
            text_glow.setBlurRadius(8)
            text_glow.setOffset(0, 0)
            text_glow.setColor(QtGui.QColor(255, 255, 255, 170))
            name_label.setGraphicsEffect(text_glow)
            crown_glow = QtWidgets.QGraphicsDropShadowEffect(crown_label)
            crown_glow.setBlurRadius(14)
            crown_glow.setOffset(0, 0)
            crown_glow.setColor(QtGui.QColor(103, 232, 249, 240))
            crown_label.setGraphicsEffect(crown_glow)

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

    def _creature_breeding_points(self, creature: Creature, use_points: bool = False) -> dict[str, float]:
        return {
            key: float(self._get_stat_value(creature, key, use_points=use_points, points_only=use_points))
            for _short, key, _title in _BREEDING_POINT_STAT_CONFIG
        }

    def _is_target_reached(self, points: dict[str, float], targets: list[tuple[str, int]]) -> bool:
        if not targets:
            return False
        short_to_key = {short: key for short, key, _title in _BREEDING_POINT_STAT_CONFIG}
        for short, target in targets:
            key = short_to_key.get(short)
            if not key:
                continue
            if points.get(key, 0.0) + 0.001 < float(target):
                return False
        return True

    def _render_breeding_plan_chain(
        self,
        parent_layout: QtWidgets.QVBoxLayout,
        ranked_pairs: list[tuple[int, float, Creature, Creature]],
        targets: list[tuple[str, int]],
        max_stats: dict[str, float],
        use_points: bool = False,
        best_male_key: str | None = None,
        best_female_key: str | None = None,
    ) -> None:
        sequence, pending = self._build_breeding_plan_sequence(
            ranked_pairs,
            targets,
            use_points=use_points,
        )
        if not sequence:
            return

        chain_title = QtWidgets.QLabel("Breeding plan")
        chain_title.setStyleSheet("color: #93c5fd; font-size: 14px; font-weight: 800;")
        parent_layout.addWidget(chain_title)
        show_step_labels = len(sequence) > 1

        # Stage 1: explicit donor pairs per step.
        for idx, step_info in enumerate(sequence):
            step = int(step_info["step"])
            male = step_info["male"]
            female = step_info["female"]
            if not isinstance(male, Creature) or not isinstance(female, Creature):
                continue
            expected_points_raw = step_info.get("expected_points")
            if not isinstance(expected_points_raw, dict):
                continue
            expected_points = {
                key: float(value)
                for key, value in expected_points_raw.items()
                if isinstance(key, str)
            }

            if show_step_labels:
                step_label = QtWidgets.QLabel(f"Step {step}")
                step_label.setAlignment(QtCore.Qt.AlignCenter)
                step_label.setStyleSheet("color: #cbd5f5; font-size: 15px; font-weight: 800;")
                parent_layout.addWidget(step_label)

            step_box = QtWidgets.QFrame()
            step_box.setStyleSheet(
                "QFrame { background: rgba(15, 23, 42, 0.28); border: 1px solid #334155; border-radius: 12px; }"
            )
            step_box.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Maximum)
            step_layout = QtWidgets.QVBoxLayout(step_box)
            step_layout.setContentsMargins(8, 8, 8, 8)
            step_layout.setSpacing(0)

            pair_layout = QtWidgets.QHBoxLayout()
            pair_layout.setSpacing(12)
            pair_layout.setContentsMargins(0, 0, 0, 0)
            male_key = male.external_id or f"male:{male.id}"
            female_key = female.external_id or f"female:{female.id}"
            pair_layout.addWidget(
                self._pair_info_box(
                    male,
                    max_stats,
                    use_points=use_points,
                    points_only=True,
                    targets=targets,
                    highlighted=(best_male_key == male_key),
                )
            )
            plus = QtWidgets.QLabel("+")
            plus.setAlignment(QtCore.Qt.AlignCenter)
            plus.setFixedWidth(18)
            plus.setStyleSheet(
                "color: #cbd5f5; font-size: 16px; font-weight: 700;"
                "background: transparent; border: none;"
            )
            pair_layout.addWidget(plus)
            pair_layout.addWidget(
                self._pair_info_box(
                    female,
                    max_stats,
                    use_points=use_points,
                    points_only=True,
                    targets=targets,
                    highlighted=(best_female_key == female_key),
                )
            )
            arrow = QtWidgets.QLabel("⟶")
            arrow.setAlignment(QtCore.Qt.AlignCenter)
            arrow.setFixedWidth(28)
            arrow.setStyleSheet(
                "color: #93c5fd; font-size: 20px; font-weight: 700;"
                "background: transparent; border: none;"
            )
            pair_layout.addWidget(arrow)
            pair_layout.addWidget(
                self._pair_child_box(
                    male,
                    female,
                    max_stats,
                    targets,
                    use_points=use_points,
                    override_points=expected_points,
                    title_override=self._expected_child_title(step),
                )
            )
            step_layout.addLayout(pair_layout)

            parent_layout.addWidget(step_box, alignment=QtCore.Qt.AlignHCenter)
            if idx < len(sequence) - 1:
                parent_layout.addWidget(self._plan_down_arrow())

        # Stage 2: expected merge chain (E1 + E2 -> C2 -> ...).
        if len(sequence) >= 2:
            parent_layout.addWidget(self._plan_down_arrow())
            merge_title = QtWidgets.QLabel("Expected merge path")
            merge_title.setAlignment(QtCore.Qt.AlignCenter)
            merge_title.setStyleSheet("color: #93c5fd; font-size: 15px; font-weight: 800;")
            parent_layout.addWidget(merge_title)

            first_points_raw = sequence[0].get("merged_points")
            if not isinstance(first_points_raw, dict):
                first_points_raw = {}
            current_points = {
                key: float(value)
                for key, value in first_points_raw.items()
                if isinstance(key, str)
            }
            current_title = self._expected_child_title(1)

            for idx, step_info in enumerate(sequence[1:], start=2):
                male = step_info["male"]
                female = step_info["female"]
                if not isinstance(male, Creature) or not isinstance(female, Creature):
                    continue
                expected_points_raw = step_info.get("expected_points")
                merged_points_raw = step_info.get("merged_points")
                if not isinstance(expected_points_raw, dict) or not isinstance(merged_points_raw, dict):
                    continue
                expected_points = {
                    key: float(value)
                    for key, value in expected_points_raw.items()
                    if isinstance(key, str)
                }
                merged_points = {
                    key: float(value)
                    for key, value in merged_points_raw.items()
                    if isinstance(key, str)
                }
                merge_row = QtWidgets.QHBoxLayout()
                merge_row.setSpacing(12)
                merge_row.setContentsMargins(0, 0, 0, 0)
                merge_row.addWidget(
                    self._pair_child_box(
                        male,
                        female,
                        max_stats,
                        targets,
                        use_points=use_points,
                        override_points=current_points,
                        title_override=current_title,
                    )
                )
                plus_label = QtWidgets.QLabel("+")
                plus_label.setAlignment(QtCore.Qt.AlignCenter)
                plus_label.setFixedWidth(18)
                plus_label.setStyleSheet(
                    "color: #cbd5f5; font-size: 16px; font-weight: 700;"
                    "background: transparent; border: none;"
                )
                merge_row.addWidget(plus_label)
                merge_row.addWidget(
                    self._pair_child_box(
                        male,
                        female,
                        max_stats,
                        targets,
                        use_points=use_points,
                        override_points=expected_points,
                        title_override=self._expected_child_title(idx),
                    )
                )
                merge_arrow = QtWidgets.QLabel("⟶")
                merge_arrow.setAlignment(QtCore.Qt.AlignCenter)
                merge_arrow.setFixedWidth(28)
                merge_arrow.setStyleSheet(
                    "color: #93c5fd; font-size: 20px; font-weight: 700;"
                    "background: transparent; border: none;"
                )
                merge_row.addWidget(merge_arrow)
                merge_row.addWidget(
                    self._pair_child_box(
                        male,
                        female,
                        max_stats,
                        targets,
                        use_points=use_points,
                        override_points=merged_points,
                        title_override=self._combined_child_title(idx),
                    )
                )
                merge_container = QtWidgets.QWidget()
                merge_container.setLayout(merge_row)
                merge_container.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Maximum)
                parent_layout.addWidget(merge_container, alignment=QtCore.Qt.AlignHCenter)
                current_points = merged_points
                current_title = self._combined_child_title(idx)
                if idx < len(sequence):
                    parent_layout.addWidget(self._plan_down_arrow())

        if pending:
            pending_label = QtWidgets.QLabel(f"Missing target stats: {', '.join(pending)}")
            pending_label.setStyleSheet("color: #fbbf24; font-size: 11px; font-weight: 600;")
            parent_layout.addWidget(pending_label)
        else:
            complete_label = QtWidgets.QLabel("Target reached: this chain covers current best points.")
            complete_label.setStyleSheet("color: #67e8f9; font-size: 11px; font-weight: 700;")
            parent_layout.addWidget(complete_label)

    def _build_breeding_plan_sequence(
        self,
        ranked_pairs: list[tuple[int, float, Creature, Creature]],
        targets: list[tuple[str, int]],
        use_points: bool = False,
    ) -> tuple[list[dict[str, object]], list[str]]:
        if not ranked_pairs:
            return [], []

        rank_lookup = {rank: (score, male, female) for rank, score, male, female in ranked_pairs}
        base_points, steps, pending = self._build_breeding_plan_steps(
            ranked_pairs,
            targets,
            use_points=use_points,
        )
        sequence: list[dict[str, object]] = []
        start_rank, _start_score, start_male, start_female = ranked_pairs[0]
        sequence.append(
            {
                "step": 1,
                "rank": start_rank,
                "male": start_male,
                "female": start_female,
                "expected_points": dict(base_points),
                "merged_points": dict(base_points),
                "gains": [],
                "from_child": "",
            }
        )

        current_points = dict(base_points)
        step_index = 2
        for step in steps:
            donor_rank = int(step["donor_rank"])
            donor = rank_lookup.get(donor_rank)
            if donor is None:
                continue
            _score, male, female = donor
            donor_points = self._expected_child_points(male, female, use_points=use_points)
            merged_points = {
                key: max(current_points.get(key, 0.0), donor_points.get(key, 0.0))
                for _short, key, _title in _BREEDING_POINT_STAT_CONFIG
            }
            gains = [
                short
                for short, key, _title in _BREEDING_POINT_STAT_CONFIG
                if merged_points.get(key, 0.0) > current_points.get(key, 0.0) + 0.001
            ]
            sequence.append(
                {
                    "step": step_index,
                    "rank": donor_rank,
                    "male": male,
                    "female": female,
                    "expected_points": dict(donor_points),
                    "merged_points": dict(merged_points),
                    "gains": gains,
                    "from_child": self._combined_child_title(step_index - 1),
                }
            )
            current_points = merged_points
            step_index += 1

        return sequence, pending

    def _expected_child_title(self, step: int) -> str:
        names = {
            1: "One",
            2: "Two",
            3: "Three",
            4: "Four",
            5: "Five",
        }
        suffix = names.get(step, str(step))
        return f"{self._sex_icon('male')}/{self._sex_icon('female')} Expected {suffix}"

    def _combined_child_title(self, step: int) -> str:
        names = {
            1: "One",
            2: "Two",
            3: "Three",
            4: "Four",
            5: "Five",
        }
        suffix = names.get(step, str(step))
        return f"{self._sex_icon('male')}/{self._sex_icon('female')} Combined {suffix}"

    def _plan_down_arrow(self) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addStretch(1)
        arrow = QtWidgets.QLabel("↓")
        arrow.setAlignment(QtCore.Qt.AlignCenter)
        arrow.setStyleSheet("color: #93c5fd; font-size: 16px; font-weight: 800;")
        row.addWidget(arrow)
        row.addStretch(1)
        return container

    def _build_breeding_plan_steps(
        self,
        ranked_pairs: list[tuple[int, float, Creature, Creature]],
        targets: list[tuple[str, int]],
        use_points: bool = False,
    ) -> tuple[dict[str, float], list[dict[str, object]], list[str]]:
        first_male = ranked_pairs[0][2]
        first_female = ranked_pairs[0][3]
        base_points = self._expected_child_points(first_male, first_female, use_points=use_points)
        current_points = dict(base_points)
        target_by_key = {
            key: float(value)
            for short, value in targets
            for s, key, _title in _BREEDING_POINT_STAT_CONFIG
            if short == s
        }
        key_to_short = {key: short for short, key, _title in _BREEDING_POINT_STAT_CONFIG}

        steps: list[dict[str, object]] = []
        used_donors: set[int] = set()
        max_iterations = max(0, min(9, len(ranked_pairs) - 1))
        for _ in range(max_iterations):
            pending_keys = [
                key
                for key, target in target_by_key.items()
                if current_points.get(key, 0.0) + 0.001 < target
            ]
            if not pending_keys:
                break

            best_choice: dict[str, object] | None = None
            for rank, _score, male, female in ranked_pairs[1:]:
                if rank in used_donors:
                    continue
                donor_points = self._expected_child_points(male, female, use_points=use_points)
                candidate = dict(current_points)
                for key in target_by_key:
                    candidate[key] = max(candidate.get(key, 0.0), donor_points.get(key, 0.0))

                gained_keys = [
                    key
                    for key in target_by_key
                    if candidate.get(key, 0.0) > current_points.get(key, 0.0) + 0.001
                ]
                if not gained_keys:
                    continue

                target_gain = sum(
                    max(
                        0.0,
                        min(candidate.get(key, 0.0), target_by_key[key])
                        - min(current_points.get(key, 0.0), target_by_key[key]),
                    )
                    for key in pending_keys
                )
                total_gain = sum(
                    max(0.0, candidate.get(key, 0.0) - current_points.get(key, 0.0))
                    for key in target_by_key
                )
                if target_gain <= 0:
                    continue
                score_tuple = (target_gain, total_gain, -rank)
                if best_choice is None or score_tuple > best_choice["score"]:  # type: ignore[operator]
                    best_choice = {
                        "rank": rank,
                        "male_name": male.name,
                        "female_name": female.name,
                        "points": candidate,
                        "gains": [key_to_short[key] for key in gained_keys if key in key_to_short],
                        "score": score_tuple,
                    }

            if best_choice is None:
                break

            used_donors.add(int(best_choice["rank"]))
            current_points = dict(best_choice["points"])  # type: ignore[arg-type]
            steps.append(
                {
                    "donor_rank": int(best_choice["rank"]),
                    "donor_male": str(best_choice["male_name"]),
                    "donor_female": str(best_choice["female_name"]),
                    "gains": list(best_choice["gains"]),  # type: ignore[arg-type]
                    "points": dict(current_points),
                }
            )

        pending_shorts = [
            short
            for short, key, _title in _BREEDING_POINT_STAT_CONFIG
            if key in target_by_key and current_points.get(key, 0.0) + 0.001 < target_by_key[key]
        ]
        return base_points, steps, pending_shorts

    def _rank_badge(self, rank: int) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel()
        label.setAlignment(QtCore.Qt.AlignCenter)
        label.setFixedWidth(40)
        if rank == 1:
            label.setText("🥇")
            label.setStyleSheet("color: #facc15; font-size: 15px;")
        elif rank == 2:
            label.setText("🥈")
            label.setStyleSheet("color: #cbd5e1; font-size: 15px;")
        elif rank == 3:
            label.setText("🥉")
            label.setStyleSheet("color: #f59e0b; font-size: 15px;")
        else:
            label.setText(f"#{rank}")
            label.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 700;")
        return label

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
        badge.setMinimumWidth(56)
        badge.setStyleSheet(
            """
            QLabel {
                background: #111827;
                border: 1px solid #1f2937;
                border-radius: 8px;
                padding: 4px 6px;
                font-size: 12px;
                font-weight: 600;
            }
            """
        )
        return badge

    def _point_icon(self, code: str) -> str:
        icons = {
            "H": "✚",
            "S": "⚗",
            "O": "💧",
            "F": "♨",
            "W": "⚖",
            "M": "🗡︎",
            "Sp": "≫",
        }
        return icons.get(code, code)

    def _truncate_text(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[:limit] + "..."

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
        labels = {key: short for short, key, _title in _DETAIL_POINT_STAT_CONFIG}
        points = self._get_stat_points(creature)
        max_points_by_key: dict[str, int] = {}
        for _short, key, _title in _DETAIL_POINT_STAT_CONFIG:
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
            self._detail_rank_note.setText("")
            self._detail_crown.setVisible(False)
            self._detail_insights.setText("Select a creature to see insights.")
            self._detail_strengths.setText("Strengths: -")
            self._detail_weaknesses.setText("Weaknesses: -")
            if hasattr(self, "_detail_delete_btn"):
                self._detail_delete_btn.setEnabled(False)
            self._apply_detail_panel_accent(None)
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

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched is getattr(self, "_detail_panel", None) and event.type() == QtCore.QEvent.Resize:
            self._position_detail_crown()
        return super().eventFilter(watched, event)

    def _position_detail_crown(self) -> None:
        if not hasattr(self, "_detail_panel") or not hasattr(self, "_detail_crown"):
            return
        size = self._detail_crown.sizeHint()
        self._detail_crown.resize(size)
        margins = self._detail_panel.contentsMargins()
        x = max(0, self._detail_panel.width() - size.width() - margins.right() - 1)
        y = -10
        self._detail_crown.move(x, y)

    def _update_creature_detail(self, creature: Creature) -> None:
        rank, ranked_count = self._species_sex_rank(creature)
        is_top_candidate = rank == 1 and ranked_count >= 2
        self._apply_detail_panel_accent(creature.sex, spotlight=is_top_candidate)
        if hasattr(self, "_detail_delete_btn"):
            self._detail_delete_btn.setEnabled(creature.id is not None)
        title = f"{self._sex_icon(creature.sex)} {creature.name or 'Unknown'}"
        self._detail_title.setText(title)
        self._detail_crown.setVisible(is_top_candidate)
        self._position_detail_crown()
        if is_top_candidate:
            crown_glow = QtWidgets.QGraphicsDropShadowEffect(self._detail_crown)
            crown_glow.setBlurRadius(34)
            crown_glow.setOffset(0, 0)
            crown_glow.setColor(QtGui.QColor(103, 232, 249, 240))
            self._detail_crown.setGraphicsEffect(crown_glow)
        else:
            self._detail_crown.setGraphicsEffect(None)
        subtitle = f"{self._display_species(creature.species)} • {creature.sex} • L{creature.level}"
        self._detail_subtitle.setText(subtitle)
        self._detail_rank_note.setText(self._build_detail_rank_note(creature))
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
        values = {}
        for label, key in radar_axes:
            value = self._get_stat_value(creature, key, use_points=use_points)
            values[label] = min(max(float(value), 0.0), 100.0)
        radar_max = {label: 100.0 for label, _key in radar_axes}
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
        self._detail_insights.setText(
            self._build_detail_insights(
                creature,
                species_group,
            )
        )
        if len(species_group) <= 1:
            self._detail_strengths.setText("Strengths: Add more of this species for comparison.")
            self._detail_weaknesses.setText("Weaknesses: Add more of this species for comparison.")
            return

        self._detail_strengths.setText(
            "Strengths: "
            + (
                self._render_stat_badges(strengths, "#67e8f9")
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

    def _build_detail_rank_note(self, creature: Creature) -> str:
        rank, ranked_count = self._species_sex_rank(creature)
        if rank is None or ranked_count < 2:
            return ""
        if rank == 1:
            return f"Top {creature.sex} candidate in species"
        return f"Rank #{rank} {creature.sex} candidate in species"

    def _build_detail_insights(
        self,
        creature: Creature,
        species_group: list[Creature],
    ) -> str:
        rank, ranked_count = self._species_sex_rank(creature)
        max_by_key: dict[str, int] = {}
        for _short, key, _title in _DETAIL_POINT_STAT_CONFIG:
            values = [
                int(value)
                for candidate in species_group
                if (value := self._get_stat_points_value(candidate, key)) is not None
            ]
            if values:
                max_by_key[key] = max(values)

        top_stats_items: list[str] = []
        for short, key, _title in _DETAIL_POINT_STAT_CONFIG:
            value = self._get_stat_points_value(creature, key)
            if value is None:
                continue
            int_value = int(value)
            species_max = max_by_key.get(key)
            if species_max is None:
                continue
            if int_value >= species_max:
                top_stats_items.append(f"{self._point_icon(short)} {int_value}")
        top_stats = ", ".join(top_stats_items) if top_stats_items else "n/a"

        role: str
        if ranked_count < 2 or rank is None:
            role = "Need more same-species creatures for full ranking."
        elif rank == 1:
            role = f"Primary {creature.sex.lower()} breeder candidate."
        else:
            role = f"Backup {creature.sex.lower()} breeder (rank #{rank})."
        return (
            f"<b>Top points:</b> {top_stats}<br/>"
            f"<b>Role:</b> {role}"
        )

    def _species_sex_rank(self, creature: Creature) -> tuple[int | None, int]:
        species_group = [
            c
            for c in self._creature_cache
            if self._display_species(c.species) == self._display_species(creature.species)
            and (c.sex or "").lower() == (creature.sex or "").lower()
        ]
        if not species_group:
            return None, 0
        use_points = self._points_available(species_group)
        ranked = sorted(
            species_group,
            key=lambda c: self._breeding_creature_score(c, use_points=use_points),
            reverse=True,
        )
        for index, candidate in enumerate(ranked, start=1):
            same_external = (
                candidate.external_id is not None
                and creature.external_id is not None
                and candidate.external_id == creature.external_id
            )
            same_id = candidate.id is not None and creature.id is not None and candidate.id == creature.id
            if same_external or same_id:
                return index, len(ranked)
        return None, len(ranked)

    def _delete_selected_creature(self) -> None:
        creature = self._selected_creature
        if creature is None or creature.id is None:
            return

        ask_confirm = get_setting(self._conn, "confirm_delete_creature") != "0"
        if ask_confirm:
            dialog = QtWidgets.QMessageBox(self)
            dialog.setOption(QtWidgets.QMessageBox.DontUseNativeDialog, True)
            dialog.setIcon(QtWidgets.QMessageBox.Warning)
            dialog.setWindowTitle("Delete creature")
            dialog.setText(f"Delete '{creature.name}'?")
            dialog.setInformativeText("This action removes the creature from local data.")
            dialog.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            dialog.setStyleSheet(
                "QMessageBox { background: #0f172a; color: #e5e7eb; border: 1px solid #334155; border-radius: 12px; }"
                "QLabel { color: #e5e7eb; font-size: 12px; }"
                "QPushButton { background: #1e293b; color: #e5e7eb; border: 1px solid #334155;"
                "padding: 6px 10px; border-radius: 6px; min-width: 92px; }"
                "QPushButton:hover { background: #243247; }"
                "QCheckBox { color: #cbd5f5; spacing: 6px; }"
                "QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #334155;"
                "background: #111827; border-radius: 3px; }"
                "QCheckBox::indicator:checked { background: #38bdf8; border: 1px solid #38bdf8; }"
            )
            checkbox = QtWidgets.QCheckBox("Don't ask me again")
            dialog.setCheckBox(checkbox)
            result = dialog.exec()
            if checkbox.isChecked():
                set_setting(self._conn, "confirm_delete_creature", "0")
            if result != QtWidgets.QMessageBox.Yes:
                return

        removed = delete_creature(self._conn, creature)
        if not removed:
            self.show_toast("Failed to delete creature.", "error")
            return

        files_removed, files_failed = self._delete_export_files_for_creature(creature)
        self._selected_creature = None
        self.refresh_data()
        if files_removed > 0 and files_failed == 0:
            self.show_toast(f"Creature deleted. Removed {files_removed} export file(s).", "success")
        elif files_removed > 0:
            self.show_toast(
                f"Creature deleted. Removed {files_removed} file(s), {files_failed} failed.",
                "info",
            )
        else:
            self.show_toast("Creature deleted.", "success")

    def _delete_export_files_for_creature(self, creature: Creature) -> tuple[int, int]:
        if not creature.external_id or not self._export_dir.exists():
            return 0, 0

        removed = 0
        failed = 0
        target_id = creature.external_id

        for path in sorted(self._export_dir.rglob("*.ini")):
            if not path.is_file():
                continue
            try:
                parsed = parse_creature_file(path)
            except Exception:
                continue
            if parsed.external_id != target_id:
                continue
            try:
                path.unlink()
                removed += 1
            except OSError:
                failed += 1

        # Remove now-empty subfolders created under DinoExports/<id>/...
        for folder in sorted(
            (p for p in self._export_dir.rglob("*") if p.is_dir()),
            key=lambda p: len(p.parts),
            reverse=True,
        ):
            if folder == self._export_dir:
                continue
            try:
                if not any(folder.iterdir()):
                    folder.rmdir()
            except OSError:
                continue

        return removed, failed

    def _apply_detail_panel_accent(self, sex: str | None, spotlight: bool = False) -> None:
        if not hasattr(self, "_detail_panel"):
            return
        accent = "rgba(148, 163, 184, 0.25)"
        glow = QtGui.QColor(148, 163, 184, 105)
        lowered = (sex or "").lower()
        if lowered == "male":
            accent = "#60a5fa"
            glow = QtGui.QColor(96, 165, 250, 120)
        elif lowered == "female":
            accent = "#f472b6"
            glow = QtGui.QColor(244, 114, 182, 120)
        if spotlight:
            accent = "#67e8f9"
            glow = QtGui.QColor(103, 232, 249, 230)
        self._detail_panel.setStyleSheet(
            "#detailPanel {"
            f"background: rgba(15, 23, 42, {'0.62' if spotlight else '0.44'}); border: {3 if spotlight else 2}px solid {accent};"
            "border-radius: 16px;"
            "}"
        )
        effect = QtWidgets.QGraphicsDropShadowEffect(self._detail_panel)
        effect.setBlurRadius(42 if spotlight else 14)
        effect.setOffset(0, 0)
        glow.setAlpha(255 if spotlight else 100)
        effect.setColor(glow)
        self._detail_panel.setGraphicsEffect(effect)

    def _compute_strengths_weaknesses(
        self,
        creature: Creature,
        species_group: list[Creature],
        use_points: bool = False,
    ) -> tuple[list[str], list[str]]:
        strengths: list[str] = []
        weaknesses: list[str] = []
        stat_map = [(short, key) for short, key, _title in _DETAIL_POINT_STAT_CONFIG]

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
            badges.append(f"<img src=\"{icon_path.as_posix()}\" width=\"20\" height=\"20\" />")
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
        self._load_manual_overrides_inputs()
        self._update_settings_view()

    def _update_settings_view(self) -> None:
        if hasattr(self, "_settings_warning"):
            self._settings_warning.setText(self._official_consistency_warning())
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
        if multipliers.max_wild_level is not None and int(multipliers.max_wild_level) > 0:
            non_default_count += 1
            lines.append(f"- Max wild level cap: {int(multipliers.max_wild_level)}")
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

    def _official_consistency_warning(self) -> str:
        if not self._creature_cache:
            return ""
        over_level = [c for c in self._creature_cache if c.level > 450]
        over_points: list[Creature] = []
        inconsistent_bred: list[Creature] = []
        for creature in self._creature_cache:
            points = self._get_stat_points(creature)
            if not points:
                continue
            if any(int(value) > 255 for value in points.values()):
                over_points.append(creature)
            if creature.mother_external_id or creature.father_external_id:
                point_total = 0
                for _short, key, _title in _POINT_STAT_CONFIG:
                    value = points.get(key)
                    if value is None:
                        continue
                    point_total += int(value)
                expected = max(0, int(creature.level) - 1)
                if abs(point_total - expected) > 6:
                    inconsistent_bred.append(creature)
        flagged = {id(c): c for c in over_level + over_points + inconsistent_bred}
        if not flagged:
            return ""
        return (
            f"Official baseline check: {len(flagged)} creature(s) exceed official caps "
            "or have inconsistent point budgets (level > 450, stat points > 255, or bred budget mismatch). "
            "Import server INI files or set manual overrides above."
        )

    def _fmt_multiplier(self, value: float) -> str:
        formatted = f"{value:.4f}".rstrip("0").rstrip(".")
        return formatted or "0"

    def _manual_overrides_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self._manual_max_level_input is not None:
            payload["max_wild_level"] = int(self._manual_max_level_input.value())
        if self._manual_override_difficulty_input is not None:
            payload["override_official_difficulty"] = float(
                self._manual_override_difficulty_input.value()
            )
        if self._manual_difficulty_offset_input is not None:
            payload["difficulty_offset"] = float(self._manual_difficulty_offset_input.value())
        if self._manual_imprint_input is not None:
            payload["imprinting"] = float(self._manual_imprint_input.value())
        return payload

    def _load_manual_overrides_inputs(self) -> None:
        if (
            self._manual_max_level_input is None
            and self._manual_override_difficulty_input is None
            and self._manual_difficulty_offset_input is None
            and self._manual_imprint_input is None
        ):
            return
        defaults: dict[str, object] = {}
        if self._server_settings:
            raw = self._server_settings.get("manual_overrides")
            if isinstance(raw, dict):
                defaults = raw
        max_wild_default = int(defaults.get("max_wild_level") or 0)
        if max_wild_default <= 0 and self._stat_multipliers.max_wild_level:
            max_wild_default = int(self._stat_multipliers.max_wild_level)
        if self._manual_max_level_input is not None:
            self._manual_max_level_input.setValue(max(0, max_wild_default))

        imported_override = self._server_setting_float("OverrideOfficialDifficulty") or 0.0
        override_default = float(defaults.get("override_official_difficulty") or imported_override)
        if self._manual_override_difficulty_input is not None:
            self._manual_override_difficulty_input.setValue(max(0.0, override_default))

        imported_offset = self._server_setting_float("DifficultyOffset") or 0.0
        offset_default = float(defaults.get("difficulty_offset") or imported_offset)
        if self._manual_difficulty_offset_input is not None:
            self._manual_difficulty_offset_input.setValue(max(0.0, offset_default))

        imprint_value = float(defaults.get("imprinting") or self._stat_multipliers.imprinting or 1.0)
        if self._manual_imprint_input is not None:
            self._manual_imprint_input.setValue(imprint_value)

    def _server_setting_float(self, key_name: str) -> float | None:
        if not self._server_settings:
            return None
        needle = key_name.strip().lower()
        for source_key in ("game_user_settings", "game_ini"):
            source = self._server_settings.get(source_key)
            if not isinstance(source, dict):
                continue
            for section in source.values():
                if not isinstance(section, dict):
                    continue
                for raw_key, raw_value in section.items():
                    if not isinstance(raw_key, str):
                        continue
                    if raw_key.strip().lower() != needle:
                        continue
                    try:
                        return float(raw_value)
                    except (TypeError, ValueError):
                        return None
        return None

    def _apply_manual_overrides(self) -> None:
        payload = self._ensure_server_settings_payload()
        payload["manual_overrides"] = self._manual_overrides_payload()
        self._save_server_settings(payload, "Manual overrides applied.")

    def _reset_manual_overrides(self) -> None:
        if self._manual_max_level_input is not None:
            self._manual_max_level_input.setValue(0)
        if self._manual_override_difficulty_input is not None:
            self._manual_override_difficulty_input.setValue(0.0)
        if self._manual_difficulty_offset_input is not None:
            self._manual_difficulty_offset_input.setValue(0.0)
        if self._manual_imprint_input is not None:
            self._manual_imprint_input.setValue(1.0)
        payload = self._ensure_server_settings_payload()
        payload["manual_overrides"] = self._manual_overrides_payload()
        self._save_server_settings(payload, "Manual overrides reset.")

    def _load_species_values(self) -> None:
        self._values_store = SpeciesValuesStore()
        self._values_from_bundle = False
        default_path = bundled_values_path()
        self._values_path = str(default_path)
        loaded = False
        if default_path.exists():
            try:
                self._values_store.load_values_file(default_path)
                loaded = self._values_store.count() > 0
            except Exception:
                logger.exception("Failed to load bundled values from %s", default_path)
            if loaded:
                self._values_from_bundle = True
        self._update_values_view()
        self._update_points_info_labels()
        self._recompute_stat_points()

    def _update_values_view(self) -> None:
        if not hasattr(self, "_values_summary") or not hasattr(self, "_values_details"):
            return
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
        self._stat_multipliers = extract_stat_multipliers(self._server_settings)
        self._load_manual_overrides_inputs()
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
