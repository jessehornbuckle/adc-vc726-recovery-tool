"""Validate the narrowly proven U-Boot format workflow."""

from __future__ import annotations

import re
from enum import Enum

from .constants import FORMAT_PARTITIONS


class FormatHelpOutcome(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    MISMATCH = "mismatch"
    ERROR = "error"


class FormatRunOutcome(str, Enum):
    PENDING = "pending"
    REBOOT_REQUIRED = "reboot_required"
    BOOTLOADER_READY = "bootloader_ready"
    ERROR = "error"


class LinuxRebootHelpOutcome(str, Enum):
    PENDING = "pending"
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


_HELP_LINE = re.compile(
    r"Help\s+for\s+['\"]?format['\"]?\s*:\s*format\s+(.+?)\s+partitions",
    re.IGNORECASE,
)
_PROMPT = re.compile(r"HKVS\s*#", re.IGNORECASE)
_LINUX_PROMPT = re.compile(r"(?:^|[\r\n])#(?:[ \t]+#)?(?=[ \t]*(?:[\r\n]|$))")
_ERROR_MARKERS = (
    "unknown command",
    "command not found",
    "format fail",
    "format error",
    "operation failed",
)


def classify_format_help(output: str) -> FormatHelpOutcome:
    """Require U-Boot to advertise exactly the four proven format targets."""
    text = output.casefold()
    if any(marker in text for marker in _ERROR_MARKERS):
        return FormatHelpOutcome.ERROR

    match = _HELP_LINE.search(output)
    prompt = _PROMPT.search(output, match.end()) if match else None
    if match and prompt:
        targets = tuple(re.findall(r"[a-z0-9_]+", match.group(1).casefold()))
        if targets == FORMAT_PARTITIONS:
            return FormatHelpOutcome.VERIFIED
        return FormatHelpOutcome.MISMATCH

    if _PROMPT.search(output) and not match:
        return FormatHelpOutcome.ERROR
    return FormatHelpOutcome.PENDING


def classify_format_run(output: str) -> FormatRunOutcome:
    """Recognize the observed format completion and post-format bootloader handoff."""
    text = output.casefold()
    if any(marker in text for marker in _ERROR_MARKERS):
        return FormatRunOutcome.ERROR
    if _PROMPT.search(output):
        return FormatRunOutcome.BOOTLOADER_READY
    done = text.rfind("done!")
    if done >= 0 and _LINUX_PROMPT.search(output, done + len("done!")):
        return FormatRunOutcome.REBOOT_REQUIRED
    return FormatRunOutcome.PENDING


def classify_linux_reboot_help(output: str) -> LinuxRebootHelpOutcome:
    """Check the protected shell's completed help listing for a reboot command."""
    prompt = _LINUX_PROMPT.search(output)
    if prompt is None:
        return LinuxRebootHelpOutcome.PENDING

    body = output[: prompt.start()]
    lines = body.splitlines()
    if lines and lines[0].strip().casefold() == "help":
        lines = lines[1:]
    command_listing = "\n".join(lines)
    if re.search(r"\breboot\b", command_listing, re.IGNORECASE):
        return LinuxRebootHelpOutcome.SUPPORTED
    return LinuxRebootHelpOutcome.UNSUPPORTED
