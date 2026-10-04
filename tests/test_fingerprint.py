from vc726_recovery.constants import HARDWARE_PROFILE_BEGIN, HARDWARE_PROFILE_END
from vc726_recovery.fingerprint import (
    FingerprintAnalyzer,
    UpdateOutcome,
    classify_update_output,
    find_protected_shell_prompt,
)

PROVEN_HARDWARE_PROFILE = f"""
{HARDWARE_PROFILE_BEGIN}
Ambarella S3L Olive board S3L33M
NAND device id: 0x2c 0xf1 Micron 128 MiB
sensor type 42 sensor id 0x3013
ambarella-eth e000e000.ethernet: MAC Address[b8:3a:9d:14:02:37].
{HARDWARE_PROFILE_END}
"""

PROVEN_TRANSCRIPT = """
HKVS # printenv
ipaddr=192.168.1.65
serverip=192.168.1.128
ethaddr=b8:3a:9d:14:02:37
"""


def test_proven_fingerprint_passes_readonly_gate():
    report = FingerprintAnalyzer.analyze(PROVEN_TRANSCRIPT, PROVEN_HARDWARE_PROFILE)

    assert report.readonly_gate_passed
    assert report.matched_count == 8


def test_prompt_and_network_alone_are_not_enough():
    report = FingerprintAnalyzer.analyze(
        "HKVS #\nipaddr=192.168.1.65\nserverip=192.168.1.128\n"
    )

    assert not report.readonly_gate_passed


def test_second_proven_camera_bootloader_ip_passes():
    transcript = PROVEN_TRANSCRIPT.replace("192.168.1.65", "192.168.1.66")
    report = FingerprintAnalyzer.analyze(transcript, PROVEN_HARDWARE_PROFILE)

    assert report.readonly_gate_passed
    assert report.matched_count == 8


def test_unproven_camera_bootloader_ip_is_rejected():
    transcript = PROVEN_TRANSCRIPT.replace("192.168.1.65", "192.168.1.67")
    report = FingerprintAnalyzer.analyze(transcript, PROVEN_HARDWARE_PROFILE)

    assert not report.camera_ip
    assert not report.readonly_gate_passed


def test_hardware_and_bootloader_mac_must_match():
    transcript = PROVEN_TRANSCRIPT.replace("b8:3a:9d:14:02:37", "b8:3a:9d:14:02:38")
    report = FingerprintAnalyzer.analyze(transcript, PROVEN_HARDWARE_PROFILE)

    assert not report.mac_match
    assert not report.readonly_gate_passed


def test_incomplete_hardware_capture_is_rejected():
    incomplete = PROVEN_HARDWARE_PROFILE.replace(HARDWARE_PROFILE_END, "")
    report = FingerprintAnalyzer.analyze(PROVEN_TRANSCRIPT, incomplete)

    assert not report.profile_captured
    assert not report.readonly_gate_passed


def test_echoed_end_command_is_not_a_complete_capture_marker():
    incomplete = (
        f"echo {HARDWARE_PROFILE_BEGIN}\r\n{HARDWARE_PROFILE_BEGIN}\r\n"
        "Micron NAND 128MiB 0x2c 0xf1\r\n"
        f"echo {HARDWARE_PROFILE_END}\r\n"
    )
    report = FingerprintAnalyzer.analyze(PROVEN_TRANSCRIPT, incomplete)

    assert not report.profile_captured
    assert not report.readonly_gate_passed


def test_actual_second_camera_dmesg_format_is_recognized():
    hardware = (
        f"{HARDWARE_PROFILE_BEGIN}\n"
        "NAND device: Manufacturer ID: 0x2c, Chip ID: 0xf1 "
        "(Micron NAND 128MiB 3,3V 8-bit), 128MiB, page size: 2048, OOB size: 64\n"
        "ambarella-eth e000e000.ethernet: MAC Address[b8:3a:9d:14:02:37].\n"
        f"{HARDWARE_PROFILE_END}\n"
    )
    report = FingerprintAnalyzer.analyze(PROVEN_TRANSCRIPT, hardware)

    assert report.nand
    assert report.mac_match
    assert report.readonly_gate_passed


def test_protected_shell_prompt_is_found_when_async_log_follows_it():
    captured = (
        "dmesg\r\n"
        "[    1.980446] NAND device: Manufacturer ID: 0x2c, Chip ID: 0xf1\r\n"
        "# # [10-03 20:29:14][pid:655][SYSINIT][ERROR] asynchronous log\r\n"
    )

    match = find_protected_shell_prompt(captured)

    assert match is not None
    assert captured[: match.end()].endswith("# #")


def test_hash_banner_is_not_mistaken_for_protected_shell_prompt():
    assert find_protected_shell_prompt("######## camera banner ########\r\n") is None


def test_update_outcome_prefers_short_write_over_generic_failure():
    assert (
        classify_update_output("failed: short write /dav/IElang.tar") == UpdateOutcome.SHORT_WRITE
    )
    assert classify_update_output("TFTP error: file not found") == UpdateOutcome.TFTP_ERROR
    assert classify_update_output("Update success; rebooting") == UpdateOutcome.SUCCESS


def test_update_outcome_recognizes_real_hikvision_success_markers():
    transcript = """
    [ INFO][MIN]BURN: Write Flash [OK]
    ***** UPDATE COMPLETE *****
    ***** SYSTEM REBOOT *****
    """

    assert classify_update_output(transcript) == UpdateOutcome.SUCCESS


def test_update_outcome_requires_both_hikvision_success_markers():
    assert classify_update_output("Write Flash [OK]") == UpdateOutcome.UNKNOWN
    assert classify_update_output("UPDATE COMPLETE") == UpdateOutcome.UNKNOWN
