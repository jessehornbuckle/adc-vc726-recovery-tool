# ADC-VC726 Recovery Assistant

A guarded Windows/macOS desktop utility for converting a **verified Alarm.com ADC-VC726** camera to local Hikvision firmware through its internal 3.3 V UART bootloader.

## Download

**[Download the signed and notarized Mac app (Apple Silicon)](https://github.com/jessehornbuckle/adc-vc726-recovery-tool/releases/download/v0.1.1-alpha.6/ADC-VC726-Recovery-macOS-arm64.zip)**

[View the release notes and all available downloads](https://github.com/jessehornbuckle/adc-vc726-recovery-tool/releases/tag/v0.1.1-alpha.6).

The goal is a right-to-repair tool in the spirit of JungleFlasher: automate the repetitive work, preserve the evidence, and refuse to write when the known hardware and firmware checks do not match.

> [!CAUTION]
> This is alpha software. Firmware flashing can permanently brick a camera. The packaged application completed a second physical-camera recovery on 2026-10-04, but it must not be used on a different model or board revision.

## Supported hardware profile

Version `0.1.1-alpha.6` supports only this proven combination:

| Item | Required value |
|---|---|
| Product label | `ADC-VC726` |
| Main board | `PCB-131948 REV 2.0` |
| Processor | Ambarella `S3L33M-B0-RH` |
| NAND | Micron `MT29F1G08ABAEA`, 128 MiB |
| Sensor reported by original firmware | type `42`, ID `0x3013` |
| Original firmware | `V5.5.82 build 210706` |
| Replacement platform | Hikvision G1 `V5.5.82 build 181211` |
| Proven U-Boot client IPs | `192.168.1.65`, `192.168.1.66` |
| U-Boot TFTP server IP | `192.168.1.128` |

If any identifier differs, stop. Similar-looking Alarm.com cameras can contain incompatible hardware.

## What the app does

- detects USB serial adapters;
- opens the UART at 115200 8-N-1;
- includes in-app camera-connector and USB-to-TTL adapter photos with the exact safe wiring
  map: GND to GND, camera TXD to adapter RXD, camera RXD to adapter TXD, and VCC disconnected;
- captures `dmesg` from the running camera using the read-only command supported by
  Hikvision's protected shell and automatically saves the bounded hardware evidence;
- guides the user through a 10-second PoE power-off wait;
- repeatedly sends `Ctrl+U` during the short U-Boot countdown;
- runs only `help` and `printenv` during the read-only fingerprint check;
- requires the saved Linux profile MAC to match U-Boot's live `ethaddr`;
- verifies the exact filename, size, and SHA-256 of `digicap.dav`;
- serves only that verified file through a built-in TFTP server;
- blocks the write command behind automatic and manual safety gates;
- requires a typed brick-risk confirmation before any destructive command;
- asks U-Boot to describe `format` and requires exactly `app_pri`, `app_sec`, `cfg_pri`,
  and `cfg_sec` before allowing it to run;
- waits for formatting to finish, checks the protected Linux shell's command list, and uses
  software reboot only when `reboot` is explicitly advertised;
- sends Ctrl+U across that reboot, waits for `HKVS #`, and then sends `upd digicap.dav`;
- falls back to a guided PoE power cycle when software reboot is not advertised;
- watches output for known success, TFTP, NAND, and short-write patterns;
- confirms a successful flash, explains that the camera is still booting, waits 60 seconds,
  and then automatically opens its web login;
- lets the user save a complete serial recovery log.

## What you need

- An owner-controlled ADC-VC726 matching the exact hardware table above
- A 3.3 V USB-to-TTL serial adapter
- Ground, TX, and RX connections—**never connect adapter VCC**
- Normal PoE power for the camera
- A direct or isolated Ethernet connection
- Official Hikvision package
  [`IPC_G1_EN_STD_5.5.82_181211`](https://www.hikvisioneurope.com/eu/portal/?dir=portal%2FTechnical%20Materials%2F00%20%20Network%20Camera%2F00%20%20Product%20Firmware%2FG1%20Platform%2FG1%20platform%20%28DS-2CD2XX5%202XX3%202XX7G1%203XX3%203XX5%20XM67X6%29%2F2XX5%202XX3%202XX7G1%203XX5%203XX3%20XM67X6non-Fisheye%20Multilanguage%2FV5.5.82_Build181211)

The firmware is not included in this repository. Select the package's `digicap.dav`; the app accepts only this SHA-256:

```text
0d7f4edf93e3db610a2d663514220ca3b45138fa039dfecafb01860b3b6ea6df
```

## Run from source

Install [uv](https://docs.astral.sh/uv/), then:

```bash
git clone https://github.com/jessehornbuckle/adc-vc726-recovery-tool.git
cd adc-vc726-recovery-tool
uv sync --extra dev
uv run python run_app.py
```

## Basic workflow

1. Open the camera with PoE disconnected and physically verify every hardware identifier.
2. Connect only UART ground, TX, and RX. Leave both supply pins disconnected.
3. Select `digicap.dav` and let the app verify its exact hash and size.
4. Connect the UART and let the camera finish a normal boot to its Linux `#` prompt.
5. Click **1. Capture and save hardware profile**. The app runs the protected shell's
   read-only `dmesg` command and saves the result under `Documents/ADC-VC726 Recovery Logs`.
6. When prompted, unplug Ethernet/PoE and confirm. Keep it unplugged during the app's
   10-second power-off countdown.
7. Click **2. Start Ctrl+U boot-interrupt window**, then reconnect Ethernet/PoE when the
   button tells you. The app transmits Ctrl+U before power-up so the two-second countdown
   is not a manual race.
8. At `HKVS #`, click **3. Verify read-only fingerprint**. The app combines the saved
   hardware evidence with live U-Boot settings and requires their MAC addresses to match.
9. Click **Start verified TFTP server**. On macOS, approve the administrator prompt so the
   app can temporarily assign `192.168.1.128/24` to the camera-facing network adapter.
10. Confirm that the built-in TFTP server is listening on UDP port 69.
11. Review every safety gate and enter the required risk phrase. The app verifies U-Boot's
    exact four format targets, formats them, safely probes for software reboot, catches U-Boot,
    and only then sends the update. Follow the PoE prompt only if software reboot is unavailable.
12. Do not interrupt power during formatting, transfer, or NAND writing.
13. After reboot, the app explains that the camera is still booting, waits 60 seconds, and
    automatically opens `http://192.168.1.64` for activation and ONVIF/RTSP configuration.

See [Hardware profile](docs/HARDWARE_PROFILE.md) and [Safety model](docs/SAFETY.md) before using the write function.

## Current alpha limitations

- Automatic temporary network setup is currently implemented on macOS. Other platforms
  still require the host address to be assigned manually.
- macOS displays one administrator prompt when the button configures the temporary address
  and starts the narrow TFTP helper on UDP port 69.
- Windows builds are currently unsigned. macOS builds are signed with an Apple
  Developer ID certificate, notarized by Apple, and checked with Gatekeeper before
  GitHub Actions publishes the downloadable artifact.
- The success screen requires both exact `Write Flash [OK]` and `UPDATE COMPLETE` markers; the saved serial log remains the source of truth.
- The guarded format-before-flash sequence is limited to the exact U-Boot command description
  proven on the supported ADC-VC726 hardware.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
```

The core validators are independent from the GUI so they can be tested without attached hardware.

## Legal and ethical use

Use this project only on hardware you own or are authorized to service. It is intended for repair, interoperability, and continued local use of otherwise functional equipment. It does not bypass a remote account, obtain subscription services, or include proprietary firmware.

## License

[MIT](LICENSE). Firmware and vendor trademarks remain the property of their respective owners.
