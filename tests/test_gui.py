import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import vc726_recovery.gui as gui
from vc726_recovery.constants import RECOVERED_CAMERA_URL


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_recovered_camera_url_is_the_hikvision_setup_address():
    assert RECOVERED_CAMERA_URL == "http://192.168.1.64"


def test_success_state_keeps_camera_login_action_available():
    _app()
    window = gui.RecoveryWindow()
    try:
        assert window.camera_login_button.isHidden()

        window.flash_succeeded = True
        window._update_gate()

        assert not window.camera_login_button.isHidden()
        assert window.camera_login_button.isEnabled()
        assert RECOVERED_CAMERA_URL in window.blockers_label.text()
    finally:
        window.close()


def test_camera_login_action_opens_exact_recovered_address(monkeypatch):
    _app()
    opened = []

    class FakeDesktopServices:
        @staticmethod
        def openUrl(url):  # noqa: N802 (Qt API)
            opened.append(url.toString())
            return True

    monkeypatch.setattr(gui, "QDesktopServices", FakeDesktopServices)
    window = gui.RecoveryWindow()
    try:
        window._open_camera_setup()
    finally:
        window.close()

    assert opened == [RECOVERED_CAMERA_URL]
