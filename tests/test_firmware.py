from __future__ import annotations

import hashlib

from vc726_recovery.firmware import verify_firmware


def test_verify_firmware_accepts_exact_file(tmp_path):
    payload = b"known firmware fixture"
    firmware = tmp_path / "digicap.dav"
    firmware.write_bytes(payload)

    report = verify_firmware(
        firmware,
        expected_hash=hashlib.sha256(payload).hexdigest(),
        expected_size=len(payload),
    )

    assert report.valid
    assert "known-good" in report.summary


def test_verify_firmware_rejects_wrong_hash_size_and_name(tmp_path):
    firmware = tmp_path / "wrong.bin"
    firmware.write_bytes(b"wrong")

    report = verify_firmware(firmware, expected_hash="0" * 64, expected_size=99)

    assert not report.valid
    assert not report.filename_ok
    assert not report.size_ok
    assert not report.sha256_ok
