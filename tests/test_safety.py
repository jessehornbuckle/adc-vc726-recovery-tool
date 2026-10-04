from pathlib import Path

from vc726_recovery.constants import HARDWARE_PROFILE_BEGIN, HARDWARE_PROFILE_END
from vc726_recovery.fingerprint import FingerprintAnalyzer
from vc726_recovery.firmware import FirmwareReport
from vc726_recovery.safety import ManualConfirmations, SafetyGate


def valid_firmware() -> FirmwareReport:
    return FirmwareReport(
        path=Path("digicap.dav"),
        filename_ok=True,
        size=36_390_527,
        size_ok=True,
        sha256="good",
        sha256_ok=True,
    )


def valid_fingerprint():
    hardware = (
        f"{HARDWARE_PROFILE_BEGIN}\nS3L33M\n"
        "MAC Address[b8:3a:9d:14:02:37]\n"
        f"{HARDWARE_PROFILE_END}"
    )
    bootloader = (
        "HKVS # ipaddr=192.168.1.65 serverip=192.168.1.128 "
        "ethaddr=b8:3a:9d:14:02:37"
    )
    return FingerprintAnalyzer.analyze(bootloader, hardware)


def all_confirmed() -> ManualConfirmations:
    return ManualConfirmations(True, True, True, True, True)


def test_gate_requires_every_layer():
    gate = SafetyGate(valid_firmware(), valid_fingerprint(), all_confirmed(), True, True)
    assert gate.ready
    assert gate.blockers() == []


def test_gate_blocks_when_tftp_is_not_running():
    gate = SafetyGate(valid_firmware(), valid_fingerprint(), all_confirmed(), False, True)
    assert not gate.ready
    assert "TFTP" in gate.blockers()[0]
