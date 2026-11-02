# Voice, memory and conversation recovery

Open **⚙ → Conversation Recovery** to search saved conversation text, pause or
resume saving, and add corrections for names JARVIS mishears. History search shows
up to 20 matches. The speech dictionary previews five entries; voice commands can
list or remove any entry.

Try these commands:

- “Continue our last conversation.”
- “Search our conversations about my project.”
- “Show recent conversation sessions.”
- “When you hear Navy, I mean Nivi. Remember that correction.”
- “List my speech corrections.”
- “Remove the speech correction for Navy.”
- “Pause conversation saving.” / “Resume conversation saving.”
- “What do you remember about me?”
- “Correct my [listed fact] to [new value].” / “Forget that stored fact.”
- “Undo.”
- “Diagnose my microphone and speakers.”
- “Use patient listening mode.” / “Use natural listening mode.”

## What recovery saves

Completed voice transcripts, typed requests successfully sent to the model, and
completed assistant replies are written locally as they finish. No microphone
audio is stored. Recent text from the last session containing a user message is
included on the next startup to help follow references; older text is searchable.
Historical actions are never automatically replayed. This recovered excerpt is
sent to your configured conversation provider along with the normal prompt.

Unfinished turns, unsent text and conversations before this upgrade cannot be
recovered from the journal. Existing summaries remain separately searchable with
conversation_history. Recovery depends on a writable disk. Pausing stops new
journal writes and future automatic recovery context; existing history and the
separate facts/summary features remain available. Context already sent to a model
cannot be withdrawn by pausing. Hiding a session is reversible, not disk erasure.

## Corrections and voice

Speech corrections are interpretation hints, not audio-model training. They take
effect through the current tool result and are loaded automatically on future
connections. Original transcripts stay unchanged. Correct stored personal facts
separately when needed. Corrections support undo, and the dictionary holds 40
entries of at most 100 characters each.

Listening presets apply to Gemini Live on the next connection. Patient mode
allows longer pauses; quick mode can clip speech. Use Audio Devices → TEST to
verify actual microphone input or speaker sound.

## Local storage and verification

- Personal facts: memory/long_term.json, written atomically with a previous valid
  copy in memory/long_term.backup.json for recovery from a damaged or missing file.
- Session summaries: memory/conversations.db.
- Completed conversation text and speech dictionary: memory/conversation_journal.db.

These personal files and API credentials are ignored by Git. No new service or
Python dependency was added. Tests use temporary files, not your personal memory.
Run `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`.

## Responsiveness and android face

Ordinary searches and price lookups now fetch source results directly, preferring
DuckDuckGo with an automatic fallback; the conversation model supplies the final
answer. The quick path has a six-second wait limit and does not retry a separate
Gemini model ladder. Explicit deep research still uses the detailed research path.
Network times vary; this does not guarantee faster responses to every request.

Conversation text is written in order by a dedicated background thread, outside
the audio receive loop and its shared executor. A bounded queue protects memory.
Unsaved queued turns can still be lost in a sudden crash; a normal Python shutdown
tries a short flush. Saving errors are surfaced in the activity log.

Instant read-only keyboard commands work even without a model connection:

- `/help` — command list
- `/time` or `/time Asia/Kolkata` — exact local/named-zone time
- `/recall favorite person` — personal facts
- `/history project` — saved conversation text
- `/perf` — measured local-command, tool, disk-write and typed-response timings

These commands display text without speaking. Timings are process-local, capped
at 200 samples, and store no transcript text. Typed response timing ends at the
next received audio, before playback; overlapping audio can affect it. Voice
end-of-speech latency is not measured.

The reactor display is selected. The added human portraits and portrait lip-sync rig were removed at your request.

## Screen workspace

Open **Controls (🎛)** for:

- **Record Screen / Stop Recording:** save the primary display to a local MP4.
- **Open Recordings:** reveal the recording folder in Finder.
- **Analyze Screen Now:** share one current screenshot and ask for a concise next step.
- **Work With Me:** review changed screens periodically and offer ideas while idle; click again to stop.

The header shows screen-sharing and recording state independently. Nothing starts
automatically. Say “Start screen recording”, “Stop screen recording”, “Analyze my
screen”, “Work with me on this code”, or “Stop watching my screen”. You can also
type `/screen record`, `/screen stoprecord`, `/screen analyze`, `/screen watch`,
and `/screen stop`. Stopping co-pilot does not stop recording, and vice versa.

On macOS, enable Screen Recording for **Mark LVI** when using the Desktop app under System
Settings → Privacy & Security → Screen & System Audio Recording, then restart
JARVIS. The app refuses capture when permission is unavailable rather than
claiming it can see your screen.

Recordings are silent MP4 files under `recordings/` (default 8 fps, at most
1600×1000 with aspect ratio preserved). No system or microphone audio is recorded.
Use Stop Recording to finalize a playable file; abrupt termination can leave an
incomplete MP4. Recording is local and does not itself send frames to a model.

