"""A deliberately small, single-file RFC 1350 TFTP server."""

from __future__ import annotations

import socket
import struct
import threading
from collections.abc import Callable
from pathlib import Path

from .constants import EXPECTED_FIRMWARE_NAME, TFTP_DEFAULT_BLOCK_SIZE, TFTP_MAX_BLOCK_SIZE

OP_RRQ = 1
OP_DATA = 3
OP_ACK = 4
OP_ERROR = 5
OP_OACK = 6


class TftpError(RuntimeError):
    pass


def parse_rrq(packet: bytes) -> tuple[str, str, dict[str, str]]:
    if len(packet) < 4 or struct.unpack(">H", packet[:2])[0] != OP_RRQ:
        raise TftpError("Packet is not a TFTP read request")
    parts = packet[2:].split(b"\x00")
    if len(parts) < 3:
        raise TftpError("Malformed TFTP read request")
    try:
        filename = parts[0].decode("utf-8")
        mode = parts[1].decode("ascii").casefold()
        raw_options = [part.decode("ascii") for part in parts[2:] if part]
    except UnicodeDecodeError as exc:
        raise TftpError("Malformed text in TFTP request") from exc
    options: dict[str, str] = {}
    for index in range(0, len(raw_options) - 1, 2):
        options[raw_options[index].casefold()] = raw_options[index + 1]
    return filename, mode, options


def data_packet(block: int, payload: bytes) -> bytes:
    return struct.pack(">HH", OP_DATA, block & 0xFFFF) + payload


def error_packet(code: int, message: str) -> bytes:
    return struct.pack(">HH", OP_ERROR, code) + message.encode("utf-8") + b"\x00"


class SingleFileTftpServer:
    """Serve only one verified file and reject every other request."""

    def __init__(
        self,
        host: str,
        port: int,
        file_path: Path,
        *,
        public_name: str = EXPECTED_FIRMWARE_NAME,
        progress: Callable[[int, int], None] | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.file_path = Path(file_path)
        self.public_name = public_name
        self.progress = progress or (lambda _done, _total: None)
        self.log = log or (lambda _message: None)
        self._listener: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._workers: set[threading.Thread] = set()

    @property
    def running(self) -> bool:
        return self._listener is not None and not self._stop.is_set()

    def start(self) -> None:
        if self.running:
            return
        if not self.file_path.is_file():
            raise FileNotFoundError(self.file_path)
        listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.settimeout(0.25)
        try:
            listener.bind((self.host, self.port))
        except OSError:
            listener.close()
            raise
        self._listener = listener
        self.port = listener.getsockname()[1]
        self._stop.clear()
        self._thread = threading.Thread(target=self._listen, name="tftp-listener", daemon=True)
        self._thread.start()
        self.log(f"TFTP listening on {self.host}:{self.port} for {self.public_name}")

    def stop(self) -> None:
        self._stop.set()
        listener = self._listener
        self._listener = None
        if listener:
            listener.close()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)
        self._thread = None
        for worker in list(self._workers):
            worker.join(timeout=1)
        self._workers.clear()

    def _listen(self) -> None:
        assert self._listener is not None
        while not self._stop.is_set():
            try:
                packet, client = self._listener.recvfrom(4096)
            except TimeoutError:
                continue
            except OSError:
                break
            worker = threading.Thread(
                target=self._serve_request,
                args=(packet, client),
                name=f"tftp-{client[0]}",
                daemon=True,
            )
            self._workers.add(worker)
            worker.start()

    def _serve_request(self, packet: bytes, client: tuple[str, int]) -> None:
        transfer: socket.socket | None = None
        try:
            filename, mode, options = parse_rrq(packet)
            transfer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            transfer.settimeout(2)
            if filename.casefold() != self.public_name.casefold():
                transfer.sendto(error_packet(1, "File not found"), client)
                self.log(f"Rejected request for unexpected file: {filename}")
                return
            if mode not in {"octet", "binary"}:
                transfer.sendto(error_packet(4, "Only octet mode is supported"), client)
                return

            block_size = TFTP_DEFAULT_BLOCK_SIZE
            if "blksize" in options:
                requested = int(options["blksize"])
                block_size = max(8, min(requested, TFTP_MAX_BLOCK_SIZE))
                oack = (
                    struct.pack(">H", OP_OACK) + b"blksize\x00" + str(block_size).encode() + b"\x00"
                )
                transfer.sendto(oack, client)
                ack, client = transfer.recvfrom(64)
                if ack[:4] != struct.pack(">HH", OP_ACK, 0):
                    raise TftpError("Client did not acknowledge TFTP options")

            total = self.file_path.stat().st_size
            done = 0
            block = 1
            with self.file_path.open("rb") as handle:
                while not self._stop.is_set():
                    payload = handle.read(block_size)
                    outgoing = data_packet(block, payload)
                    acknowledged = False
                    for _attempt in range(5):
                        transfer.sendto(outgoing, client)
                        try:
                            reply, reply_client = transfer.recvfrom(64)
                        except TimeoutError:
                            continue
                        if reply_client == client and reply[:4] == struct.pack(
                            ">HH", OP_ACK, block
                        ):
                            acknowledged = True
                            break
                    if not acknowledged:
                        raise TftpError(f"No acknowledgement for block {block}")
                    done += len(payload)
                    self.progress(done, total)
                    if len(payload) < block_size:
                        self.log(f"TFTP transfer complete: {done:,} bytes sent to {client[0]}")
                        break
                    block = (block + 1) & 0xFFFF
        except (OSError, TftpError, ValueError) as exc:
            if not self._stop.is_set():
                self.log(f"TFTP error for {client[0]}: {exc}")
        finally:
            if transfer:
                transfer.close()
            self._workers.discard(threading.current_thread())
