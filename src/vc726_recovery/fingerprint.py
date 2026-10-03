"""Analyze camera boot and update transcripts without writing to the device."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class UpdateOutcome(str, Enum):
    UNKNOWN = "unknown"
    TRANSFERRING = "transferring"
    SUCCESS = "success"
    SHORT_WRITE = "short_write"
    TFTP_ERROR = "tftp_error"
    NAND_ERROR = "nand_error"


@dataclass(frozen=True)
class FingerprintReport:
    prompt: bool
    soc: bool
    nand: bool
    sensor: bool
    camera_ip: bool
    server_ip: bool
    evidence: dict[str, str] = field(default_factory=dict)

    @property
    def readonly_gate_passed(self) -> bool:
        """Values that can be safely established from serial output."""
        return self.prompt and self.camera_ip and self.server_ip and (self.soc or self.nand)

    @property
    def matched_count(self) -> int:
        return sum((self.prompt, self.soc, self.nand, self.sensor, self.camera_ip, self.server_ip))


class FingerprintAnalyzer:
    _patterns = {
        "prompt": re.compile(r"HKVS\s*#", re.IGNORECASE),
        "soc": re.compile(r"(?:S3L33M|Ambarella\s+S3L|S3L\s+Olive)", re.IGNORECASE),
        "nand": re.compile(
            r"(?:MT29F1G08ABAEA|Micron.{0,40}(?:128\s*Mi?B|0x2c.{0,8}0xf1)|"
            r"(?:nand|flash).{0,40}2c[:\s,]+f1)",
            re.IGNORECASE | re.DOTALL,
        ),
        "sensor": re.compile(
            r"(?:sensor.{0,30}(?:0x)?3013|sensor\s+type\s*[:=]?\s*42)", re.IGNORECASE
        ),
        "camera_ip": re.compile(r"ipaddr\s*=\s*192\.168\.1\.65", re.IGNORECASE),
        "server_ip": re.compile(r"serverip\s*=\s*192\.168\.1\.128", re.IGNORECASE),
    }

    @classmethod
    def analyze(cls, transcript: str) -> FingerprintReport:
        found: dict[str, bool] = {}
        evidence: dict[str, str] = {}
        for name, pattern in cls._patterns.items():
            match = pattern.search(transcript)
            found[name] = match is not None
            if match:
                evidence[name] = " ".join(match.group(0).split())[:160]
        return FingerprintReport(evidence=evidence, **found)


def classify_update_output(transcript: str) -> UpdateOutcome:
    text = transcript.casefold()
    if "short write" in text or "ielang.tar" in text and "failed" in text:
        return UpdateOutcome.SHORT_WRITE
    if any(
        marker in text for marker in ("nand write error", "bad eraseblock", "ecc unrecoverable")
    ):
        return UpdateOutcome.NAND_ERROR
    if any(marker in text for marker in ("tftp error", "retry count exceeded", "file not found")):
        return UpdateOutcome.TFTP_ERROR
    if any(
        marker in text
        for marker in (
            "update success",
            "upgrade success",
            "rebooting",
            "resetting",
            "done!",
        )
    ):
        return UpdateOutcome.SUCCESS
    if any(marker in text for marker in ("loading: #", "bytes transferred", "tftp from server")):
        return UpdateOutcome.TRANSFERRING
    return UpdateOutcome.UNKNOWN
