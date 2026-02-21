from __future__ import annotations

from typing import Optional

from PySide6 import QtCore, QtWidgets


class ToastNotification(QtWidgets.QWidget):
    def __init__(
        self,
        parent: QtWidgets.QWidget,
        message: str,
        kind: str = "info",
        duration_ms: int = 5000,
    ) -> None:
        flags = QtCore.Qt.ToolTip | QtCore.Qt.FramelessWindowHint
        super().__init__(parent, flags)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self._duration_ms = duration_ms
        self._kind = kind

        self._effect = QtWidgets.QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)

        container = QtWidgets.QFrame()
        container.setObjectName("toastContainer")
        layout = QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(12)

        self._label = QtWidgets.QLabel(message)
        self._label.setWordWrap(True)

        close_btn = QtWidgets.QToolButton()
        close_btn.setText("OK")
        close_btn.clicked.connect(self.fade_out)

        layout.addWidget(self._label, 1)
        layout.addWidget(close_btn)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(container)

        self._apply_style(container, close_btn)

        self._fade_anim = QtCore.QPropertyAnimation(self._effect, b"opacity")
        self._fade_anim.setDuration(800)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self.close)

        QtCore.QTimer.singleShot(self._duration_ms, self.fade_out)

    def _apply_style(self, container: QtWidgets.QFrame, close_btn: QtWidgets.QToolButton) -> None:
        palette = {
            "info": ("#1f2937", "#e5e7eb"),
            "success": ("#065f46", "#ecfdf3"),
            "error": ("#7f1d1d", "#fee2e2"),
        }
        background, text = palette.get(self._kind, palette["info"])

        container.setStyleSheet(
            f"""
            QFrame#toastContainer {{
                background: {background};
                color: {text};
                border-radius: 10px;
            }}
            QLabel {{
                color: {text};
                font-size: 12px;
            }}
            """
        )
        close_btn.setStyleSheet(
            f"""
            QToolButton {{
                background: rgba(255, 255, 255, 0.12);
                color: {text};
                border: 0px;
                padding: 4px 8px;
                border-radius: 6px;
            }}
            QToolButton:hover {{
                background: rgba(255, 255, 255, 0.2);
            }}
            """
        )

    def show_at_bottom_right(self, margin: int = 24) -> None:
        parent = self.parentWidget()
        self.adjustSize()
        if parent is None:
            self.show()
            return
        frame = parent.frameGeometry()
        x = frame.x() + frame.width() - self.width() - margin
        y = frame.y() + frame.height() - self.height() - margin
        x = max(frame.x() + margin, x)
        y = max(frame.y() + margin, y)
        self.move(x, y)
        self.show()

    def fade_out(self) -> None:
        if self._fade_anim.state() == QtCore.QAbstractAnimation.Running:
            return
        self._fade_anim.start()
