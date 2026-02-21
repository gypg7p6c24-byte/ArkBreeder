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
        self._pending_sources: list[str] = []

    def set_species(self, species: str) -> None:
        if not species:
            self.setText("No image")
            return
        self._pending_species = species
        cached = self._cache_path(species)
        if cached.exists():
            self._set_pixmap(QtGui.QPixmap(str(cached)))
            return
        self.setText("Loading image...")
        self._pending_sources = [
            self._wiki_page_url(species),
            self._fandom_page_url(species),
        ]
        self._fetch_next_source()

    def _on_reply(self, reply: QtNetwork.QNetworkReply) -> None:
        if reply.error() != QtNetwork.QNetworkReply.NoError:
            if self._pending_kind == "html" and self._fetch_next_source():
                return
            self.setText("Image unavailable")
            return
        data = reply.readAll()
        if self._pending_kind == "html":
            html = bytes(data).decode("utf-8", errors="replace")
            image_url = self._extract_og_image(html)
            if not image_url:
                if self._fetch_next_source():
                    return
                self.setText("Image unavailable")
                return
            self._pending_kind = "image"
            self._pending_url = QtCore.QUrl(image_url)
            self._manager.get(self._build_request(self._pending_url))
            return
        if self._pending_kind == "image":
            pixmap = QtGui.QPixmap()
            pixmap.loadFromData(data)
            if pixmap.isNull():
                self.setText("Image unavailable")
                return
            if self._pending_species:
                pixmap.save(str(self._cache_path(self._pending_species)))
            self._set_pixmap(pixmap)

    def _fetch_next_source(self) -> bool:
        if not self._pending_sources:
            return False
        page_url = self._pending_sources.pop(0)
        self._pending_kind = "html"
        self._pending_url = QtCore.QUrl(page_url)
        self._manager.get(self._build_request(self._pending_url))
        return True

    def _set_pixmap(self, pixmap: QtGui.QPixmap) -> None:
        scaled = pixmap.scaled(
            self.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
        )
        self.setPixmap(scaled)

    def _cache_path(self, species: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", species).lower()
        cache_dir = user_data_dir() / "cache" / "images"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"{safe}.png"

    def _wiki_page_url(self, species: str) -> str:
        mapped = _SPECIES_PAGE_OVERRIDES.get(species, species)
        slug = mapped.replace(" ", "_")
        return f"https://ark.wiki.gg/wiki/{urllib.parse.quote(slug)}"

    def _fandom_page_url(self, species: str) -> str:
        mapped = _SPECIES_PAGE_OVERRIDES.get(species, species)
        slug = mapped.replace(" ", "_")
        return f"https://ark.fandom.com/wiki/{urllib.parse.quote(slug)}"

    def _extract_og_image(self, html: str) -> str | None:
        match = re.search(r'property="og:image"\\s+content="([^"]+)"', html)
        if match:
            return match.group(1)
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
