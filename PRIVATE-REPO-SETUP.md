# Personal Mark LVI source backup

This repository contains the Mark LVI application and its local upgrades.
The original project's license and attribution are retained in LICENSE and
readme.md. Bundled Earth libraries retain their license and attribution files.

Start with LOCAL-UPGRADES.md and ADVANCED-FEATURES.md for the implemented features,
installation details, privacy controls and validation limits.

API keys, integration tokens, personal memory, conversation databases, calendar
exports, recordings, development copies, generated reports, virtual environments
and downloaded speech models are deliberately excluded. Configure credentials
locally after cloning; never commit them, even to this private repository.

The current native Mac launcher targets this installation's Desktop paths and
Homebrew Python. Rebuild/adapt native/launcher.c and native/build_launcher.py if
moving the installation. macOS camera, microphone and screen-recording access
remain separate per-app permissions and are not copied through GitHub.

The upstream origin is FatihMakes/Mark-LVI. This private personal repository
stores the customized source and does not publish changes upstream.