Analyze Now and Work With Me share compressed screenshots with the currently
configured vision conversation model. Co-pilot samples at most every 30 seconds
by default (voice tool allows 15–300 seconds), skips mostly unchanged screens,
and waits while JARVIS speaks or the user recently spoke. It reuses the existing
conversation rather than creating a second model session. It suggests ideas and
never performs clicks, edits or messages based on screenshot content. A stop
prevents future sends, including a capture still in progress; images already sent
to the provider cannot be withdrawn.

Only the selected/primary visible display can be analyzed. Hidden windows,
off-screen content, tiny text and fast-changing details are not reliably visible.
A vision-capable model is required. Recordings are ignored by Git and created
with owner-only file permissions.

## British assistant voice

Controls → **Voice: British Assistant** selects an original composed British
English delivery with clear diction, measured but brisk pacing and restrained dry
wit. Click to return to Standard. The existing base voice remains selectable under
Customize Assistant. This is a delivery preset, not a clone of the movie actor.
Accent and timbre depend on the selected voice/model; non-English replies keep the
user's language. Changing delivery reconnects the session, carrying available
recent local conversation context forward. No additional voice service is used.

## Complete work toolkit

Open **Controls → Projects & Workspace**. Five tabs expose the six additions:

1. **Projects:** save a name, goal, progress, next step and optional existing
   folder; save-and-use makes it active. Add tasks and toggle completion. The
   active project is included in new conversation setup and each screen analysis.
   Existing voice sessions can query it with project_workspace.
2. **Routines:** build and save 1–12 ordered steps using the form. Supported
   actions open apps/documents/folders, arrange an app window left/right/maximized,
   set volume, and activate a project. Run executes only the saved steps, stops
   on failure and reports requested/unverified actions separately. Window layout
   needs macOS Accessibility permission and may be limited by app minimum sizes.
3. **Screen focus:** choose a display, exact visible macOS window, or rectangular
   region. Refresh windows before selecting one. A closed window stops capture;
   changing the target invalidates a capture in progress. Regions include any
   visible overlapping windows. This scope affects AI analysis, not independent
   whole-display recording.
4. **Troubleshooting:** Diagnose Visible Error saves a before screenshot and
   obtains evidence-grounded guidance. After attempting a fix, Check My Fix sends
   before/after images from the same target. Reports distinguish visible change
   from proof of a backend fix. Evidence/reports stay in memory/screen_cases.
5. **Local voice:** toggle local command mode on explicitly. A locally installed
   tiny speech model recognizes a limited English grammar on CPU. Model warm-up
   happens off the voice event loop. Command audio is blocked from Gemini while
   the mode is on, including loading/error states; turn it off for normal cloud
   conversation. Mute and push-to-talk gates also suppress the local microphone.
   Recognizer output is shown in the log; uncertain/unmatched/out-of-range commands
   do not execute. Local spoken results use the macOS system voice. Accuracy and
   latency vary; this is not unrestricted offline conversation.
6. **Recording notes:** new recordings save changed keyframes about every ten
   seconds and accept timestamped markers. Storage is bounded by thinning the
   sample timeline. Summarize Selected Recording shares up to eight sampled frames
   plus markers with the existing vision conversation; the result is saved next
   to the MP4 as .highlights.md. It is not full-video or audio transcription.

Local command examples: “open Safari”, “volume thirty percent”, “timer five
minutes”, “remember coffee is black”, “recall coffee”, “run routine Start work”,
“project status”, “what time is it”, “undo”. Only supported commands run; no
freeform shell execution is supported. Timers are saved in the workspace database
and fire once when JARVIS is running; overdue ones announce at the next startup.

Keyboard equivalents include `/local COMMAND`, `/localvoice on`, `/localvoice off`,
`/project`, `/project NAME`, `/routine NAME`, `/screen diagnose`, `/screen check`
and `/screen highlights`. Use /help for the list.

Project/task/routine/timer state is in memory/workspaces.db. The local speech
model is about 75 MB under models/whisper and is ignored by Git. Optional speech
dependencies are listed in requirements-local-voice.txt. Screen recording and
window analysis still require macOS Screen Recording permission; window layout
requires Accessibility. Nothing enables ongoing screen sharing, recording or local
voice capture automatically at startup.

## Fast response profile

Controls → **Response: Fast** reduces the end-of-speech pause to 400 ms, disables
proactive relevance filtering and requests zero model thinking budget. It also
asks for a direct, short answer to ordinary questions. The original preferences
are preserved; switch to Standard to use them again. Explicit voice-pacing choices
override Fast. Changes reconnect the voice session while carrying recent context.

Short pauses can end a turn too early, and removing relevance filtering can make
JARVIS answer background conversation. Use Standard or patient listening if that
happens. Network, model availability and complex tool work still affect latency.
No feature is removed, and screen-resolution settings are unchanged.

A controlled synthetic-audio check compared the current proactive/default-pause
setup with Fast on the same short arithmetic question. Time from the last speech
chunk to first returned audio was 2.024 s versus 1.219 s in that paired test. This
is a narrow test, not a guarantee for live speech, tools or network conditions.
Fast uses the stable v1beta Live endpoint when proactive features are disabled.

## Earth, maps and optional location

