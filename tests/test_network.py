import subprocess

import pytest

from vc726_recovery.network import (
    NetworkSetupError,
    interface_for_address,
    route_interface,
)


class FakeRunner:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.commands = []

    def __call__(self, command, **_kwargs):
        self.commands.append(command)
        return next(self.replies)


def reply(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_route_interface_reads_macos_route():
    runner = FakeRunner([reply("   interface: en5\n")])
    assert route_interface("192.168.1.66", runner=runner) == "en5"


def test_route_interface_rejects_vpn_route():
    runner = FakeRunner([reply("   interface: utun4\n")])
    with pytest.raises(NetworkSetupError, match="not a local Ethernet adapter"):
        route_interface("192.168.1.66", runner=runner)


def test_interface_for_address_finds_owner():
    runner = FakeRunner(
        [
            reply(
                "en0: flags=8863<UP>\n\tinet 192.168.1.241 netmask 0xffffff00\n"
                "en5: flags=8863<UP>\n\tinet 192.168.1.128 netmask 0xffffff00\n"
            )
        ]
    )
    assert interface_for_address("192.168.1.128", runner=runner) == "en5"
