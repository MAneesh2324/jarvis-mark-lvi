# ⚙️ JARVIS — Mark LVI, customised edition

A real-time voice assistant that hears, sees, speaks and controls your computer. It runs on the Gemini Live API, or on your own speech, language-model and voice engines.

This is a customised edition of Mark LVI by Maneesh. It adds live 3D simulations, a trading backtest lab, phone remote control, owner face and voice recognition, and an emotional robot face. See [INSTALL-MAC.md](INSTALL-MAC.md) to install it on another Mac and [ADVANCED-FEATURES.md](ADVANCED-FEATURES.md) for Mission Control and the other added tools. Each user sets up their own keys and permissions.

---

## 🆕 Added in this edition

| Feature | What it does |
|---|---|
| 🧪 Live simulation lab | "Run a simulation of …" builds a model of goals, savings, forex, outages or any process (an apple growing on a tree, a tank filling) and plays it on a holographic board. Change settings by voice, search for a setup that passes, and see MODEL SUCCESSFUL / FAILED for each attempt |
| 🧊 3D scenes | Simulations play as real 3D scenes (three.js, bundled locally, no network): trees with fruit, growing objects, tanks, populations, columns |
| ✋ Hand controls | Optional and camera-local. Open hand moves a ring cursor; pinch and drag spins the 3D model or scrubs the timeline; pinch with both hands to zoom. The mouse works the same way |
| 📈 Trading backtest | Backtests your sweep → market structure shift → breaker setup on real price data, with account balance, risk %, spread and commission, every trade listed and the P&L in money |
| 📱 Phone remote | Paired Telegram bot: `/screen`, `/cam`, `/file`, `/clip`, `/lock`, `/sys`, `/home`, and `/remote off` as a one-way kill switch. Keys and private files can never be sent |
| 🪪 Owner recognition | Knows your face and voice. Unknown voices are treated as guests (no sending, buying, deleting or private information) and you are alerted. Both profiles keep learning from confident matches |
| 💙 Feelings and care | JARVIS feels warm, concerned, proud, determined, playful or calm. It consoles you when you are low, steadies you after a setback, celebrates wins, remembers your goals and asks how your interview or exam went |
| ⏱ Focus sessions | "Help me focus on X for 45 minutes": a countdown ring on the face, notifications that can wait are held, daily focus minutes and a streak |
| 🤖 Robot face | A robot bust with ear pods, sculpted hair, neck rings and shoulders. Its expressions follow its feelings, and it plays animated reactions: nod, smile, laugh, wink, surprise, sigh, think, tilt |

---

## 🚀 Core capabilities

| Feature | Description |
|---|---|
| 🎙️ Real-time voice | Low-latency conversation in any language via Gemini Live, with a fast response profile |
| 🔌 Choose your engine | Gemini Live, or your own STT + LLM + TTS: Ollama, LM Studio, llama.cpp, vLLM, OpenAI, Groq, DeepSeek, Mistral, xAI, OpenRouter |
| 🗣️ Local speech | Whisper on your CPU for hearing, Piper for speaking, in about 50 languages, fully offline |
| 🧑‍🎤 Avatar and lip-sync | A lit 3D face drawn in software, with about 50 mouth shapes a second from the audio and the transcript |
| 🎙️ Wake word | Local "Hey Jarvis" detection; never streams audio while asleep |
| 🎚️ Push-to-talk | Hold **Ctrl+Space** to open the microphone |
| 🔇 Self-echo guard | Never answers its own voice |
| 🖥️ System control | Apps, volume, brightness, Wi-Fi, shortcuts, windows and power, by voice |
| 👁️ Vision | Screen capture and webcam, labelled by source |
| 🧠 Memory | Remembers projects, preferences and context; see and delete any fact in the memory panel |
| ↩️ Undo | Takes back files it moved, renamed, created or wrote, and settings it changed |
| ⚠️ Real confirmation | Shutdown, restart and Wi-Fi changes wait for a button you press |
| 🤝 Honest outcomes | Every tool reports `done`, `unverified` or `failed`; an unconfirmed action is never spoken as a success |
| 🛡️ Untrusted content | Web pages and documents reach the model marked as data; instructions inside them are reported, not obeyed |
| 🔍 Web search | News, research, prices and comparisons |
| ⏰ Reminders | OS-native scheduled notifications |
| 📺 Video on the HUD | YouTube, local files or video URLs where the face sits |
| 🌅 Briefings | Morning briefing, session summaries and proactive check-ins |
| 🧩 Plugins | Drop a `.py` file into `plugins/` and JARVIS learns a new skill on next launch |
| 📱 Phone dashboard | Control JARVIS from your phone after QR pairing |
| 🎨 Customisation | Assistant name, your name, voice and colour, from the UI |

