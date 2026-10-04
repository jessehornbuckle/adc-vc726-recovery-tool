"""Threaded serial-console access for the camera's 3.3 V UART."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import serial
from serial.tools import list_ports

from .constants import BOOT_INTERRUPT, SERIAL_BAUDRATE


def available_ports() -> list[tuple[str, str]]:
    ports: list[tuple[str, str]] = []
    for port in list_ports.comports():
        label = port.description or "Serial device"
        if port.manufacturer:
            label = f"{label} — {port.manufacturer}"
        ports.append((port.device, label))
    return sorted(ports, key=lambda item: item[0])


class SerialConsole:
    def __init__(
        self,
        on_text: Callable[[str], None],
        on_error: Callable[[str], None],
        on_closed: Callable[[], None] | None = None,
    ) -> None:
        self._on_text = on_text
        self._on_error = on_error
        self._on_closed = on_closed
        self._serial: serial.Serial | None = None
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()
        self._interrupt_stop = threading.Event()
        self._interrupt_lock = threading.Lock()
        self._prompt_window = ""
        self._write_lock = threading.Lock()

    @property
    def connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def connect(self, port: str) -> None:
        if self.connected:
            self.disconnect()
        self._stop.clear()
        self._interrupt_stop.clear()
        self._prompt_window = ""
        self._serial = serial.Serial(
            port=port,
            baudrate=SERIAL_BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.1,
            write_timeout=1,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        self._reader = threading.Thread(target=self._read_loop, name="serial-reader", daemon=True)
        self._reader.start()

    def disconnect(self) -> None:
        self._stop.set()
        self._interrupt_stop.set()
        serial_port = self._serial
        self._serial = None
        if serial_port:
            try:
                serial_port.close()
            except serial.SerialException:
                pass
        if self._reader and self._reader is not threading.current_thread():
            self._reader.join(timeout=1)
        self._reader = None

    def send_bytes(self, data: bytes) -> None:
        if not self.connected or self._serial is None:
            raise RuntimeError("Serial console is not connected")
        with self._write_lock:
            self._serial.write(data)
            self._serial.flush()

    def send_line(self, command: str) -> None:
        cleaned = command.strip("\r\n")
        self.send_bytes(cleaned.encode("ascii", errors="strict") + b"\r\n")

    def interrupt_boot(self, attempts: int = 120, interval: float = 0.1) -> None:
        """Send Ctrl+U across power-up, stopping when the HKVS prompt appears."""
        if not self._interrupt_lock.acquire(blocking=False):
            return
        self._interrupt_stop.clear()
        try:
            for _ in range(attempts):
                if not self.connected or self._interrupt_stop.is_set():
                    return
                self.send_bytes(BOOT_INTERRUPT)
                time.sleep(interval)
        finally:
            self._interrupt_lock.release()

    def _observe_boot_prompt(self, text: str) -> None:
        self._prompt_window = (self._prompt_window + text)[-128:]
        if "HKVS #" in self._prompt_window.upper():
            self._interrupt_stop.set()

    def run_readonly_probe(self) -> None:
        """Request only non-mutating U-Boot information."""
        self.send_line("help")
        time.sleep(0.25)
        self.send_line("printenv")

    def capture_hardware_profile(self) -> None:
        """Request read-only kernel hardware evidence from Hikvision's protected shell."""
        self.send_line("dmesg")

    def _read_loop(self) -> None:
        decoder_buffer = b""
        try:
            while not self._stop.is_set() and self._serial is not None:
                waiting = self._serial.in_waiting
                chunk = self._serial.read(max(waiting, 1))
                if not chunk:
                    continue
                decoder_buffer += chunk
                try:
                    text = decoder_buffer.decode("utf-8")
                    decoder_buffer = b""
                except UnicodeDecodeError as exc:
                    complete = decoder_buffer[: exc.start]
                    remainder = decoder_buffer[exc.start :]
                    if complete:
                        self._on_text(complete.decode("utf-8", errors="replace"))
                    if len(remainder) > 4:
                        self._on_text(remainder[:1].decode("utf-8", errors="replace"))
                        remainder = remainder[1:]
                    decoder_buffer = remainder
                    continue
                self._observe_boot_prompt(text)
                self._on_text(text)
        except (serial.SerialException, OSError) as exc:
            if not self._stop.is_set():
                self._on_error(str(exc))
        finally:
            if decoder_buffer:
                self._on_text(decoder_buffer.decode("utf-8", errors="replace"))
            if self._on_closed:
                self._on_closed()
