"""Root-only macOS helper: configure one alias and serve one verified file."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from .firmware import verify_firmware
from .network import interface_for_address
from .tftp import SingleFileTftpServer


def _write_state(path: Path, state: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="state-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _parent_alive(parent_pid: int) -> bool:
    try:
        os.kill(parent_pid, 0)
    except OSError:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--interface", required=True)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--stop", type=Path, required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args()

    state: dict[str, object] = {
        "status": "starting",
        "sequence": 0,
        "done": 0,
        "total": 0,
        "message": "Preparing temporary network address",
    }
    added_address = False
    server: SingleFileTftpServer | None = None
    stopping = False

    def publish(message: str, *, status: str | None = None) -> None:
        state["sequence"] = int(state["sequence"]) + 1
        state["message"] = message
        if status:
            state["status"] = status
        _write_state(args.state, state)

    def request_stop(*_unused: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    try:
        state["total"] = args.file.stat().st_size
        firmware = verify_firmware(args.file)
        if not firmware.valid:
            raise RuntimeError(f"Firmware verification failed in helper: {firmware.summary}")
        owner = interface_for_address(args.host)
        if owner is None:
            subprocess.run(
                [
                    "/sbin/ifconfig",
                    args.interface,
                    "alias",
                    args.host,
                    "netmask",
                    "255.255.255.0",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            added_address = True
        elif owner != args.interface:
            raise RuntimeError(
                f"{args.host} already belongs to {owner}, not camera adapter {args.interface}"
            )

        def progress(done: int, total: int) -> None:
            state["done"] = done
            state["total"] = total
            publish(f"TFTP transfer: {done:,} / {total:,} bytes")

        server = SingleFileTftpServer(
            args.host,
            args.port,
            args.file,
            progress=progress,
            log=publish,
        )
        server.start()
        publish(
            f"Listening on {args.host}:{args.port} via {args.interface}", status="running"
        )
        while not stopping and not args.stop.exists() and _parent_alive(args.parent_pid):
            time.sleep(0.2)
    except Exception as exc:
        publish(str(exc), status="error")
        return 1
    finally:
        if server:
            server.stop()
        if added_address:
            subprocess.run(
                ["/sbin/ifconfig", args.interface, "-alias", args.host],
                check=False,
                capture_output=True,
            )
        if state.get("status") != "error":
            publish("TFTP stopped; temporary network address removed", status="stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
