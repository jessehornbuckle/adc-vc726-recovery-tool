"""Simple guarded desktop GUI for the ADC-VC726 recovery workflow."""

from __future__ import annotations

import os
import socket
import sys
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from serial import SerialException

from .constants import (
    APP_NAME,
    APP_VERSION,
    EXPECTED_BOARD,
    EXPECTED_FIRMWARE_SHA256,
    EXPECTED_MODEL,
    EXPECTED_NAND,
    EXPECTED_SERVER_IP,
    EXPECTED_SOC,
    FIRMWARE_SOURCE_URL,
    FLASH_COMMAND,
    FORMAT_COMMAND,
    FORMAT_HELP_COMMAND,
    FORMAT_PARTITIONS,
    HARDWARE_PROFILE_BEGIN,
    HARDWARE_PROFILE_END,
    LINUX_HELP_COMMAND,
    LINUX_REBOOT_COMMAND,
    RISK_PHRASE,
    SERIAL_BAUDRATE,
    SUPPORTED_CAMERA_IPS,
    TFTP_PORT,
)
from .fingerprint import (
    FingerprintAnalyzer,
    FingerprintReport,
    UpdateOutcome,
    classify_update_output,
    find_protected_shell_prompt,
)
from .firmware import FirmwareReport, verify_firmware
from .format_workflow import (
    FormatHelpOutcome,
    FormatRunOutcome,
    LinuxRebootHelpOutcome,
    classify_format_help,
    classify_format_run,
    classify_linux_reboot_help,
)
from .network import NetworkSetupError
from .privileged_tftp import PrivilegedMacTftpServer
from .safety import ManualConfirmations, SafetyGate
from .serial_console import SerialConsole, available_ports
from .tftp import SingleFileTftpServer


class EventBridge(QObject):
    serial_text = Signal(str)
    serial_error = Signal(str)
    serial_closed = Signal()
    tftp_log = Signal(str)
    tftp_progress = Signal(int, int)
    firmware_done = Signal(object)
    firmware_error = Signal(str)


class RecoveryWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — {APP_VERSION}")
        self.resize(980, 720)

        self.bridge = EventBridge()
        self.bridge.serial_text.connect(self._append_serial)
        self.bridge.serial_error.connect(self._serial_error)
        self.bridge.serial_closed.connect(self._serial_closed)
        self.bridge.tftp_log.connect(self._append_system)
        self.bridge.tftp_progress.connect(self._tftp_progress)
        self.bridge.firmware_done.connect(self._firmware_verified)
        self.bridge.firmware_error.connect(self._firmware_failed)

        self.serial = SerialConsole(
            self.bridge.serial_text.emit,
            self.bridge.serial_error.emit,
            self.bridge.serial_closed.emit,
        )
        self.tftp: SingleFileTftpServer | PrivilegedMacTftpServer | None = None
        self.firmware: FirmwareReport | None = None
        self.fingerprint: FingerprintReport | None = None
        self.transcript = ""
        self.log_path: Path | None = None
        self.hardware_profile = ""
        self.hardware_profile_path: Path | None = None
        self.capture_start_index: int | None = None
        self.bootloader_start_index: int | None = None
        self.power_cycle_seconds = 0
        self.power_cycle_ready = False
        self.destructive_stage: str | None = None
        self.destructive_start_index: int | None = None
        self.destructive_blocked = False
        self.flash_succeeded = False

        self._build_ui()
        self._refresh_ports()
        self._update_gate()

        self.outcome_timer = QTimer(self)
        self.outcome_timer.setInterval(1000)
        self.outcome_timer.timeout.connect(self._check_update_outcome)
        self.outcome_timer.start()

        self.capture_timer = QTimer(self)
        self.capture_timer.setInterval(200)
        self.capture_timer.timeout.connect(self._check_hardware_capture)

        self.power_cycle_timer = QTimer(self)
        self.power_cycle_timer.setInterval(1000)
        self.power_cycle_timer.timeout.connect(self._power_cycle_tick)

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        title = QLabel(APP_NAME)
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        warning = QLabel(
            "⚠ This writes firmware to NAND and can permanently brick a camera. "
            "Version 0.1 supports only the exact verified ADC-VC726 hardware listed below."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "QLabel { background:#7a2e00; color:white; padding:10px; border-radius:6px; }"
        )
        layout.addWidget(warning)

        self.status_label = QLabel("Not ready")
        self.status_label.setStyleSheet("font-weight:600; padding:4px;")
        layout.addWidget(self.status_label)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_prepare_tab(), "1. Prepare")
        self.tabs.addTab(self._build_console_tab(), "2. Serial console")
        self.tabs.addTab(self._build_flash_tab(), "3. Transfer & flash")
        layout.addWidget(self.tabs, 1)

        self.setCentralWidget(root)

    def _build_prepare_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        hardware = QGroupBox("Verified hardware — physically inspect the camera")
        hardware_layout = QVBoxLayout(hardware)
        self.confirm_ownership = QCheckBox("I own this camera or have permission to modify it")
        self.confirm_model = QCheckBox(f"Product label is exactly {EXPECTED_MODEL}")
        self.confirm_board = QCheckBox(f"Main board is exactly {EXPECTED_BOARD}")
        self.confirm_components = QCheckBox(
            f"Processor is {EXPECTED_SOC} and NAND is {EXPECTED_NAND}"
        )
        self.confirm_risk = QCheckBox("I understand that the camera can be permanently bricked")
        for checkbox in (
            self.confirm_ownership,
            self.confirm_model,
            self.confirm_board,
            self.confirm_components,
            self.confirm_risk,
        ):
            checkbox.toggled.connect(self._update_gate)
            hardware_layout.addWidget(checkbox)
        layout.addWidget(hardware)

        firmware_group = QGroupBox("Firmware image")
        firmware_layout = QGridLayout(firmware_group)
        self.firmware_path = QLineEdit()
        self.firmware_path.setReadOnly(True)
        browse = QPushButton("Choose digicap.dav…")
        browse.clicked.connect(self._choose_firmware)
        self.firmware_status = QLabel("No firmware selected")
        self.firmware_status.setWordWrap(True)
        firmware_layout.addWidget(self.firmware_path, 0, 0)
        firmware_layout.addWidget(browse, 0, 1)
        firmware_layout.addWidget(self.firmware_status, 1, 0, 1, 2)
        firmware_layout.addWidget(
            QLabel(f"Required SHA-256: {EXPECTED_FIRMWARE_SHA256}"), 2, 0, 1, 2
        )
        layout.addWidget(firmware_group)

        note = QLabel(
            "Firmware is not bundled. Download the official Hikvision G1 "
            "IPC_G1_EN_STD_5.5.82_181211 package and select its digicap.dav file."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        firmware_download = QPushButton("Open official firmware download page")
        firmware_download.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(FIRMWARE_SOURCE_URL))
        )
        firmware_download.setToolTip(
            "Opens Hikvision Europe's V5.5.82_Build181211 download page in your browser"
        )
        layout.addWidget(firmware_download)
        layout.addStretch()
        return page

    def _build_console_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        connection = QGroupBox("3.3 V UART — 115200 8-N-1")
        connection_layout = QHBoxLayout(connection)
        self.port_combo = QComboBox()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh_ports)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self._toggle_serial)
        connection_layout.addWidget(self.port_combo, 1)
        connection_layout.addWidget(refresh)
        connection_layout.addWidget(self.connect_button)
        layout.addWidget(connection)

        cable_warning = QLabel(
            "Connect GND, camera TX → adapter RX, and camera RX → adapter TX. "
            "Leave both VCC/3.3 V supply pins disconnected; power the camera by PoE."
        )
        cable_warning.setWordWrap(True)
        cable_warning.setStyleSheet("color:#b54500; font-weight:600;")
        layout.addWidget(cable_warning)

        controls = QGridLayout()
        self.capture_button = QPushButton("1. Capture and save hardware profile")
        self.capture_button.clicked.connect(self._capture_hardware_profile)
        self.capture_button.setEnabled(False)
        self.interrupt_button = QPushButton("2. Start Ctrl+U boot-interrupt window")
        self.interrupt_button.clicked.connect(self._interrupt_boot)
        self.interrupt_button.setEnabled(False)
        self.probe_button = QPushButton("3. Verify read-only fingerprint")
        self.probe_button.clicked.connect(self._run_probe)
        self.probe_button.setEnabled(False)
        save_log = QPushButton("Save log…")
        save_log.clicked.connect(self._save_log_as)
        controls.addWidget(self.capture_button, 0, 0)
        controls.addWidget(self.interrupt_button, 0, 1)
        controls.addWidget(self.probe_button, 0, 2)
        controls.addWidget(save_log, 0, 3)
        layout.addLayout(controls)

        self.workflow_status = QLabel(
            "Step 1: Let the camera boot normally, then capture its hardware profile."
        )
        self.workflow_status.setWordWrap(True)
        self.workflow_status.setStyleSheet("font-weight:600;")
        layout.addWidget(self.workflow_status)

        self.fingerprint_status = QLabel("No bootloader fingerprint collected")
        self.fingerprint_status.setWordWrap(True)
        layout.addWidget(self.fingerprint_status)

        self.terminal = QPlainTextEdit()
        self.terminal.setReadOnly(True)
        terminal_font = QFont("Menlo")
        terminal_font.setStyleHint(QFont.StyleHint.Monospace)
        terminal_font.setPointSize(10)
        self.terminal.setFont(terminal_font)
        self.terminal.setPlaceholderText("Serial boot output will appear here…")
        layout.addWidget(self.terminal, 1)
        return page

    def _build_flash_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        server_group = QGroupBox("Single-file TFTP server")
        server_form = QFormLayout(server_group)
        self.server_ip = QLineEdit(EXPECTED_SERVER_IP)
        self.server_ip.setToolTip("Must match U-Boot serverip and be assigned to this computer")
        self.camera_ip = QLineEdit("Detected after fingerprint check")
        self.camera_ip.setReadOnly(True)
        self.tftp_button = QPushButton("Start verified TFTP server")
        self.tftp_button.clicked.connect(self._toggle_tftp)
        self.tftp_status = QLabel("Stopped")
        self.transfer_progress = QProgressBar()
        self.transfer_progress.setRange(0, 1000)
        self.transfer_progress.setValue(0)
        server_form.addRow("This computer:", self.server_ip)
        server_form.addRow("Camera bootloader:", self.camera_ip)
        server_form.addRow(self.tftp_button, self.tftp_status)
        server_form.addRow("Transfer:", self.transfer_progress)
        layout.addWidget(server_group)

        network_note = QLabel(
            "On macOS, Start automatically finds the camera-facing network adapter and "
            "temporarily assigns 192.168.1.128/24. macOS will ask for an administrator "
            "password. The app removes the temporary address when TFTP stops."
        )
        network_note.setWordWrap(True)
        layout.addWidget(network_note)

        gate_group = QGroupBox("Write safety gate")
        gate_layout = QVBoxLayout(gate_group)
        self.blockers_label = QLabel()
        self.blockers_label.setWordWrap(True)
        gate_layout.addWidget(self.blockers_label)
        self.flash_button = QPushButton("Format app/config partitions, then flash")
        self.flash_button.setMinimumHeight(46)
        self.flash_button.clicked.connect(self._flash)
        gate_layout.addWidget(self.flash_button)
        layout.addWidget(gate_group)

        format_warning = QLabel(
            "Before flashing, the app asks U-Boot what its format command erases. It proceeds "
            "only if U-Boot reports exactly app_pri, app_sec, cfg_pri, and cfg_sec, then waits "
            "for format to finish. It safely checks whether Linux supports reboot, catches "
            "U-Boot automatically, and then sends the verified firmware update command."
        )
        format_warning.setWordWrap(True)
        format_warning.setStyleSheet("color:#b54500;")
        layout.addWidget(format_warning)
        layout.addStretch()
        return page

    def _choose_firmware(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select verified Hikvision firmware",
            str(Path.home()),
            "Hikvision firmware (digicap.dav);;All files (*)",
        )
        if not path:
            return
        self.firmware_path.setText(path)
        self.firmware_status.setText("Calculating SHA-256…")
        self.firmware_status.setStyleSheet("")
        threading.Thread(target=self._verify_firmware_worker, args=(path,), daemon=True).start()

    def _verify_firmware_worker(self, path: str) -> None:
        try:
            report = verify_firmware(path)
        except (OSError, ValueError) as exc:
            self.bridge.firmware_error.emit(str(exc))
            return
        self.bridge.firmware_done.emit(report)

    def _firmware_verified(self, report: FirmwareReport) -> None:
        self.firmware = report
        self.firmware_status.setText(
            f"{'✓' if report.valid else '✗'} {report.summary}\n"
            f"Size: {report.size:,} bytes\nSHA-256: {report.sha256}"
        )
        self.firmware_status.setStyleSheet("color:#187a2f;" if report.valid else "color:#b00020;")
        self._append_system(f"Firmware check: {report.summary}")
        self._update_gate()

    def _firmware_failed(self, message: str) -> None:
        self.firmware = None
        self.firmware_status.setText(f"Firmware verification failed: {message}")
        self.firmware_status.setStyleSheet("color:#b00020;")
        self._update_gate()

    def _refresh_ports(self) -> None:
        previous = self.port_combo.currentData()
        self.port_combo.clear()
        for device, description in available_ports():
            self.port_combo.addItem(f"{device} — {description}", device)
        if previous:
            index = self.port_combo.findData(previous)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
        if self.port_combo.count() == 0:
            self.port_combo.addItem("No serial adapters found", None)

    def _toggle_serial(self) -> None:
        if self.serial.connected:
            self.serial.disconnect()
            self._serial_closed()
            return
        port = self.port_combo.currentData()
        if not port:
            QMessageBox.warning(self, "No adapter", "Connect a USB-to-UART adapter and refresh.")
            return
        try:
            self.serial.connect(port)
        except (OSError, SerialException) as exc:
            QMessageBox.critical(self, "Serial connection failed", str(exc))
            return
        self.connect_button.setText("Disconnect")
        self.capture_button.setEnabled(True)
        self._append_system(f"Connected to {port} at {SERIAL_BAUDRATE} 8-N-1")
        self._update_gate()

    def _serial_closed(self) -> None:
        self.connect_button.setText("Connect")
        if hasattr(self, "capture_button"):
            self.capture_button.setEnabled(False)
            self.interrupt_button.setEnabled(False)
            self.probe_button.setEnabled(False)
        self._update_gate()

    def _serial_error(self, message: str) -> None:
        self._append_system(f"Serial error: {message}")
        QMessageBox.critical(self, "Serial error", message)
        self._serial_closed()

    def _interrupt_boot(self) -> None:
        if not self.serial.connected:
            QMessageBox.warning(self, "Serial disconnected", "Connect the serial console first.")
            return
        self.interrupt_button.setEnabled(False)
        self.bootloader_start_index = len(self.transcript)
        self.interrupt_button.setText("2. Sending Ctrl+U — reconnect PoE now…")
        self.workflow_status.setText(
            "Reconnect Ethernet/PoE now. Ctrl+U will continue until HKVS # appears."
        )
        self._append_system(
            "Sending Ctrl+U for up to 12 seconds; apply PoE now. "
            "The window stops automatically at HKVS #."
        )
        threading.Thread(target=self.serial.interrupt_boot, daemon=True).start()
        QTimer.singleShot(12_500, self._reset_interrupt_button)

    def _reset_interrupt_button(self) -> None:
        self.interrupt_button.setEnabled(
            self.serial.connected and self.power_cycle_ready and bool(self.hardware_profile)
        )
        self.interrupt_button.setText("2. Start Ctrl+U boot-interrupt window")

    def _capture_hardware_profile(self) -> None:
        if not self.serial.connected:
            QMessageBox.warning(self, "Serial disconnected", "Connect the serial console first.")
            return
        if "HKVS #" in self.transcript[-256:].upper():
            QMessageBox.warning(
                self,
                "Camera is in U-Boot",
                "Step 1 runs from the normal Linux # prompt. Power-cycle the camera and let "
                "it finish booting normally before capturing the hardware profile.",
            )
            return
        self.hardware_profile = ""
        self.hardware_profile_path = None
        self.fingerprint = None
        self.power_cycle_ready = False
        self.capture_button.setEnabled(False)
        self.interrupt_button.setEnabled(False)
        self.probe_button.setEnabled(False)
        self._append_system(
            "Step 1: capturing read-only Linux hardware evidence with dmesg"
        )
        self.capture_start_index = len(self.transcript)
        self.workflow_status.setText("Capturing hardware profile…")
        threading.Thread(target=self.serial.capture_hardware_profile, daemon=True).start()
        self.capture_timer.start()
        QTimer.singleShot(30_000, self._hardware_capture_timeout)

    def _check_hardware_capture(self) -> None:
        if self.capture_start_index is None:
            self.capture_timer.stop()
            return
        captured = self.transcript[self.capture_start_index :]
        returned_prompt = find_protected_shell_prompt(captured)
        if returned_prompt is None:
            return
        self.capture_timer.stop()
        shell_output = captured[: returned_prompt.end()]
        self.hardware_profile = (
            f"{HARDWARE_PROFILE_BEGIN}\n{shell_output}\n{HARDWARE_PROFILE_END}\n"
        )
        self.capture_start_index = None

        preliminary = FingerprintAnalyzer.analyze("", self.hardware_profile)
        if not (preliminary.soc or preliminary.nand) or "hardware_mac" not in preliminary.evidence:
            self.capture_button.setEnabled(self.serial.connected)
            self.workflow_status.setText(
                "Hardware capture did not contain the required platform and MAC evidence."
            )
            QMessageBox.warning(
                self,
                "Hardware evidence not found",
                "The read-only commands finished, but the expected Ambarella S3L or Micron "
                "NAND evidence and camera MAC were not both found. No write controls were "
                "unlocked.",
            )
            return

        try:
            self.hardware_profile_path = self._save_hardware_profile(self.hardware_profile)
        except OSError as exc:
            self.capture_button.setEnabled(self.serial.connected)
            self.workflow_status.setText(
                "Hardware captured, but the evidence file could not be saved."
            )
            QMessageBox.critical(self, "Unable to save hardware profile", str(exc))
            return

        self._append_system(f"Hardware profile saved to {self.hardware_profile_path}")
        self.workflow_status.setText(
            f"Step 1 complete. Evidence saved to {self.hardware_profile_path}"
        )
        QMessageBox.information(
            self,
            "Step 1 complete — unplug PoE",
            f"The hardware profile was captured and saved to:\n\n{self.hardware_profile_path}\n\n"
            "Unplug the camera's Ethernet/PoE cable now, then click OK. "
            "The app will count down a 10-second power-off wait.",
        )
        self.power_cycle_seconds = 10
        self.workflow_status.setText(
            "Keep Ethernet/PoE unplugged — power-off wait: 10 seconds remaining."
        )
        self.power_cycle_timer.start()

    def _hardware_capture_timeout(self) -> None:
        if self.capture_start_index is None:
            return
        self.capture_timer.stop()
        self.capture_start_index = None
        self.capture_button.setEnabled(self.serial.connected)
        self.workflow_status.setText("Hardware capture timed out; no evidence was accepted.")
        QMessageBox.warning(
            self,
            "Hardware capture timed out",
            "The camera did not return the complete read-only hardware profile. Confirm it is "
            "fully booted at the Linux # prompt and try Step 1 again.",
        )

    def _save_hardware_profile(self, profile: str) -> Path:
        folder = Path.home() / "Documents" / "ADC-VC726 Recovery Logs"
        folder.mkdir(parents=True, exist_ok=True)
        report = FingerprintAnalyzer.analyze("", profile)
        mac = report.evidence.get("hardware_mac", "unknown-mac").replace(":", "-")
        path = folder / f"ADC-VC726-hardware-{mac}-{datetime.now():%Y%m%d-%H%M%S}.log"
        path.write_text(profile, encoding="utf-8")
        return path

    def _power_cycle_tick(self) -> None:
        self.power_cycle_seconds -= 1
        if self.power_cycle_seconds > 0:
            self.workflow_status.setText(
                "Keep Ethernet/PoE unplugged — power-off wait: "
                f"{self.power_cycle_seconds} seconds remaining."
            )
            return
        self.power_cycle_timer.stop()
        if self.destructive_stage == "format_poweroff":
            self._begin_post_format_interrupt()
            return
        self.power_cycle_ready = True
        self.interrupt_button.setEnabled(self.serial.connected)
        self.workflow_status.setText(
            "Power-off wait complete. Click Step 2 first, then reconnect Ethernet/PoE "
            "when the button tells you."
        )
        QMessageBox.information(
            self,
            "Ready for Step 2",
            "Keep PoE unplugged. Click “2. Start Ctrl+U boot-interrupt window,” then "
            "reconnect Ethernet/PoE when the button says to do so.",
        )

    def _run_probe(self) -> None:
        if not self.serial.connected:
            QMessageBox.warning(self, "Serial disconnected", "Connect the serial console first.")
            return
        if not self.hardware_profile:
            QMessageBox.warning(
                self,
                "Hardware profile missing",
                "Complete Step 1 and save the hardware profile before checking U-Boot.",
            )
            return
        bootloader_transcript = (
            self.transcript[self.bootloader_start_index :]
            if self.bootloader_start_index is not None
            else ""
        )
        if "HKVS #" not in bootloader_transcript.upper():
            QMessageBox.warning(
                self,
                "Bootloader prompt not seen",
                "Interrupt startup and wait for the HKVS # prompt before probing.",
            )
            return
        self._append_system("Running read-only U-Boot commands: help and printenv")
        threading.Thread(target=self.serial.run_readonly_probe, daemon=True).start()
        QTimer.singleShot(1800, self._analyze_fingerprint)

    def _analyze_fingerprint(self) -> None:
        bootloader_transcript = (
            self.transcript[self.bootloader_start_index :]
            if self.bootloader_start_index is not None
            else ""
        )
        self.fingerprint = FingerprintAnalyzer.analyze(
            bootloader_transcript, self.hardware_profile
        )
        report = self.fingerprint
        rows = [
            ("saved hardware profile", report.profile_captured),
            ("HKVS prompt", report.prompt),
            ("S3L33M/Ambarella evidence", report.soc),
            ("Micron NAND evidence", report.nand),
            ("sensor 0x3013/type 42", report.sensor),
            (f"ipaddr in {', '.join(SUPPORTED_CAMERA_IPS)}", report.camera_ip),
            (f"serverip={EXPECTED_SERVER_IP}", report.server_ip),
            ("captured MAC matches U-Boot ethaddr", report.mac_match),
        ]
        text = "  |  ".join(f"{'✓' if good else '✗'} {name}" for name, good in rows)
        self.fingerprint_status.setText(text)
        self.fingerprint_status.setStyleSheet(
            "color:#187a2f;" if report.readonly_gate_passed else "color:#b00020;"
        )
        self._append_system(
            f"Fingerprint: {report.matched_count}/8 indicators; "
            f"read-only gate {'passed' if report.readonly_gate_passed else 'blocked'}"
        )
        if report.camera_ip:
            detected = report.evidence["camera_ip"].partition("=")[2].strip()
            self.camera_ip.setText(detected)
        self._update_gate()

    def _toggle_tftp(self) -> None:
        if self.tftp:
            if self.tftp.running:
                self.tftp.stop()
                self.tftp = None
                self.tftp_button.setText("Start verified TFTP server")
                self.tftp_status.setText("Stopped")
                self._update_gate()
                return
            self.tftp.stop()
            self.tftp = None
        if not self.firmware or not self.firmware.valid:
            QMessageBox.warning(
                self, "Firmware not verified", "Verify the exact firmware image first."
            )
            return
        host = self.server_ip.text().strip()
        try:
            socket.inet_aton(host)
        except OSError:
            QMessageBox.warning(self, "Invalid address", "Enter a valid IPv4 address.")
            return
        if sys.platform == "darwin":
            server = PrivilegedMacTftpServer(
                host,
                TFTP_PORT,
                self.firmware.path,
                self.camera_ip.text().strip(),
                progress=self.bridge.tftp_progress.emit,
                log=self.bridge.tftp_log.emit,
            )
        else:
            server = SingleFileTftpServer(
                host,
                TFTP_PORT,
                self.firmware.path,
                progress=self.bridge.tftp_progress.emit,
                log=self.bridge.tftp_log.emit,
            )
        try:
            server.start()
        except NetworkSetupError as exc:
            QMessageBox.critical(self, "Network setup failed", str(exc))
            return
        except PermissionError:
            QMessageBox.critical(
                self,
                "Port 69 requires permission",
                "The operating system denied UDP port 69. No TFTP server was left running.",
            )
            return
        except OSError as exc:
            QMessageBox.critical(
                self,
                "TFTP server failed",
                f"{exc}\n\nConfirm that {host} is assigned to this computer and port 69 is free.",
            )
            return
        self.tftp = server
        self.tftp_button.setText("Stop TFTP server")
        self.tftp_status.setText(f"Listening on {host}:{TFTP_PORT}")
        self._update_gate()

    def _tftp_progress(self, done: int, total: int) -> None:
        value = int(done * 1000 / total) if total else 0
        self.transfer_progress.setValue(min(value, 1000))
        self.transfer_progress.setFormat(f"{done:,} / {total:,} bytes (%p%)")

    def _manual_confirmations(self) -> ManualConfirmations:
        return ManualConfirmations(
            owns_device=self.confirm_ownership.isChecked(),
            model=self.confirm_model.isChecked(),
            board=self.confirm_board.isChecked(),
            components=self.confirm_components.isChecked(),
            accepts_brick_risk=self.confirm_risk.isChecked(),
        )

    def _gate(self) -> SafetyGate:
        return SafetyGate(
            firmware=self.firmware,
            fingerprint=self.fingerprint,
            confirmations=self._manual_confirmations(),
            tftp_running=bool(self.tftp and self.tftp.running),
            serial_connected=self.serial.connected,
        )

    def _update_gate(self) -> None:
        if not hasattr(self, "flash_button"):
            return
        gate = self._gate()
        self.flash_button.setEnabled(gate.ready and not self.destructive_blocked)
        if self.flash_succeeded:
            self.flash_button.setEnabled(False)
            self.status_label.setText("✓ FLASH SUCCESSFUL — camera rebooting into Hikvision")
            self.status_label.setStyleSheet("color:#187a2f; font-weight:700; padding:4px;")
            self.blockers_label.setText(
                "Firmware writing completed successfully. Let the camera finish its first "
                "boot before disconnecting power."
            )
        elif self.destructive_blocked:
            self.status_label.setText("STOPPED — destructive sequence halted")
            self.status_label.setStyleSheet("color:#b00020; font-weight:700; padding:4px;")
            self.blockers_label.setText(
                "The format/flash safety sequence stopped. Save the serial log and stop."
            )
        elif gate.ready:
            self.status_label.setText("✓ All safety gates passed — ready to format and flash")
            self.status_label.setStyleSheet("color:#187a2f; font-weight:700; padding:4px;")
            self.blockers_label.setText(
                "All automatic and manual checks passed. Keep PoE and Ethernet stable "
                "during the write."
            )
        else:
            self.status_label.setText("Not ready — no write command can be sent")
            self.status_label.setStyleSheet("color:#b00020; font-weight:700; padding:4px;")
            self.blockers_label.setText("Still required:\n• " + "\n• ".join(gate.blockers()))

    def _flash(self) -> None:
        gate = self._gate()
        if not gate.ready:
            QMessageBox.warning(self, "Safety gate blocked", "\n".join(gate.blockers()))
            return
        phrase, accepted = QInputDialog.getText(
            self,
            "Final destructive-action confirmation",
            "This sequence erases the four application/config partitions, then writes firmware "
            "to NAND. Do not disconnect power.\n\n"
            f"Type exactly: {RISK_PHRASE}",
        )
        if not accepted or phrase.strip() != RISK_PHRASE:
            self._append_system("Flash cancelled at final confirmation")
            return
        answer = QMessageBox.question(
            self,
            "Format and flash this camera?",
            "The app will first verify that U-Boot's format command targets only:\n\n"
            f"{', '.join(FORMAT_PARTITIONS)}\n\n"
            f"It will then run `{FORMAT_COMMAND}`, use a verified software reboot when this "
            f"Linux shell supports it, catch U-Boot, and send `{FLASH_COMMAND}`. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.flash_button.setEnabled(False)
        self.tabs.setCurrentIndex(1)
        self._start_destructive_stage(
            "format_help",
            FORMAT_HELP_COMMAND,
            "FORMAT PREFLIGHT: verifying U-Boot's exact format targets",
        )

    def _start_destructive_stage(self, stage: str, command: str, message: str) -> None:
        self._append_system(message)
        self.destructive_stage = stage
        self.destructive_start_index = len(self.transcript)
        stage_labels = {
            "format_help": "Checking U-Boot's exact format targets…",
            "format_run": "FORMATTING app/config partitions — do not power off",
            "linux_help": "FORMAT COMPLETE — checking safe software reboot support…",
            "update": "TRANSFERRING AND WRITING firmware — do not power off",
        }
        self.status_label.setText(stage_labels[stage])
        self.status_label.setStyleSheet("color:#b54500; font-weight:700; padding:4px;")
        try:
            self.serial.send_line(command)
        except (OSError, RuntimeError) as exc:
            self.destructive_stage = None
            self.destructive_start_index = None
            QMessageBox.critical(self, "Unable to send command", str(exc))
            self._update_gate()

    def _block_destructive_sequence(self, message: str) -> None:
        self.destructive_stage = None
        self.destructive_start_index = None
        self.destructive_blocked = True
        self._append_system(f"STOPPED: {message}")
        self._update_gate()
        QMessageBox.critical(self, "Format safety check stopped", message)

    def _begin_software_reboot(self) -> None:
        self._append_system(
            "LINUX REBOOT PREFLIGHT PASSED: protected shell advertises reboot\n"
            f"SENDING REBOOT COMMAND: {LINUX_REBOOT_COMMAND}"
        )
        self.destructive_stage = "awaiting_uboot"
        self.destructive_start_index = len(self.transcript)
        self.bootloader_start_index = self.destructive_start_index
        self.status_label.setText("REBOOTING — catching HKVS # automatically")
        self.status_label.setStyleSheet("color:#b54500; font-weight:700; padding:4px;")
        try:
            self.serial.send_line(LINUX_REBOOT_COMMAND)
        except (OSError, RuntimeError) as exc:
            self._block_destructive_sequence(f"Unable to send Linux reboot command: {exc}")
            return
        threading.Thread(
            target=self.serial.interrupt_boot,
            kwargs={"attempts": 300},
            daemon=True,
        ).start()
        QTimer.singleShot(30_500, self._post_format_interrupt_timeout)

    def _begin_post_format_power_cycle(self) -> None:
        self.destructive_stage = "format_poweroff"
        self.destructive_start_index = None
        self.status_label.setText("FORMAT COMPLETE — unplug PoE for the guided reboot")
        self.status_label.setStyleSheet("color:#b54500; font-weight:700; padding:4px;")
        self._append_system(
            "FORMAT COMPLETE: software reboot is not advertised. A controlled PoE power "
            "cycle is required to return to U-Boot."
        )
        QMessageBox.information(
            self,
            "Format complete — unplug PoE",
            "Formatting completed successfully, but this protected shell does not advertise "
            "a software reboot command.\n\nUnplug Ethernet/PoE now, then click OK. The app "
            "will enforce a 10-second power-off wait and tell you when to reconnect it.",
        )
        self.power_cycle_seconds = 10
        self.workflow_status.setText(
            "Keep Ethernet/PoE unplugged — post-format wait: 10 seconds remaining."
        )
        self.power_cycle_timer.start()

    def _begin_post_format_interrupt(self) -> None:
        self._append_system(
            "Post-format power-off wait complete. Sending Ctrl+U for up to 30 seconds; "
            "reconnect PoE now."
        )
        self.destructive_stage = "awaiting_uboot"
        self.destructive_start_index = len(self.transcript)
        self.bootloader_start_index = self.destructive_start_index
        self.status_label.setText("RECONNECT PoE NOW — catching HKVS # automatically")
        self.status_label.setStyleSheet("color:#b54500; font-weight:700; padding:4px;")
        threading.Thread(
            target=self.serial.interrupt_boot,
            kwargs={"attempts": 300},
            daemon=True,
        ).start()
        QMessageBox.information(
            self,
            "Reconnect PoE now",
            "Reconnect Ethernet/PoE now. The app is sending Ctrl+U and will automatically "
            "send the verified firmware update when HKVS # appears.",
        )
        QTimer.singleShot(30_500, self._post_format_interrupt_timeout)

    def _post_format_interrupt_timeout(self) -> None:
        if self.destructive_stage != "awaiting_uboot":
            return
        self._block_destructive_sequence(
            "HKVS # was not detected during the post-format Ctrl+U window. The firmware "
            "update was not sent. Keep the serial log and return the camera to U-Boot before "
            "trying again."
        )

    def _append_serial(self, text: str) -> None:
        self.transcript += text
        if len(self.transcript) > 2_000_000:
            self.transcript = self.transcript[-2_000_000:]
        cursor = self.terminal.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text)
        self.terminal.setTextCursor(cursor)
        self.terminal.ensureCursorVisible()
        if (
            self.bootloader_start_index is not None
            and "HKVS #" in self.transcript[-128:].upper()
        ):
            self._reset_interrupt_button()
            if self.hardware_profile:
                self.probe_button.setEnabled(True)
                self.workflow_status.setText(
                    "HKVS # detected. Click Step 3 to combine the saved hardware profile "
                    "with the live bootloader settings."
                )

    def _append_system(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self._append_serial(f"\n[assistant {stamp}] {message}\n")

    def _check_update_outcome(self) -> None:
        if self.destructive_stage is None or self.destructive_start_index is None:
            return
        stage_output = self.transcript[self.destructive_start_index :]
        if self.destructive_stage == "format_help":
            help_outcome = classify_format_help(stage_output)
            if help_outcome == FormatHelpOutcome.VERIFIED:
                self._start_destructive_stage(
                    "format_run",
                    FORMAT_COMMAND,
                    "FORMAT PREFLIGHT PASSED: exact targets are "
                    + ", ".join(FORMAT_PARTITIONS)
                    + f"\nSENDING DESTRUCTIVE COMMAND: {FORMAT_COMMAND}",
                )
            elif help_outcome in {FormatHelpOutcome.MISMATCH, FormatHelpOutcome.ERROR}:
                self._block_destructive_sequence(
                    "U-Boot did not report exactly app_pri, app_sec, cfg_pri, and cfg_sec. "
                    "The app did not send format or the firmware update."
                )
            return
        if self.destructive_stage == "format_run":
            format_outcome = classify_format_run(stage_output)
            if format_outcome == FormatRunOutcome.REBOOT_REQUIRED:
                self._start_destructive_stage(
                    "linux_help",
                    LINUX_HELP_COMMAND,
                    "FORMAT COMPLETE: Linux # returned\n"
                    "LINUX REBOOT PREFLIGHT: listing protected-shell commands",
                )
            elif format_outcome == FormatRunOutcome.BOOTLOADER_READY:
                self._start_destructive_stage(
                    "update",
                    FLASH_COMMAND,
                    "FORMAT COMPLETE: U-Boot returned to HKVS #\n"
                    f"SENDING WRITE COMMAND: {FLASH_COMMAND}",
                )
            elif format_outcome == FormatRunOutcome.ERROR:
                self._block_destructive_sequence(
                    "U-Boot reported a format error. The firmware update was not sent."
                )
            return
        if self.destructive_stage == "linux_help":
            reboot_help = classify_linux_reboot_help(stage_output)
            if reboot_help == LinuxRebootHelpOutcome.SUPPORTED:
                self._begin_software_reboot()
            elif reboot_help == LinuxRebootHelpOutcome.UNSUPPORTED:
                self._begin_post_format_power_cycle()
            return
        if self.destructive_stage == "awaiting_uboot":
            if "HKVS #" in stage_output.upper():
                self._start_destructive_stage(
                    "update",
                    FLASH_COMMAND,
                    "POST-FORMAT HKVS # DETECTED\n"
                    f"SENDING WRITE COMMAND: {FLASH_COMMAND}",
                )
            return

        outcome = classify_update_output(stage_output)
        if outcome == UpdateOutcome.SHORT_WRITE:
            self.destructive_stage = None
            self.destructive_start_index = None
            self.status_label.setText(
                "STOPPED — known short-write pattern detected; do not power off"
            )
            self.status_label.setStyleSheet("color:#b00020; font-weight:700; padding:4px;")
        elif outcome == UpdateOutcome.NAND_ERROR:
            self.destructive_stage = None
            self.destructive_start_index = None
            self.status_label.setText("STOPPED — unexpected NAND error detected")
            self.status_label.setStyleSheet("color:#b00020; font-weight:700; padding:4px;")
        elif outcome == UpdateOutcome.SUCCESS:
            self.destructive_stage = None
            self.destructive_start_index = None
            self.flash_succeeded = True
            self._append_system(
                "FLASH SUCCESSFUL: Write Flash [OK] and UPDATE COMPLETE confirmed"
            )
            self.workflow_status.setText(
                "Firmware was written successfully. The camera is rebooting into stock "
                "Hikvision firmware; allow the first boot to finish."
            )
            self._update_gate()
            self.tabs.setCurrentIndex(2)
            QMessageBox.information(
                self,
                "Flash successful",
                "The camera reported Write Flash [OK] and UPDATE COMPLETE, then began its "
                "automatic reboot.\n\nKeep PoE connected while the first Hikvision boot "
                "finishes. TFTP is no longer needed after the reboot.",
            )

    def _save_log_as(self) -> None:
        suggested = f"ADC-VC726-recovery-{datetime.now():%Y%m%d-%H%M%S}.log"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save recovery log", str(Path.home() / suggested), "Log files (*.log)"
        )
        if not path:
            return
        Path(path).write_text(self.transcript, encoding="utf-8")
        self.log_path = Path(path)
        self._append_system(f"Saved recovery log to {path}")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt API)
        if self.tftp:
            self.tftp.stop()
        self.serial.disconnect()
        event.accept()


def apply_dark_mode_if_requested(app: QApplication) -> None:
    if os.environ.get("VC726_DARK_MODE") != "1":
        return
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, Qt.GlobalColor.darkGray)
    palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    app.setPalette(palette)