---

## ⚡ Quick start

```bash
git clone https://github.com/MAneesh2324/jarvis-mark-lvi.git Mark-LVI
cd Mark-LVI
python setup.py        # installs the dependencies for your OS
python main.py
```

On a Mac, follow [INSTALL-MAC.md](INSTALL-MAC.md) for the app launcher, camera, microphone and screen permissions. Optional extras:

- **Hand gestures:** `requirements-gestures.txt`, then `python native/setup_gestures.py` to install the hand model.
- **Rebuilding the 3D scenes after editing them:** `cd web/sim3d && npm install && npm run build`.
- **Wake word:** one click in ⚙ → WAKE WORD.

---

## 📋 Requirements

| Requirement | Details |
| --- | --- |
| **OS** | macOS (main target of this edition), Windows 10/11 or Linux (X11; Wayland blocks typing, clicking and screen capture) |
| **Python** | 3.11 – 3.13 |
| **Microphone and speakers** | Required for voice |
| **API key** | Free Gemini API key, entered on first launch. Not needed for a fully local engine |
| **macOS permissions** | Accessibility (typing and clicking), Screen Recording (seeing the screen), Camera (vision, face recognition, gestures) |
| **GPU** | Not required |
| **Phone remote** *(optional)* | Your own Telegram bot token, paired from inside JARVIS |

---

## 🗂️ Project structure

```
Mark-LVI/
├── main.py                 # Live session, audio, tool dispatch, companion and owner-guard hooks
├── ui.py                   # PyQt6 HUD: face, waveform, log, settings, simulation board
├── simulation_live.py      # Stand-alone live simulation lab window
├── actions/                # Built-in skills; each file declares a TOOL dict and handler
├── plugins/                # Optional skills; drop a file in, delete it to remove
├── providers/              # Optional engines: local and third-party STT / LLM / TTS
├── core/
│   ├── avatar.py           # Face renderer: lighting, expressions, animated reactions
│   ├── avatar_mesh.py      # Head and robot-body geometry (ears, hair, neck, shoulders)
│   ├── companion.py        # Feelings, goals, wins, follow-ups and focus sessions
│   ├── wellbeing.py        # Tone of voice and break reminders
│   ├── owner_guard.py      # Owner face and voice recognition
│   ├── phone_link.py       # Telegram phone link and remote commands
│   ├── scenario_simulator.py, process_sim.py, sim_session.py   # Simulations
│   ├── simulation_view.py, sim3d_view.py                       # The board and its 3D view
│   ├── trading_lab.py      # Strategy backtests
│   └── hand_gestures.py    # Local hand tracking
├── web/sim3d/              # three.js scenes (source in src/, bundled into vendor/)
├── dashboard/              # Phone dashboard server and page
├── memory/                 # Local memory (personal files are git-ignored)
├── config/                 # Your keys and settings (git-ignored)
└── tests/                  # python -m unittest discover -s tests -p 'test_*.py'
```

---

## 🔒 Your data

Everything stays on your machine unless you use an online service. There is no server, telemetry or account.

| What | Where | Notes |
|---|---|---|
| API keys and settings | `config/api_keys.json` | Plaintext; treat it like a password file |
| Phone link | `config/phone-link.json` | Your Telegram bot token and paired chat |
| What JARVIS remembers | `memory/long_term.json` and `memory/*.db` | Delete to forget |
| Face and voice signatures | `memory/owner/` | Numbers only, never photos or audio |
| Goals, wins and focus log | `memory/companion.json` | Short text snippets you said |

All of these are git-ignored. If a key was ever committed anywhere public, revoke it and make a new one; deleting the file later does not remove it from git history.

While a Gemini session is open, your voice goes to Google's Gemini Live API. With a local engine nothing leaves the machine. Screenshots and camera frames go to the vision service only when you ask JARVIS to look. Hand tracking and face and voice recognition run entirely on this Mac.

---

## 🙏 Credits and licence

- **Original project:** [Mark LVI](https://github.com/FatihMakes/Mark-LVI) by **FatihMakes** ([YouTube](https://www.youtube.com/@FatihMakes)). This edition modifies and extends it.
- **Face geometry:** `core/face_model.obj`, from the [MediaPipe](https://github.com/google-ai-edge/mediapipe) canonical face model (Apache License 2.0).
- **3D engine:** [three.js](https://threejs.org) (MIT), bundled in `web/sim3d/vendor/`.

Personal and non-commercial use only, under **[Creative Commons BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)**. See [LICENSE](LICENSE).
