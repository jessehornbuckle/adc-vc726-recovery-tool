"""Temporary macOS network setup for the recovery TFTP host."""

from __future__ import annotations

import ipaddress
import re
import subprocess
from collections.abc import Callable, Sequence

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
_INTERFACE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")


class NetworkSetupError(RuntimeError):
    """Raised when the temporary recovery address cannot be configured safely."""


def _run(command: Sequence[str], *, runner: CommandRunner) -> subprocess.CompletedProcess[str]:
    return runner(command, capture_output=True, text=True, check=False)


def _valid_ipv4(address: str) -> str:
    try:
        return str(ipaddress.IPv4Address(address))
    except ipaddress.AddressValueError as exc:
        raise NetworkSetupError(f"Invalid IPv4 address: {address}") from exc


def _interface_for_address(address: str, *, runner: CommandRunner) -> str | None:
    result = _run(["/sbin/ifconfig"], runner=runner)
    if result.returncode != 0:
        raise NetworkSetupError(result.stderr.strip() or "Unable to inspect network addresses")
    current: str | None = None
    for line in result.stdout.splitlines():
        if line and not line[0].isspace() and ":" in line:
            current = line.partition(":")[0]
        elif current and re.search(rf"\binet\s+{re.escape(address)}\b", line):
            return current
    return None


def interface_for_address(
    address: str, *, runner: CommandRunner = subprocess.run
) -> str | None:
    """Return the interface that currently owns address, if any."""

    return _interface_for_address(_valid_ipv4(address), runner=runner)


def route_interface(destination: str, *, runner: CommandRunner = subprocess.run) -> str:
    """Return the macOS interface selected for the camera bootloader address."""

    destination = _valid_ipv4(destination)
    result = _run(["/sbin/route", "-n", "get", destination], runner=runner)
    if result.returncode != 0:
        raise NetworkSetupError(
            result.stderr.strip()
            or "No active network route reaches the camera. Connect Ethernet/PoE first."
        )
    match = re.search(r"^\s*interface:\s*(\S+)\s*$", result.stdout, re.MULTILINE)
    if not match or not _INTERFACE_RE.fullmatch(match.group(1)):
        raise NetworkSetupError("Could not identify the Ethernet adapter used for the camera")
    interface = match.group(1)
    if interface == "lo0" or interface.startswith("utun"):
        raise NetworkSetupError(
            f"The camera route uses {interface}, not a local Ethernet adapter. "
            "Connect the camera network and try again."
        )
    return interface
