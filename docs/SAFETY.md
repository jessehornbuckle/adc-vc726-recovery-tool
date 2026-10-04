# Safety model

The app uses independent gates because no single check is enough to make a cross-flash safe.

## Gate 1: physical inspection

The user must confirm ownership, model, printed board revision, processor, NAND, and accepted brick risk. The PCB revision cannot be trusted to software discovery alone.

## Gate 2: firmware identity

The selected file must simultaneously match:

- filename `digicap.dav`;
- size `36,390,527` bytes;
- the known SHA-256 digest.

A renamed or modified file cannot pass.

## Gate 3: read-only serial fingerprint

Before any write command, the app requires:

- the `HKVS #` prompt;
- one of the explicitly proven per-camera bootloader addresses (`192.168.1.65` or
  `192.168.1.66`) and the expected TFTP-server address (`192.168.1.128`);
- evidence of the expected Ambarella S3L or Micron NAND platform.

The probe sends only `help` and `printenv`.

## Gate 4: controlled transfer

The built-in server exposes only the already verified firmware under the expected filename. The app must remain connected to both UART and TFTP before enabling the write button.

## Gate 5: deliberate write confirmation

The user must type `I ACCEPT BRICK RISK` and approve a second confirmation before the app sends `upd digicap.dav`.

## Stop conditions

Stop if any identifier differs, serial text is garbled, the firmware digest fails, partition names differ, unexpected NAND errors appear, or reliable power cannot be maintained.

The alpha release detects the known `IElang.tar` short-write failure but does not automatically run `format`. That command is destructive and should remain a separate, evidence-driven recovery action.
