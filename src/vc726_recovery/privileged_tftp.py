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
    return f'do shell script "{escaped}" with administrator privileges'


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
        command = [
            *_helper_path(),
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--interface",
            interface,
            "--file",
            str(self.file_path),
            "--state",
            str(self._state_path),
            "--stop",
            str(self._stop_path),
            "--parent-pid",
            str(os.getpid()),
        ]
        shell_command = "/usr/bin/nohup " + " ".join(shlex.quote(part) for part in command)
        shell_command += " >/dev/null 2>&1 &"
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", _apple_script(shell_command)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            self._discard_directory()
            message = result.stderr.strip()
            if "User canceled" in message or "(-128)" in message:
                raise NetworkSetupError("Administrator approval was cancelled")
            raise NetworkSetupError(message or "macOS could not start the TFTP helper")
        deadline = time.monotonic() + 8
        state: dict[str, object] = {}
        while time.monotonic() < deadline:
            state = self._read_state()
            if state.get("status") in {"running", "error"}:
                break
            time.sleep(0.1)
        if state.get("status") != "running":
            if self._stop_path:
                self._stop_path.touch(exist_ok=True)
            self._discard_directory()
            raise NetworkSetupError(str(state.get("message") or "TFTP helper did not start"))
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

    def _discard_directory(self) -> None:
        if self._directory:
            shutil.rmtree(self._directory, ignore_errors=True)
        self._directory = None
        self._state_path = None
        self._stop_path = None
