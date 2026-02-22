from __future__ import annotations

import json
from pathlib import Path
import re
import urllib.parse

from PySide6 import QtCore, QtGui, QtNetwork, QtWidgets

from arkbreeder.config import user_data_dir

_IMAGE_CACHE_VERSION = 2


class SpeciesImageWidget(QtWidgets.QLabel):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(240, 160)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setText("No image")
        self.setStyleSheet("border: 1px solid #1f2937; border-radius: 10px;")
        self._manager = QtNetwork.QNetworkAccessManager(self)
        self._manager.finished.connect(self._on_reply)
        self._active_request_id = 0
        self._active_species: str | None = None
        self._active_sources: list[tuple[str, str, str]] = []
        self._loading_timer = QtCore.QTimer(self)
        self._loading_timer.setInterval(350)
        self._loading_timer.timeout.connect(self._tick_loading)
        self._loading_text = "Loading image"
        self._loading_dots = 0

    def set_species(self, species: str) -> None:
        if not species:
            self._stop_loading()
            self.setPixmap(QtGui.QPixmap())
            self.setText("No image")
            return
        self._active_request_id += 1
        request_id = self._active_request_id
        self._active_species = species

        cached = self._cache_path(species)
        if self._is_valid_cache(species, cached):
            pixmap = QtGui.QPixmap(str(cached))
            if not pixmap.isNull():
                self._set_pixmap(pixmap)
                return
            self._invalidate_cache(species)

        self.setPixmap(QtGui.QPixmap())
        self._start_loading()
        self._active_sources = [
            ("pageimage", "wiki", self._wiki_api_url(species)),
            ("search", "wiki", self._wiki_search_url(species)),
            ("pageimage", "fandom", self._fandom_api_url(species)),
            ("search", "fandom", self._fandom_search_url(species)),
        ]
        self._fetch_next_source(request_id)

    def _on_reply(self, reply: QtNetwork.QNetworkReply) -> None:
        request_id = int(reply.property("request_id") or 0)
        kind = str(reply.property("kind") or "")
        base = str(reply.property("base") or "")
        species = str(reply.property("species") or "")

        if request_id != self._active_request_id:
            reply.deleteLater()
            return

        if reply.error() != QtNetwork.QNetworkReply.NoError:
            reply.deleteLater()
            if self._fetch_next_source(request_id):
                return
            self._stop_loading()
            self.setText("Image not available")
            return

        data = reply.readAll()
        if kind == "pageimage":
            image_url = self._extract_api_image(bytes(data))
            if not image_url:
                reply.deleteLater()
                if self._fetch_next_source(request_id):
                    return
                self._stop_loading()
                self.setText("Image not available")
                return
            self._issue_request(image_url, request_id, "image", base, species)
            reply.deleteLater()
            return
        if kind == "search":
            title = self._extract_search_title(bytes(data))
            if not title:
                reply.deleteLater()
                if self._fetch_next_source(request_id):
                    return
                self._stop_loading()
                self.setText("Image unavailable")
                return
            if base == "fandom":
                next_url = self._fandom_api_url(title)
            else:
                next_url = self._wiki_api_url(title)
            self._issue_request(next_url, request_id, "pageimage", base, species)
            reply.deleteLater()
            return
        if kind == "image":
            pixmap = QtGui.QPixmap()
            pixmap.loadFromData(data)
            if pixmap.isNull():
                reply.deleteLater()
                if self._fetch_next_source(request_id):
                    return
                self._stop_loading()
                self.setText("Image not available")
                return
            if species:
                pixmap.save(str(self._cache_path(species)))
                self._write_cache_metadata(species)
            self._set_pixmap(pixmap)
        reply.deleteLater()

    def _fetch_next_source(self, request_id: int) -> bool:
        if request_id != self._active_request_id:
            return False
        if not self._active_sources:
            return False
        kind, base, page_url = self._active_sources.pop(0)
        self._issue_request(
            page_url,
            request_id=request_id,
            kind=kind,
            base=base,
            species=self._active_species,
        )
        return True

    def _issue_request(
        self,
        url: str,
        request_id: int,
        kind: str,
        base: str,
        species: str | None,
    ) -> None:
        qurl = QtCore.QUrl(url)
        reply = self._manager.get(self._build_request(qurl))
        reply.setProperty("request_id", request_id)
        reply.setProperty("kind", kind)
        reply.setProperty("base", base)
        reply.setProperty("species", species or "")

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

    def _cache_meta_path(self, species: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", species).lower()
        cache_dir = user_data_dir() / "cache" / "images"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"{safe}.json"

    def _is_valid_cache(self, species: str, cache_path: Path) -> bool:
        if not cache_path.exists():
            return False
        meta_path = self._cache_meta_path(species)
        if not meta_path.exists():
            return False
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        return (
            isinstance(metadata, dict)
            and metadata.get("species") == species
            and metadata.get("version") == _IMAGE_CACHE_VERSION
        )

    def _write_cache_metadata(self, species: str) -> None:
        meta_path = self._cache_meta_path(species)
        payload = {"species": species, "version": _IMAGE_CACHE_VERSION}
        meta_path.write_text(json.dumps(payload), encoding="utf-8")

    def _invalidate_cache(self, species: str) -> None:
        for path in (self._cache_path(species), self._cache_meta_path(species)):
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                continue

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
    "Pterodactyl": "Pteranodon",
    "Argent": "Argentavis",
}
