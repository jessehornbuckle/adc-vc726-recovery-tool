"""Analyze camera boot and update transcripts without writing to the device."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from .constants import (
    HARDWARE_PROFILE_BEGIN,
    HARDWARE_PROFILE_END,
    SUPPORTED_CAMERA_IPS,
)

_PROTECTED_SHELL_PROMPT = re.compile(
    r"(?:^|[\r\n])#(?:[ \t]+#)?(?=[ \t]*(?:[\r\n]|$|\[))"
)


def find_protected_shell_prompt(text: str) -> re.Match[str] | None:
    """Find a Linux prompt even when asynchronous camera logs follow it."""
    return _PROTECTED_SHELL_PROMPT.search(text)


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
    profile_captured: bool
    mac_match: bool
    evidence: dict[str, str] = field(default_factory=dict)

    @property
    def readonly_gate_passed(self) -> bool:
        """Values that can be safely established from serial output."""
        return (
            self.profile_captured
            and self.prompt
            and self.camera_ip
            and self.server_ip
            and self.mac_match
            and (self.soc or self.nand)
        )

    @property
    def matched_count(self) -> int:
        return sum(
            (
                self.profile_captured,
                self.prompt,
                self.soc,
                self.nand,
                self.sensor,
                self.camera_ip,
                self.server_ip,
                self.mac_match,
            )
        )


class FingerprintAnalyzer:
    _supported_camera_ips = "|".join(re.escape(address) for address in SUPPORTED_CAMERA_IPS)
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
        "camera_ip": re.compile(
            rf"ipaddr\s*=\s*(?:{_supported_camera_ips})", re.IGNORECASE
        ),
        "server_ip": re.compile(r"serverip\s*=\s*192\.168\.1\.128", re.IGNORECASE),
    }

    _hardware_mac = re.compile(r"MAC Address\[([0-9a-f:]{17})\]", re.IGNORECASE)
    _bootloader_mac = re.compile(r"ethaddr\s*=\s*([0-9a-f:]{17})", re.IGNORECASE)
    _profile_begin = re.compile(
        rf"(?:^|[\r\n]){re.escape(HARDWARE_PROFILE_BEGIN)}(?:[\r\n]|$)"
    )
    _profile_end = re.compile(
        rf"(?:^|[\r\n]){re.escape(HARDWARE_PROFILE_END)}(?:[\r\n]|$)"
    )

    @classmethod
    def analyze(cls, transcript: str, hardware_profile: str = "") -> FingerprintReport:
        found: dict[str, bool] = {}
        evidence: dict[str, str] = {}
        for name, pattern in cls._patterns.items():
            source = hardware_profile if name in {"soc", "nand", "sensor"} else transcript
            match = pattern.search(source)
            found[name] = match is not None
            if match:
                evidence[name] = " ".join(match.group(0).split())[:160]

        profile_captured = bool(
            cls._profile_begin.search(hardware_profile)
            and cls._profile_end.search(hardware_profile)
        )
        hardware_mac = cls._hardware_mac.search(hardware_profile)
        bootloader_mac = cls._bootloader_mac.search(transcript)
        mac_match = bool(
            hardware_mac
            and bootloader_mac
            and hardware_mac.group(1).casefold() == bootloader_mac.group(1).casefold()
        )
        if hardware_mac:
            evidence["hardware_mac"] = hardware_mac.group(1).lower()
        if bootloader_mac:
            evidence["bootloader_mac"] = bootloader_mac.group(1).lower()

        return FingerprintReport(
            profile_captured=profile_captured,
            mac_match=mac_match,
            evidence=evidence,
            **found,
        )


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
