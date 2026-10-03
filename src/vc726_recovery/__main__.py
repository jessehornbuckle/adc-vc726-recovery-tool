"""Application entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .constants import APP_NAME
from .gui import RecoveryWindow, apply_dark_mode_if_requested


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("VC726 Recovery Project")
    apply_dark_mode_if_requested(app)
    window = RecoveryWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
