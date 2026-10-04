import json
import os
import sys

from vc726_recovery.tftp_helper import main


def test_helper_publishes_file_access_failure(monkeypatch, tmp_path):
    state_path = tmp_path / "state.json"
    missing_firmware = tmp_path / "missing.dav"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "vc726-tftp-helper",
            "--host",
            "192.168.1.128",
            "--port",
            "69",
            "--interface",
            "en5",
            "--file",
            str(missing_firmware),
            "--state",
            str(state_path),
            "--stop",
            str(tmp_path / "stop"),
            "--parent-pid",
            str(os.getpid()),
        ],
    )

    assert main() == 1
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "error"
    assert "missing.dav" in state["message"]
