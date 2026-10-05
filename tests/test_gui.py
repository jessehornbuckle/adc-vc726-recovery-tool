import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import QApplication

import vc726_recovery.gui as gui
from vc726_recovery.constants import (
    HARDWARE_PROFILE_BEGIN,
    HARDWARE_PROFILE_END,
    RECOVERED_CAMERA_URL,
)


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


def test_application_icon_asset_is_bundled_and_readable():
    _app()
    path = gui.bundled_asset_path("app-icon.png")
    assert path.is_file()
    assert not QIcon(str(path)).isNull()


def test_installer_assigned_bootloader_ip_is_displayed_without_gating_hardware():
    _app()
    window = gui.RecoveryWindow()
    try:
        window.hardware_profile = (
            f"{HARDWARE_PROFILE_BEGIN}\n"
            "Micron NAND 128MiB 0x2c 0xf1\n"
            "MAC Address[b8:3a:9d:14:0d:31]\n"
            f"{HARDWARE_PROFILE_END}\n"
        )
        window.transcript = (
            "HKVS # printenv\n"
            "ipaddr=192.168.1.69\n"
            "serverip=192.168.1.128\n"
            "ethaddr=b8:3a:9d:14:0d:31\n"
        )
        window.bootloader_start_index = 0

        window._analyze_fingerprint()

        assert window.fingerprint is not None
        assert window.fingerprint.readonly_gate_passed
        assert window.camera_ip.text() == "192.168.1.69"
        assert "ipaddr" not in window.fingerprint_status.text()
        assert "network setting only" in window.transcript
    finally:
        window.close()


def test_uart_pinout_dialog_shows_mapping_and_both_photos():
    app = _app()
    dialog = gui.UartPinoutDialog()
    try:
        dialog.show()
        app.processEvents()
        assert "Camera TXD → Adapter RXD" in dialog.mapping_label.text()
        assert "Camera RXD → Adapter TXD" in dialog.mapping_label.text()
        assert "DO NOT CONNECT" in dialog.mapping_label.text()
        assert dialog.pinout_tabs.count() == 2
        for index in range(dialog.pinout_tabs.count()):
            page = dialog.pinout_tabs.widget(index)
            assert isinstance(page, gui.PinoutImagePage)
            displayed = page.image_view.image_label.pixmap()
            viewport = page.image_view.viewport().size()
            assert displayed is not None
            assert not displayed.isNull()
            assert displayed.width() <= viewport.width()
            assert displayed.height() <= viewport.height()
            assert page.image_view.fit_to_window
    finally:
        dialog.close()


def test_uart_pinout_photo_can_toggle_between_fitted_and_actual_size():
    app = _app()
    page = gui.PinoutImagePage("usb-ttl-adapter-pinout.jpg")
    try:
        page.resize(900, 600)
        page.show()
        app.processEvents()
        assert page.image_view.fit_to_window

        page.size_button.click()
        app.processEvents()
        displayed = page.image_view.image_label.pixmap()
        assert not page.image_view.fit_to_window
        assert displayed.size() == page.image_view.source_pixmap.size()
        assert page.size_button.text() == "Fit whole photo"

        page.size_button.click()
        app.processEvents()
        displayed = page.image_view.image_label.pixmap()
        viewport = page.image_view.viewport().size()
        assert page.image_view.fit_to_window
        assert displayed.width() <= viewport.width()
        assert displayed.height() <= viewport.height()
    finally:
        page.close()


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


def test_flash_lock_disables_every_main_action_button_and_restores_states():
    _app()
    window = gui.RecoveryWindow()
    try:
        buttons = window._flash_action_buttons()
        previous_states = [button.isEnabled() for button in buttons]

        window._set_flash_controls_locked(True)

        assert window.flash_controls_locked
        assert all(not button.isEnabled() for button in buttons)

        window._set_flash_controls_locked(False)

        assert not window.flash_controls_locked
        assert [button.isEnabled() for button in buttons] == previous_states
    finally:
        window._set_flash_controls_locked(False)
        window.close()


def test_flash_lock_stays_active_until_terminal_update_outcome(monkeypatch):
    _app()
    window = gui.RecoveryWindow()
    monkeypatch.setattr(window, "_show_flash_success", lambda: None)
    try:
        window._set_flash_controls_locked(True)
        window.destructive_stage = "update"
        window.destructive_start_index = 0
        window.transcript = "firmware transfer still running"

        window._check_update_outcome()

        assert window.flash_controls_locked
        assert all(not button.isEnabled() for button in window._flash_action_buttons())

        window.transcript += "\nWrite Flash [OK]\nUPDATE COMPLETE\n"
        window._check_update_outcome()

        assert not window.flash_controls_locked
        assert window.flash_succeeded
        assert not window.flash_button.isEnabled()
        assert window.camera_login_button.isEnabled()
    finally:
        window._set_flash_controls_locked(False)
        window.close()


def test_flash_lock_releases_after_a_confirmed_stopped_state():
    _app()
    window = gui.RecoveryWindow()
    try:
        window._set_flash_controls_locked(True)
        window.destructive_stage = "update"
        window.destructive_start_index = 0
        window.transcript = "failed: short write /dav/IElang.tar"

        window._check_update_outcome()

        assert not window.flash_controls_locked
        assert window.destructive_blocked
        assert not window.flash_button.isEnabled()
        assert "short-write" in window.status_label.text()
    finally:
        window._set_flash_controls_locked(False)
        window.close()


def test_window_close_is_blocked_while_flash_controls_are_locked(monkeypatch):
    _app()
    window = gui.RecoveryWindow()
    warnings = []
    monkeypatch.setattr(
        gui.QMessageBox,
        "warning",
        lambda *args: warnings.append(args[2]),
    )
    try:
        window._set_flash_controls_locked(True)
        event = QCloseEvent()

        window.closeEvent(event)

        assert not event.isAccepted()
        assert warnings
        assert "locked until" in warnings[0]
    finally:
        window._set_flash_controls_locked(False)
        window.close()


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
