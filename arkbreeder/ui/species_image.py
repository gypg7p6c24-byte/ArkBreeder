from __future__ import annotations

from pathlib import Path
import re
import urllib.parse

from PySide6 import QtCore, QtGui, QtNetwork, QtWidgets

from arkbreeder.config import user_data_dir


class SpeciesImageWidget(QtWidgets.QLabel):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(240, 160)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setText("No image")
        self.setStyleSheet("border: 1px solid #1f2937; border-radius: 10px;")
        self._manager = QtNetwork.QNetworkAccessManager(self)
        self._manager.finished.connect(self._on_reply)
        self._pending_species: str | None = None
        self._pending_kind: str | None = None
        self._pending_url: QtCore.QUrl | None = None
        self._pending_sources: list[tuple[str, str, str]] = []
        self._pending_base: str | None = None
        self._loading_timer = QtCore.QTimer(self)
        self._loading_timer.setInterval(350)
        self._loading_timer.timeout.connect(self._tick_loading)
        self._loading_text = "Loading image"
        self._loading_dots = 0

    def set_species(self, species: str) -> None:
        if not species:
            self.setText("No image")
            return
        self._pending_species = species
        cached = self._cache_path(species)
        if cached.exists():
            self._set_pixmap(QtGui.QPixmap(str(cached)))
            return
        self._start_loading()
        self._pending_sources = [
            ("pageimage", "wiki", self._wiki_api_url(species)),
            ("search", "wiki", self._wiki_search_url(species)),
            ("pageimage", "fandom", self._fandom_api_url(species)),
            ("search", "fandom", self._fandom_search_url(species)),
        ]
        self._fetch_next_source()

    def _on_reply(self, reply: QtNetwork.QNetworkReply) -> None:
        if reply.error() != QtNetwork.QNetworkReply.NoError:
            if self._pending_kind == "html" and self._fetch_next_source():
                return
            self._stop_loading()
            self.setText("Image unavailable")
            return
        data = reply.readAll()
        if self._pending_kind == "pageimage":
            image_url = self._extract_api_image(bytes(data))
            if not image_url:
                if self._fetch_next_source():
                    return
                self._stop_loading()
                self.setText("Image unavailable")
                return
            self._pending_kind = "image"
            self._pending_url = QtCore.QUrl(image_url)
            self._manager.get(self._build_request(self._pending_url))
            return
        if self._pending_kind == "search":
            title = self._extract_search_title(bytes(data))
            if not title:
                if self._fetch_next_source():
                    return
                self._stop_loading()
                self.setText("Image unavailable")
                return
            if self._pending_base == "fandom":
                self._pending_kind = "pageimage"
                self._pending_url = QtCore.QUrl(self._fandom_api_url(title))
            else:
                self._pending_kind = "pageimage"
                self._pending_url = QtCore.QUrl(self._wiki_api_url(title))
            self._manager.get(self._build_request(self._pending_url))
            return
        if self._pending_kind == "image":
            pixmap = QtGui.QPixmap()
            pixmap.loadFromData(data)
            if pixmap.isNull():
                self._stop_loading()
                self.setText("Image unavailable")
                return
            if self._pending_species:
                pixmap.save(str(self._cache_path(self._pending_species)))
            self._set_pixmap(pixmap)

    def _fetch_next_source(self) -> bool:
        if not self._pending_sources:
            return False
        kind, base, page_url = self._pending_sources.pop(0)
        self._pending_kind = kind
        self._pending_base = base
        self._pending_url = QtCore.QUrl(page_url)
        self._manager.get(self._build_request(self._pending_url))
        return True

    def _set_pixmap(self, pixmap: QtGui.QPixmap) -> None:
        self._stop_loading()
        scaled = pixmap.scaled(
            self.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
        )
        self.setPixmap(scaled)

    def _start_loading(self) -> None:
        self._loading_dots = 0
        self.setText(self._loading_text)
        if not self._loading_timer.isActive():
            self._loading_timer.start()

    def _stop_loading(self) -> None:
        if self._loading_timer.isActive():
            self._loading_timer.stop()
        self._loading_dots = 0

    def _tick_loading(self) -> None:
        self._loading_dots = (self._loading_dots + 1) % 4
        dots = "." * self._loading_dots
        self.setText(f"{self._loading_text}{dots}")

    def _cache_path(self, species: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", species).lower()
        cache_dir = user_data_dir() / "cache" / "images"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"{safe}.png"

    def _wiki_api_url(self, species: str) -> str:
        mapped = _SPECIES_PAGE_OVERRIDES.get(species, species)
        return (
            "https://ark.wiki.gg/api.php?action=query&prop=pageimages&format=json"
            f"&pithumbsize=400&titles={urllib.parse.quote(mapped)}"
        )

    def _fandom_api_url(self, species: str) -> str:
        mapped = _SPECIES_PAGE_OVERRIDES.get(species, species)
        return (
            "https://ark.fandom.com/api.php?action=query&prop=pageimages&format=json"
            f"&pithumbsize=400&titles={urllib.parse.quote(mapped)}"
        )

    def _wiki_search_url(self, species: str) -> str:
        mapped = _SPECIES_PAGE_OVERRIDES.get(species, species)
        return (
            "https://ark.wiki.gg/api.php?action=query&list=search&format=json"
            f"&srsearch={urllib.parse.quote(mapped)}"
        )

    def _fandom_search_url(self, species: str) -> str:
        mapped = _SPECIES_PAGE_OVERRIDES.get(species, species)
        return (
            "https://ark.fandom.com/api.php?action=query&list=search&format=json"
            f"&srsearch={urllib.parse.quote(mapped)}"
        )

    def _extract_api_image(self, raw: bytes) -> str | None:
        try:
            text = raw.decode("utf-8", errors="replace")
            data = QtCore.QJsonDocument.fromJson(text.encode("utf-8")).toVariant()
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        query = data.get("query", {})
        pages = query.get("pages", {}) if isinstance(query, dict) else {}
        for page in pages.values():
            if not isinstance(page, dict):
                continue
            thumbnail = page.get("thumbnail", {})
            if isinstance(thumbnail, dict):
                source = thumbnail.get("source")
                if isinstance(source, str):
                    return source
        return None

    def _extract_search_title(self, raw: bytes) -> str | None:
        try:
            text = raw.decode("utf-8", errors="replace")
            data = QtCore.QJsonDocument.fromJson(text.encode("utf-8")).toVariant()
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        query = data.get("query", {})
        if not isinstance(query, dict):
            return None
        results = query.get("search", [])
        if not isinstance(results, list) or not results:
            return None
        first = results[0]
        if isinstance(first, dict):
            title = first.get("title")
            if isinstance(title, str):
                return title
        return None

    def _build_request(self, url: QtCore.QUrl) -> QtNetwork.QNetworkRequest:
        request = QtNetwork.QNetworkRequest(url)
        request.setRawHeader(
            b"User-Agent",
            b"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            b"(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        return request


_SPECIES_PAGE_OVERRIDES = {
    "Ptero": "Pteranodon",
    "Argent": "Argentavis",
}
