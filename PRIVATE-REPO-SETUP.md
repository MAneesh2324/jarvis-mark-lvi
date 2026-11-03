# Mark LVI source and privacy notes

This repository contains the Mark LVI application and its local upgrades.
The original project's license and attribution are retained in LICENSE and
readme.md. Bundled Earth libraries retain their license and attribution files.

Start with LOCAL-UPGRADES.md and ADVANCED-FEATURES.md for the implemented features,
installation details, privacy controls and validation limits.

API keys, integration tokens, personal memory, conversation databases, calendar
exports, recordings, development copies, generated reports, virtual environments
and downloaded speech models are deliberately excluded. Configure credentials
locally after cloning; never commit them, including in this public repository.

For a fresh Mac installation, follow [INSTALL-MAC.md](INSTALL-MAC.md). The native
launcher build script configures paths for the clone on that Mac. Rebuild after
moving the folder or changing the Python installation. macOS camera, microphone
and screen-recording access are separate per-app permissions and do not transfer
through GitHub. Rebuilding an ad-hoc-signed app can require removing its stale
permission entry and adding the new app again.

The upstream origin is FatihMakes/Mark-LVI. This customized repository
stores the customized source and does not publish changes upstream.
