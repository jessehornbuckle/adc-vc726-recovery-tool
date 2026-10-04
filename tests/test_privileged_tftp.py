import subprocess

from vc726_recovery.privileged_tftp import PrivilegedMacTftpServer


def test_privileged_server_uses_one_macos_admin_command(monkeypatch, tmp_path):
    work = tmp_path / "helper-state"
    work.mkdir()
    firmware = tmp_path / "digicap.dav"
    firmware.write_bytes(b"placeholder")
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("vc726_recovery.privileged_tftp.route_interface", lambda _ip: "en5")
    monkeypatch.setattr(
        "vc726_recovery.privileged_tftp._helper_path", lambda: ["/Applications/Test Helper"]
    )
    monkeypatch.setattr("vc726_recovery.privileged_tftp.tempfile.mkdtemp", lambda **_k: str(work))
    monkeypatch.setattr("vc726_recovery.privileged_tftp.subprocess.run", fake_run)

    server = PrivilegedMacTftpServer(
        "192.168.1.128", 69, firmware, "192.168.1.66"
    )
    monkeypatch.setattr(
        server,
        "_read_state",
        lambda: {"status": "running", "message": "ready", "sequence": 1},
    )
    monkeypatch.setattr(server, "_monitor_state", lambda: None)

    server.start()

    assert server.running
    assert calls[0][:2] == ["/usr/bin/osascript", "-e"]
    script = calls[0][2]
    assert "with administrator privileges" in script
    assert "'/Applications/Test Helper'" in script
    assert "--interface en5" in script
    assert "--host 192.168.1.128" in script
    server.stop()
