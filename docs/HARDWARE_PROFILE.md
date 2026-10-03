# Proven ADC-VC726 hardware profile

This profile comes from one successfully recovered test camera and must be treated as an exact-match profile—not as a family resemblance.

## Physical identifiers

- Label: Alarm.com `ADC-VC726`
- Main board silkscreen: `PCB-131948 REV 2.0`
- SoC marking: Ambarella `S3L33M-B0-RH`
- NAND marking: Micron `MT29F1G08ABAEA`
- Four-pin connector beside reset: `GND / TX / RX / 3.3V`

With the cable found in the tested camera:

| Wire | Board label | Connection |
|---|---|---|
| Yellow | GND | adapter GND |
| White | TX | adapter RXD |
| Red | RX | adapter TXD |
| Black | 3.3V | **leave disconnected** |

Never rely on wire color alone. Read the board silkscreen and confirm ground electrically.

## Serial and bootloader identifiers

- Logic: 3.3 V TTL, not RS-232
- Format: `115200 8-N-1`, no flow control
- Boot interrupt: `Ctrl+U`
- Prompt: `HKVS #`
- `ipaddr=192.168.1.65`
- `serverip=192.168.1.128`
- Working update command: `upd digicap.dav`

## Original system identifiers

- Platform: Ambarella S3L Olive / `S3L33M`
- Sensor type: `42`
- Sensor ID: `0x3013`
- NAND ID: `0x2c:0xf1`
- Internal product ID observed through SADP: `DS-2CDVT-FCMPTN-S`

## Firmware profile

- Package: `IPC_G1_EN_STD_5.5.82_181211`
- File: `digicap.dav`
- File size: `36,390,527` bytes
- SHA-256: `0d7f4edf93e3db610a2d663514220ca3b45138fa039dfecafb01860b3b6ea6df`
