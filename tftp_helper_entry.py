"""PyInstaller entry point for the privileged macOS TFTP helper."""

from vc726_recovery.tftp_helper import main

if __name__ == "__main__":
    raise SystemExit(main())
