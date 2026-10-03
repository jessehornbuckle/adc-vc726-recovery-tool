"""Firmware validation helpers."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .constants import (
    EXPECTED_FIRMWARE_NAME,
    EXPECTED_FIRMWARE_SHA256,
    EXPECTED_FIRMWARE_SIZE,
)


@dataclass(frozen=True)
class FirmwareReport:
    path: Path
    filename_ok: bool
    size: int
    size_ok: bool
    sha256: str
    sha256_ok: bool

    @property
    def valid(self) -> bool:
        return self.filename_ok and self.size_ok and self.sha256_ok

    @property
    def summary(self) -> str:
        if self.valid:
            return "Verified exact known-good Hikvision G1 image"
        problems: list[str] = []
        if not self.filename_ok:
            problems.append(f"filename must be {EXPECTED_FIRMWARE_NAME}")
        if not self.size_ok:
            problems.append(f"unexpected size ({self.size:,} bytes)")
        if not self.sha256_ok:
            problems.append("SHA-256 does not match the proven image")
        return "; ".join(problems)


def sha256_file(
    path: Path,
    progress: Callable[[int, int], None] | None = None,
    chunk_size: int = 1024 * 1024,
) -> str:
    total = path.stat().st_size
    done = 0
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    return digest.hexdigest()


def verify_firmware(
    path: str | Path,
    *,
    expected_hash: str = EXPECTED_FIRMWARE_SHA256,
    expected_size: int = EXPECTED_FIRMWARE_SIZE,
    expected_name: str = EXPECTED_FIRMWARE_NAME,
    progress: Callable[[int, int], None] | None = None,
) -> FirmwareReport:
    firmware_path = Path(path).expanduser().resolve()
    if not firmware_path.is_file():
        raise FileNotFoundError(firmware_path)
    actual_hash = sha256_file(firmware_path, progress=progress)
    actual_size = firmware_path.stat().st_size
    return FirmwareReport(
        path=firmware_path,
        filename_ok=firmware_path.name.casefold() == expected_name.casefold(),
        size=actual_size,
        size_ok=actual_size == expected_size,
        sha256=actual_hash,
        sha256_ok=actual_hash.casefold() == expected_hash.casefold(),
    )
