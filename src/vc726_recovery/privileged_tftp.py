"""macOS controller for the narrowly scoped privileged TFTP helper."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .network import NetworkSetupError, route_interface


def _helper_path() -> list[str]:
    if getattr(sys, "frozen", False):
        roots = [Path(getattr(sys, "_MEIPASS", "")), Path(sys.executable).parent]
        for root in roots:
            candidate = root / "vc726-tftp-helper"
            if candidate.is_file():
                return [str(candidate)]
        raise NetworkSetupError("The packaged TFTP helper is missing")
    return [sys.executable, "-m", "vc726_recovery.tftp_helper"]


def _apple_script(command: str) -> str:
    escaped = command.replace("\\", "\\\\").replace('"', '\\"')
    return (
        'with timeout of 86400 seconds\n'
        f'  do shell script "{escaped}" with administrator privileges\n'
        "end timeout"
    )


class PrivilegedMacTftpServer:
    """Start a root helper through the standard macOS administrator dialog."""

    def __init__(
        self,
        host: str,
        port: int,
        file_path: Path,
        camera_address: str,
        progress: Callable[[int, int], None] | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.file_path = Path(file_path)
        self.camera_address = camera_address
        self.progress = progress or (lambda _done, _total: None)
        self.log = log or (lambda _message: None)
        self._directory: Path | None = None
        self._state_path: Path | None = None
        self._stop_path: Path | None = None
        self._log_path: Path | None = None
        self._launcher: subprocess.Popen[str] | None = None
        self._running = False
        self._monitor: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        interface = route_interface(self.camera_address)
        self._directory = Path(tempfile.mkdtemp(prefix="vc726-tftp-"))
        self._state_path = self._directory / "state.json"
        self._stop_path = self._directory / "stop"
        self._log_path = self._directory / "helper.log"
        staged_firmware = self._directory / "digicap.dav"
        # The administrator-owned helper may not have macOS privacy access to a file
        # selected from Downloads/Documents even though the GUI does. Stage the already
        # verified image in our private working directory before elevating.
        shutil.copyfile(self.file_path, staged_firmware)
        staged_firmware.chmod(0o644)
        command = [
            *_helper_path(),
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--interface",
            interface,
            "--file",
            str(staged_firmware),
            "--state",
            str(self._state_path),
            "--stop",
            str(self._stop_path),
            "--parent-pid",
            str(os.getpid()),
        ]
        shell_command = "exec " + " ".join(shlex.quote(part) for part in command)
        shell_command += f" </dev/null >{shlex.quote(str(self._log_path))} 2>&1"
        self._launcher = subprocess.Popen(
            ["/usr/bin/osascript", "-e", _apple_script(shell_command)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 60
        state: dict[str, object] = {}
        while time.monotonic() < deadline:
            state = self._read_state()
            if state.get("status") in {"running", "error"}:
                break
            if self._launcher.poll() is not None:
                break
            time.sleep(0.1)
        if state.get("status") != "running":
            if self._stop_path:
                self._stop_path.touch(exist_ok=True)
            launcher_message = self._launcher_message()
            detail = self._startup_detail(state, launcher_message)
            self._finish_launcher()
            self._discard_directory()
            if "User canceled" in launcher_message or "(-128)" in launcher_message:
                raise NetworkSetupError("Administrator approval was cancelled")
            raise NetworkSetupError(detail)
        self._running = True
        self.log(str(state.get("message") or f"TFTP listening on {self.host}:{self.port}"))
        self._monitor = threading.Thread(target=self._monitor_state, daemon=True)
        self._monitor.start()

    def stop(self) -> None:
        if self._stop_path and self._directory:
            self._stop_path.touch(exist_ok=True)
        if self._monitor and self._monitor is not threading.current_thread():
            self._monitor.join(timeout=5)
        self._running = False
        self._finish_launcher()
        self._discard_directory()

    def _read_state(self) -> dict[str, object]:
        if not self._state_path:
            return {}
        try:
            return json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _monitor_state(self) -> None:
        last_sequence = -1
        while self._running:
            state = self._read_state()
            sequence = int(state.get("sequence", 0))
            if sequence != last_sequence:
                last_sequence = sequence
                done = int(state.get("done", 0))
                total = int(state.get("total", 0))
                if total:
                    self.progress(done, total)
                message = str(state.get("message", ""))
                if message:
                    self.log(message)
            if state.get("status") in {"stopped", "error"}:
                self._running = False
                return
            time.sleep(0.2)

    def _launcher_message(self) -> str:
        if not self._launcher or self._launcher.poll() is None:
            return ""
        try:
            stdout, stderr = self._launcher.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            return ""
        return "\n".join(part.strip() for part in (stderr, stdout) if part.strip())

    def _startup_detail(
        self, state: dict[str, object], launcher_message: str = ""
    ) -> str:
        message = str(state.get("message") or "").strip()
        if message:
            return message
        if self._log_path:
            try:
                output = self._log_path.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                output = ""
            if output:
                return f"TFTP helper failed to launch: {output[-1200:]}"
        if launcher_message:
            return f"macOS could not start the TFTP helper: {launcher_message[-1200:]}"
        return "TFTP helper did not start and produced no diagnostic output"

    def _finish_launcher(self) -> None:
        if not self._launcher:
            return
        try:
            self._launcher.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._launcher.terminate()
            try:
                self._launcher.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        self._launcher = None

    def _discard_directory(self) -> None:
        if self._directory:
            shutil.rmtree(self._directory, ignore_errors=True)
        self._directory = None
        self._state_path = None
        self._stop_path = None
        self._log_path = None
