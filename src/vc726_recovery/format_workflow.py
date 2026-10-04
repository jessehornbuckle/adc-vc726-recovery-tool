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
    COMPLETE = "complete"
    ERROR = "error"


_HELP_LINE = re.compile(
    r"Help\s+for\s+['\"]?format['\"]?\s*:\s*format\s+(.+?)\s+partitions",
    re.IGNORECASE,
)
_PROMPT = re.compile(r"HKVS\s*#", re.IGNORECASE)
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
    """Accept format completion only after U-Boot returns to its prompt without an error."""
    text = output.casefold()
    if any(marker in text for marker in _ERROR_MARKERS):
        return FormatRunOutcome.ERROR
    if _PROMPT.search(output):
        return FormatRunOutcome.COMPLETE
    return FormatRunOutcome.PENDING
