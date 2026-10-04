# macOS signing and notarization

Public macOS releases are signed with an Apple **Developer ID Application**
certificate and submitted to Apple's notarization service before they are
published.

## Required GitHub Actions secrets

| Secret | Contents |
| --- | --- |
| `MACOS_CERTIFICATE_P12` | Base64-encoded Developer ID Application certificate and private key (`.p12`) |
| `MACOS_CERTIFICATE_PASSWORD` | Password used when exporting the `.p12` file |
| `APPLE_API_KEY_P8_BASE64` | Base64-encoded App Store Connect API private key (`.p8`) |
| `APPLE_API_KEY_ID` | App Store Connect API key ID |
| `APPLE_API_ISSUER_ID` | App Store Connect API issuer ID |

Never commit the certificate, private key, passwords, or decoded secret files.

## Release checks

The macOS job must complete all of these checks:

1. Import the Developer ID identity into an ephemeral keychain.
2. Build the app with a reverse-DNS bundle identifier.
3. Sign the nested binaries and app bundle with hardened runtime and a secure timestamp.
4. Verify the signature with `codesign --verify --deep --strict`.
5. Submit the ZIP to Apple's notarization service and wait for acceptance.
6. Staple and validate the notarization ticket.
7. Require Gatekeeper's `spctl --assess` check to pass.
8. Archive the stapled app as the downloadable artifact.

The final release should also be downloaded through a browser and opened on a
different Mac before it is promoted beyond alpha status. This exercises the same
quarantine and Gatekeeper path that an end user will encounter.
