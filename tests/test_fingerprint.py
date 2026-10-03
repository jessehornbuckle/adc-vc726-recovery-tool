from vc726_recovery.fingerprint import FingerprintAnalyzer, UpdateOutcome, classify_update_output

PROVEN_TRANSCRIPT = """
Ambarella S3L Olive board S3L33M
NAND device id: 0x2c 0xf1 Micron 128 MiB
sensor type 42 sensor id 0x3013
HKVS # printenv
ipaddr=192.168.1.65
serverip=192.168.1.128
"""


def test_proven_fingerprint_passes_readonly_gate():
    report = FingerprintAnalyzer.analyze(PROVEN_TRANSCRIPT)

    assert report.readonly_gate_passed
    assert report.matched_count == 6


def test_prompt_and_network_alone_are_not_enough():
    report = FingerprintAnalyzer.analyze("HKVS #\nipaddr=192.168.1.65\nserverip=192.168.1.128\n")

    assert not report.readonly_gate_passed


def test_update_outcome_prefers_short_write_over_generic_failure():
    assert (
        classify_update_output("failed: short write /dav/IElang.tar") == UpdateOutcome.SHORT_WRITE
    )
    assert classify_update_output("TFTP error: file not found") == UpdateOutcome.TFTP_ERROR
    assert classify_update_output("Update success; rebooting") == UpdateOutcome.SUCCESS
