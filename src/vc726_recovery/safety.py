"""Safety interlocks for write operations."""

from __future__ import annotations

from dataclasses import dataclass

from .fingerprint import FingerprintReport
from .firmware import FirmwareReport


@dataclass(frozen=True)
class ManualConfirmations:
    owns_device: bool = False
    model: bool = False
    board: bool = False
    components: bool = False
    accepts_brick_risk: bool = False

    @property
    def complete(self) -> bool:
        return all(
            (
                self.owns_device,
                self.model,
                self.board,
                self.components,
                self.accepts_brick_risk,
            )
        )


@dataclass(frozen=True)
class SafetyGate:
    firmware: FirmwareReport | None
    fingerprint: FingerprintReport | None
    confirmations: ManualConfirmations
    tftp_running: bool
    serial_connected: bool

    @property
    def ready(self) -> bool:
        return all(
            (
                self.firmware is not None and self.firmware.valid,
                self.fingerprint is not None and self.fingerprint.readonly_gate_passed,
                self.confirmations.complete,
                self.tftp_running,
                self.serial_connected,
            )
        )

    def blockers(self) -> list[str]:
        blockers: list[str] = []
        if not self.firmware or not self.firmware.valid:
            blockers.append("Select and verify the exact known-good digicap.dav")
        if not self.fingerprint or not self.fingerprint.readonly_gate_passed:
            blockers.append("Complete the read-only serial fingerprint check")
        if not self.confirmations.complete:
            blockers.append("Complete every ownership and hardware confirmation")
        if not self.tftp_running:
            blockers.append("Start the built-in TFTP server")
        if not self.serial_connected:
            blockers.append("Connect the 3.3 V serial console")
        return blockers
