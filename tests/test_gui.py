import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea

import vc726_recovery.gui as gui
from vc726_recovery.constants import RECOVERED_CAMERA_URL


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_recovered_camera_url_is_the_hikvision_setup_address():
    assert RECOVERED_CAMERA_URL == "http://192.168.1.64"


def test_uart_pinout_assets_are_bundled_and_readable():
    _app()
    for filename in ("camera-uart-pinout.jpg", "usb-ttl-adapter-pinout.jpg"):
        path = gui.bundled_asset_path(filename)
        assert path.is_file()
        assert not QPixmap(str(path)).isNull()


def test_uart_pinout_dialog_shows_mapping_and_both_photos():
    _app()
    dialog = gui.UartPinoutDialog()
    try:
        assert "Camera TXD → Adapter RXD" in dialog.mapping_label.text()
        assert "Camera RXD → Adapter TXD" in dialog.mapping_label.text()
        assert "DO NOT CONNECT" in dialog.mapping_label.text()
        assert dialog.pinout_tabs.count() == 2
        for index in range(dialog.pinout_tabs.count()):
            page = dialog.pinout_tabs.widget(index)
            assert isinstance(page, QScrollArea)
            image = page.widget()
            assert isinstance(image, QLabel)
            assert image.pixmap() is not None
            assert not image.pixmap().isNull()
    finally:
        dialog.close()


def test_uart_pinout_button_opens_reference_dialog(monkeypatch):
    _app()
    opened = []
    monkeypatch.setattr(gui.UartPinoutDialog, "exec", lambda self: opened.append(True))
    window = gui.RecoveryWindow()
    try:
        window.pinout_button.click()
    finally:
        window.close()

    assert opened == [True]


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


def test_boot_wait_message_explains_blank_page_and_countdown():
    text = gui.RecoveryWindow._camera_boot_wait_text(60)

    assert "camera login page will not be available" in text
    assert "blank or unavailable page" in text
    assert "open automatically in 60 seconds" in text
    assert RECOVERED_CAMERA_URL in text


def test_completed_boot_wait_closes_prompt_and_opens_camera(monkeypatch):
    _app()
    window = gui.RecoveryWindow()
    calls = []

    class FakeMessage:
        def accept(self):
            calls.append("accepted")

    class FakeTimer:
        def stop(self):
            calls.append("stopped")

    monkeypatch.setattr(window, "_open_camera_setup", lambda: calls.append("opened"))
    try:
        window._finish_camera_boot_wait(FakeMessage(), FakeTimer())
    finally:
        window.close()

    assert calls == ["stopped", "accepted", "opened"]


def test_success_prompt_automatically_opens_after_countdown(monkeypatch):
    _app()
    window = gui.RecoveryWindow()
    opened = []
    monkeypatch.setattr(gui, "POST_FLASH_BOOT_WAIT_SECONDS", 1)
    monkeypatch.setattr(window, "_open_camera_setup", lambda: opened.append(True))
    try:
        window._show_flash_success()
    finally:
        window.close()

    assert opened == [True]
