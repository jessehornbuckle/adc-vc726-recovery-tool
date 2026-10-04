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

- a complete, automatically saved Linux hardware profile bounded by capture markers;
- evidence of the expected Ambarella S3L or Micron NAND platform in that profile;
- the `HKVS #` prompt;
- one of the explicitly proven per-camera bootloader addresses (`192.168.1.65` or
  `192.168.1.66`) and the expected TFTP-server address (`192.168.1.128`);
- the MAC address captured from Linux to exactly match U-Boot's live `ethaddr`.

Step 1 sends only `dmesg`, which is supported by the camera's protected Linux shell;
the app adds its own capture boundaries after the shell prompt returns. Step 3 sends
only `help` and `printenv`. All are read-only.

## Gate 4: controlled transfer

The built-in server exposes only the already verified firmware under the expected filename. The app must remain connected to both UART and TFTP before enabling the write button.

## Gate 5: deliberate destructive-action confirmation

The user must type `I ACCEPT BRICK RISK` and approve a second confirmation before the app
sends any destructive command.

## Gate 6: exact format preflight

The app first sends the read-only `help format` command. It proceeds only if this U-Boot
instance advertises exactly `app_pri`, `app_sec`, `cfg_pri`, and `cfg_sec`. It then sends
`format`, waits for the `HKVS #` prompt to return without a format error, and only then sends
`upd digicap.dav`. A missing prompt, command error, or different target list stops the sequence
before the firmware update is sent.

## Stop conditions

Stop if any identifier differs, serial text is garbled, the firmware digest fails, partition names differ, unexpected NAND errors appear, or reliable power cannot be maintained.

The app detects the known `IElang.tar` short-write failure and stops. A fresh guarded run uses
the same verified format-before-flash sequence; it never formats an unrecognized target list.