Controls → **Earth & Maps** opens an embedded panel in the assistant area. Switch
between a 3D globe, street map and satellite imagery; pan/zoom, enter coordinates
or choose a city. The globe uses locally bundled Natural Earth imagery. Street
and satellite tiles require internet; satellite imagery is not live. Use Return
to Assistant to leave the panel. It is loaded only on demand and pauses rendering
when hidden so ordinary voice startup does not load the web renderer.

Use **Mark LVI.app** on the Desktop for device location. This dedicated local
launcher declares the microphone/location purposes that the bare Homebrew Python
host lacks. “My device location” requests your explicit permission and then the
macOS location service; accuracy depends on the device and available location
sources. “Approximate location” separately asks to contact ipapi.co using your
public IP and labels its city-level result. VPNs can make that result wrong.
Manual coordinates work without location access.

Fixes stay in the current app session, not personal memory or a location-history
file. A viewed area's map tiles are requested from OpenStreetMap or Esri, so those
providers receive tile requests for the viewed area. Clear Location removes the
active fix/markers; previously sent provider requests cannot be withdrawn. The
embedded browser uses an in-memory profile and denies camera/microphone requests.

Voice examples: “Show Earth”, “Show the satellite map”, “Fly to latitude 9.9312,
longitude 76.2673”, “Ask for my location”, “Close the map”. Keyboard equivalents:
`/earth`, `/map`, `/satellite`, `/location`.

Libraries are bundled under web/earth/vendor; package versions are locked in
web/earth/package-lock.json. The optional renderer dependency is recorded in
requirements-earth.txt. The native launcher source is native/launcher.c.

Provider references: [Cesium imagery](https://cesium.com/learn/cesiumjs/ref-doc/TileMapServiceImageryProvider.html),
[OpenStreetMap tile policy](https://operations.osmfoundation.org/policies/tiles/),
[Esri attribution](https://support.esri.com/en-us/knowledge-base/what-is-the-correct-way-to-cite-an-arcgis-online-basema-000012040),
and [Qt location permissions](https://doc.qt.io/qt-6/qtwebengine-webenginewidgets-maps-example.html).

Rebuild the native launcher using `.venv/bin/python native/build_launcher.py`.
It is tied to this installation's Desktop path and Homebrew Python framework;
rebuild after upgrading Python. The Desktop command now opens the dedicated app.
Mac Metal atmosphere shader effects are disabled for compatibility; the globe's
Earth imagery, zooming and rotation remain enabled.

## Advanced Mission Control

Mission workflows, background checkpoints, restaurant prospecting and private
website concepts, Earth research markers/routes, local briefings, Home Assistant
setup and engineering review are now available in Controls → Mission Control
(`/missions`). See [ADVANCED-FEATURES.md](ADVANCED-FEATURES.md) for the complete
capability list, setup, validation and limits. Calendar and home integrations
need your own data/server; no accounts were connected automatically.

## Mark LVI screen-recording permission repair

The Desktop app uses **Mark LVI** (`com.maneesh.marklvi`) as its privacy identity.
Terminal or another Python version having permission does not grant this app
screen access. Controls now includes **Screen Recording Permission**, also
available as `/screen permission` or the `screen_recording` tool's `permission`
action. Failed recording starts show this setup dialog and report the correct
app rather than claiming success or silently retrying.

Choose **Open Screen Recording settings**, authenticate locally if macOS asks,
then enable **Mark LVI** in Privacy & Security → Screen & System Audio Recording.
If missing, use **+** and add `/Users/maneesh/Desktop/Mark LVI.app`.
The dialog can explicitly request the native macOS prompt on the GUI thread and
recheck access. It never grants itself permission or starts capture. Quit and
reopen Mark LVI after macOS requests a relaunch, then start a recording normally.
Recordings are local silent MP4 files under `recordings/`; AI sharing is separate.

Verified during repair: Mark LVI was missing from the system permission list,
while Terminal was enabled. Eleven capture/permission tests passed, including a
real MP4 encode/decode using synthetic screen frames; the available regression
set passed 96 tests. After the user enabled Mark LVI in macOS settings, a live
5.62-second local recording was started/stopped through the native app. Its MP4
decoded successfully: 45 frames, 8 fps, 1512 × 982, owner-only mode 0600. Both
recording and AI screen sharing were off after verification. The app signature was verified and the
native binary was not rebuilt, preserving its existing identity.

## Camera crash repair

The macOS crash report identified a TCC termination because the native app had
no NSCameraUsageDescription. The Desktop bundle and reproducible launcher build
now include that camera purpose. The updated bundle signature is verified.
Camera snapshot/probe and live-stream paths check permission before opening any
OpenCV device. Missing/denied access returns a recoverable error and opens a
local setup dialog; the vision busy state is cleared so a later request works.
Permission is requested asynchronously through Qt on the main GUI thread.

Use Controls → Camera Permission. The app has been reopened with the repaired
bundle; the dialog was verified without capturing an image or granting access.
Approving permission alone captures nothing. When the user later requests camera
analysis, its image goes to the configured vision conversation service. Camera
access remains the user's choice. macOS may require renewed permissions after
an updated local app signature; existing screen-recording settings should be
rechecked if macOS asks.
