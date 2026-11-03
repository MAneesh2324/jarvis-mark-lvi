# Install the customized JARVIS on another Mac

Only people invited to this **private** GitHub repository can clone it. The owner
can add a collaborator in GitHub → repository Settings → Collaborators. Each
person uses their own GitHub login, Gemini API key and local memory. No API key,
personal memory, recordings or macOS permission grants are included here.

## Requirements

Use macOS 15+ and Python 3.13. Microphone + system audio with the current echo
reduction pipeline requires macOS 27; older Macs can use `audio=system` or
`audio=none`. Gestures require a supported MediaPipe wheel and a camera. Native
screen recording has been tested on Apple Silicon; Intel needs separate hardware
validation. Install Xcode Command Line Tools (`xcode-select --install`) and
Homebrew from their official sources if missing.

## Install

Run these in Terminal, replacing YOUR_GITHUB_USER if GitHub asks for a login.
Use GitHub CLI authentication or a credential manager; never put a token in the
clone URL.

```sh
brew install python@3.13 ffmpeg node
cd ~/Desktop
git clone https://github.com/MAneesh2324/jarvis-mark-lvi.git Mark-LVI
cd Mark-LVI
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-advanced.txt -r requirements-earth.txt -r requirements-portable.txt -r requirements-recording.txt
python -m playwright install chromium
python native/build_launcher.py
open "../Mark LVI.app"
```

The build creates `Mark LVI.app` beside the cloned folder. Keep the folder and
virtual environment in place. The build embeds the local paths; rebuild after
moving them. Do not copy another person's compiled launcher or `.venv`. Routine
Python updates to JARVIS do not require rebuilding the native launcher.

The setup screen asks for your own Gemini API key. Billing and API quotas belong
to that key's account. Configure optional integrations in the app if needed.

## Optional local hand gestures

```sh
source .venv/bin/activate
python -m pip install -r requirements-gestures.txt
python native/setup_gestures.py
```

Enable **Controls → Hand Gestures** after granting Camera access. Frames stay
local. The model installer verifies the official model against a pinned hash.
Gestures share the camera exclusively with live preview and snapshots.

Optional local speech recognition uses `requirements-local-voice.txt`; models
are downloaded separately and are excluded from GitHub. Earth library assets are
bundled with their license files; npm is available for updating the libraries.

## macOS permissions

Launch the new **Mark LVI.app** first. In System Settings → Privacy & Security,
enable Microphone for voice; Camera for camera assistance/gestures; Screen &
System Audio Recording for recording and screen assistance; Location Services
for device-centered maps; Accessibility for requested computer control.
Grant only features you use. Each person must approve these on their own Mac.

If a switch is on but the app reports denied after a native rebuild, remove only
Mark LVI from the corresponding permission list, add the current app again, then
fully quit and reopen it. Native apps built here are locally ad-hoc signed, not
Apple-notarized distribution packages.

## Features and local data

See [ADVANCED-FEATURES.md](ADVANCED-FEATURES.md) for voice recovery, local knowledge
refresh, trading/security reference data, missions, development tools, Earth,
recording with audio/echo reduction, hand gestures, encrypted portable memory and
scenario comparisons. These are implemented features with documented limits,
not unrestricted autonomy or model self-training. Configure automatic knowledge
refresh locally; the owner's private refresh configuration is not copied.

Mission Control uses compact buttons and a More tools menu. Memory exports use a
passphrase entered only in the local UI. Share a vault separately only if you
intend to share its contents; vaults are excluded from Git. New clones begin
with fresh personal memory.

Recordings live in `recordings/` inside the clone. Both-mode recording finalizes
local adaptive echo reduction on stop, then saves one mixed audio track. A
headset reduces acoustic leakage further. Processing can take time; wait while
FINALIZING AUDIO is displayed. No recording audio is uploaded by this pipeline.

## Updating

Stop recording, close JARVIS, then run:

```sh
git pull --ff-only
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-advanced.txt -r requirements-earth.txt -r requirements-portable.txt -r requirements-recording.txt
open "../Mark LVI.app"
```

Update the optional gesture/local-speech dependencies if you use them. Avoid
rebuilding the native launcher unless its source, location or Python changes.
Keep API keys and personal runtime files ignored, including in a private repo.
