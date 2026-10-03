# Contributing

Contributions are welcome, especially:

- redacted boot fingerprints from matching ADC-VC726 hardware;
- Windows and macOS packaging improvements;
- safer network-interface and privileged TFTP handling;
- tests that use simulated serial and TFTP clients;
- documentation corrections.

## Safety rule

Do not broaden a hardware profile because another model looks similar. A new profile needs documented board, processor, flash, bootloader, firmware, and recovery-path evidence.

Firmware binaries, private credentials, serial numbers, MAC addresses, and identifying logs must not be committed.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
```
