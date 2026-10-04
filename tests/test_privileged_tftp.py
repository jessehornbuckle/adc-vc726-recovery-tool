import shlex
from pathlib import Path

from vc726_recovery.privileged_tftp import PrivilegedMacTftpServer


def test_privileged_server_uses_one_macos_admin_command(monkeypatch, tmp_path):
    work = tmp_path / "helper-state"
    work.mkdir()
    firmware = tmp_path / "digicap.dav"
    firmware.write_bytes(b"placeholder")
    calls = []

    class FakeLauncher:
        returncode = None

        def __init__(self, command, **_kwargs):
            calls.append(command)

        def poll(self):
            return self.returncode

        def communicate(self, timeout=None):
            return "", ""

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def terminate(self):
            self.returncode = -15

    monkeypatch.setattr("vc726_recovery.privileged_tftp.route_interface", lambda _ip: "en5")
    monkeypatch.setattr(
        "vc726_recovery.privileged_tftp._helper_path", lambda: ["/Applications/Test Helper"]
    )
    monkeypatch.setattr("vc726_recovery.privileged_tftp.tempfile.mkdtemp", lambda **_k: str(work))
    monkeypatch.setattr("vc726_recovery.privileged_tftp.subprocess.Popen", FakeLauncher)

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
    assert "with timeout of 86400 seconds" in script
    assert "'/Applications/Test Helper'" in script
    assert "/usr/bin/nohup" not in script
    assert "exec " in script
    assert "</dev/null" in script
    assert "--interface en5" in script
    assert "--host 192.168.1.128" in script
    normalized_script = script.replace("\\\\", "\\")
    staged_argument = shlex.quote(str(work / "digicap.dav"))
    log_argument = shlex.quote(str(work / "helper.log"))
    assert f"--file {staged_argument}" in normalized_script
    assert f">{log_argument}" in normalized_script
    assert (work / "digicap.dav").read_bytes() == b"placeholder"
    server.stop()


def test_startup_detail_uses_helper_log(tmp_path):
    server = PrivilegedMacTftpServer(
        "192.168.1.128", 69, tmp_path / "digicap.dav", "192.168.1.66"
    )
    server._log_path = tmp_path / "helper.log"
    server._log_path.write_text("launch failure detail", encoding="utf-8")

    assert server._startup_detail({}) == "TFTP helper failed to launch: launch failure detail"


def test_startup_detail_uses_osascript_error():
    server = PrivilegedMacTftpServer(
        "192.168.1.128", 69, Path("digicap.dav"), "192.168.1.66"
    )

    assert server._startup_detail({}, "authorization failed") == (
        "macOS could not start the TFTP helper: authorization failed"
    )
