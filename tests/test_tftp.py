import socket
import struct
from pathlib import Path

import pytest

from vc726_recovery.tftp import (
    OP_ACK,
    OP_DATA,
    OP_OACK,
    SingleFileTftpServer,
    TftpError,
    data_packet,
    parse_rrq,
)


def test_parse_rrq_with_blksize():
    request = b"\x00\x01digicap.dav\x00octet\x00blksize\x001468\x00"
    filename, mode, options = parse_rrq(request)
    assert filename == "digicap.dav"
    assert mode == "octet"
    assert options == {"blksize": "1468"}


def test_parse_rrq_rejects_other_opcodes():
    with pytest.raises(TftpError):
        parse_rrq(b"\x00\x02bad")


def test_data_packet_header():
    packet = data_packet(7, b"abc")
    assert struct.unpack(">HH", packet[:4]) == (OP_DATA, 7)
    assert packet[4:] == b"abc"


def test_single_file_server_completes_transfer(tmp_path: Path):
    payload = b"abcdefghijklmnopqrstuvwxyz"
    firmware = tmp_path / "digicap.dav"
    firmware.write_bytes(payload)
    progress: list[tuple[int, int]] = []
    server = SingleFileTftpServer(
        "127.0.0.1",
        0,
        firmware,
        progress=lambda done, total: progress.append((done, total)),
    )
    server.start()

    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.settimeout(2)
    request = b"\x00\x01digicap.dav\x00octet\x00blksize\x008\x00"
    client.sendto(request, ("127.0.0.1", server.port))

    received = bytearray()
    try:
        reply, transfer_address = client.recvfrom(128)
        assert struct.unpack(">H", reply[:2])[0] == OP_OACK
        client.sendto(struct.pack(">HH", OP_ACK, 0), transfer_address)

        expected_block = 1
        while True:
            packet, packet_address = client.recvfrom(128)
            opcode, block = struct.unpack(">HH", packet[:4])
            assert opcode == OP_DATA
            assert block == expected_block
            data = packet[4:]
            received.extend(data)
            client.sendto(struct.pack(">HH", OP_ACK, block), packet_address)
            if len(data) < 8:
                break
            expected_block += 1
    finally:
        client.close()
        server.stop()

    assert bytes(received) == payload
    assert progress[-1] == (len(payload), len(payload))
