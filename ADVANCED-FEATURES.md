# JARVIS Mission Control

Open **Controls → Mission Control**, type `/missions`, or ask JARVIS to show
Mission Control. The Desktop **Mark LVI.app** and **Launch Mark-LVI.command** use
this installation. Restart JARVIS to load any code changed after it was opened.

## What is available

| Capability | What it does | Practical limit |
| --- | --- | --- |
| Mission mode | Plans and runs research, restaurant prospecting, engineering inspection, saved routines and briefings | Concrete workflows, not an unrestricted autonomous agent |
| Background work | Two workers, bounded queue, step checkpoints, activity log, pause/cancel, failure and completion notices | JARVIS must remain open; in-flight requests finish before a safe stop |
| Continuity | Saves mission evidence, project tasks, next steps, decisions and correction notes locally | Interrupted work requires explicit resume; partial Mac routines are not automatically replayed |
| Screen co-pilot | Existing selected-screen analysis, changed-screen watching, diagnosis and before/after comparison | Opt-in; screenshots go to the configured vision service; cannot see hidden windows |
| Mac actions | Existing app/browser/file tools, plus saved routines with per-action verification | macOS permissions may be needed; a dispatched click is reported as unverified until its outcome is checked |
| Voice | Existing Fast profile, recovery and correction tools; optional voice interruption with echo filtering and buffered speech onset | Experimental interruption depends on microphone, room and speaker echo; off by default |
| Restaurant research | Finds a bounded sample of restaurants without OSM website tags, gathers search links, exports CSV and plots leads | Missing tags/search results do not establish that no website exists; review evidence manually |
| Website concepts | Creates and opens private local restaurant landing-page drafts | Owner review required; no invented menu/reviews/prices, publishing or outreach |
| Earth intelligence | Public-city lookup, mission markers, evidence-based area comparisons and estimated driving routes | Internet-dependent; no live satellite feed, traffic or turn-by-turn navigation |
| Daily briefing | Local project/task/mission summary and recurring events from an imported calendar export | ICS snapshot, not a live Google/Apple calendar connection; daily display requires JARVIS running |
| Smart home | Home Assistant setup, allowed light/switch state reads and verified on/off requests | Requires your own server, token and explicit entity allowlist; nothing connected by default |
| Engineering workspace | Local Python syntax and JSON checks, inventory/TODO report, document/PDF/SVG excerpts and optional AI suggestions | No automatic code execution or edits; runtime tests remain a separate explicit task |

## Start a mission

1. Choose a mission type and enter its required details.
2. **Create plan** records the goal and visible steps without starting them.
3. **Start / resume** queues the job and returns immediately.
4. Review each step's evidence, activity, failures and output in the dashboard.
5. **Open evidence folder** opens private local reports and artifacts.

Voice requests can plan and start work when the scope is already clear. For
example: “Research current Home Assistant options in a background mission.”
JARVIS must report the returned ID/state rather than announcing completion early.

**Restaurant searches ask for a city each time.** City is never inferred from
GPS, an earlier search or your memories. The radius is 500–10,000 metres and
results are capped at 30. The underlying map response is a bounded sample, not a
complete business directory. After research, select a candidate number to create
a private website concept. CSV cells that could become spreadsheet formulas are
escaped. Business-provided text is escaped in HTML and map popups.

Pause preserves completed checkpoints. Resume skips completed steps. Cancelled
jobs do not continue; make a new plan for a new goal. On startup, previously
running/queued jobs become **interrupted**, not completed. Partially attempted
routines require a fresh plan after reviewing their action evidence, because
repeating device/file actions may have side effects. Notes record corrections
and decisions; they do not silently rewrite a running plan.

## Connections and privacy

- **Screen:** use Projects & Workspace to choose the target, then enable co-pilot.
  Screen sharing and local video recording have separate stop controls.
- **Engineering:** choose a folder. Local checks never execute that folder's code.
  Common secret/config folders, credential filenames, symlinks, oversized files
  and dependency directories are excluded. Up to 250 files are inspected.
  For AI suggestions, enter up to six relative paths separated by `|`, preview
  the excerpts, enable **Use AI synthesis**, then start the mission. Only those
  selected excerpts and local check metadata are submitted. PDFs use text from
  up to eight pages; source excerpts are bounded and may be incomplete.
- **Calendar:** import an `.ics` export in Briefing. Recurring events and timezones
  are supported. Import again to refresh; there is no cloud OAuth connection.
  Daily briefing is disabled by default and uses your Mac's local time.
- **Home Assistant:** enter your own server origin, long-lived access token and
  allowed `light.*`/`switch.*` IDs in Smart home. Credentials are kept in a local
  file with mode `0600`, not in voice tools, AI prompts or mission reports.
  Remote servers must use HTTPS. HTTP is limited to local/private-IP hosts.
  Redirects are not followed with the token. **Disconnect** removes local setup.
- **Voice interruption:** enable it in Voice & screen, or type
  `/voiceinterrupt on`. Turn off with `/voiceinterrupt off`; the existing
  Interrupt button remains available. Use headphones for the most reliable
  separation from JARVIS's own playback. It has not been calibrated to your room.
- **AI synthesis:** can use the configured service's quota and may fail when its
  model/account is unavailable. Source evidence and completed checkpoints remain.

Mission records live in `memory/missions.db`, with reports, CSVs and concepts in
`memory/missions/<id>/`. They are private local files and ignored by Git.
Calendar exports and integration settings are also ignored. Restaurant/city
research records are public-place research, separate from the session-only
personal location fix. Device location still requires the Earth panel's consent.

## Map services

City lookup uses Nominatim with explicit city requests, a seven-day local cache,
a serialized maximum of one request per second and an identifying User-Agent.
No autocomplete or bulk geocoding is implemented. Do not submit personal or
confidential addresses. See the
[Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/).
To change providers without updating the app, create `config/place-services.json`:

```json
{
  "geocoder": "https://nominatim.openstreetmap.org/search",
  "overpass": "https://overpass-api.de/api/interpreter",
  "router": "https://router.project-osrm.org"
}
```

The geocoder must provide Nominatim-compatible output, the Overpass endpoint
must support Overpass QL, and the router must support OSRM's route API.
OpenStreetMap data attribution and ODbL source links are included in results and
exports. Public providers can rate-limit or become unavailable; a failed request
is reported instead of manufacturing results. Selected cities go to the
geocoder; restaurant queries go to Overpass; route endpoints go to OSRM; research
queries go to the search provider. Street/satellite tiles retain their existing
provider disclosures. Satellite imagery is not live.

References: [Overpass QL](https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_QL),
[OSRM routing](https://project-osrm.org/docs/v5.24.0/api/),
[Home Assistant REST API](https://developers.home-assistant.io/docs/api/rest/),
[Calendar recurrence](https://recurring-ical-events.readthedocs.io/en/latest/user-guide/examples.html).

## Validation

The full suite passed 81 tests, including persistence/recovery, cancellation,
late-result rejection, private artifacts, no false website claims, HTML/CSV
escaping, calendar recurrence, scoped device control and field-value checks.
The native dashboard opened successfully. Live public example checks succeeded
for city lookup, driving routing and search sources. Home Assistant has no
configured real devices, so its integration is tested with simulated responses.
A further live Overpass-to-restaurant-report check could not run because the
automatic approval review system reached its usage limit; that live path remains
unverified. No personal location, calendar or smart-home token was used in tests.

Install the extra Python dependencies with
`.venv/bin/python -m pip install -r requirements-advanced.txt` if rebuilding this
installation. Existing Earth and local speech dependencies retain their own
requirements files.

## Development sandbox and learnable skills

Restart Mark LVI, then open **Mission Control → Sandbox** or **Skills**.

**Sandbox workflow:** choose an explicit source project and change goal, create
its private source copy, select a copied file and edit it. **Save copy edit**
changes only that copy. Review the unified diff, then run the available
Python/JSON/basic HTML checks. For Python projects with a copied `tests/` folder,
**Run Python unittest tests…** runs real tests and shows their output and exit
status. Tests have a 45-second deadline and an output limit. No tests, zero tests,
failed tests, changing source during tests and stale checks are not reported as
passing validation. Dependencies and private configuration are excluded from the
copy, so some projects require additional setup before tests can pass.

This is a source-file workspace, **not a VM or OS security sandbox**. Requested
project tests run with your Mac user's permissions and can access files/network
outside the copy. Only run trusted test code; the local run button explains this
before execution. No arbitrary test command or shell step is accepted by the new
voice tool. There is no background test execution or automatic dependency install.

AI proposals require selecting 1–6 copied files and enabling sharing. Preview the
selected files first. The configured model receives those files and the change
goal. Its response is stored as a pending proposal; **Stage proposal in copy**
applies it only to the work copy, after checking that it has not changed since
the proposal was requested. Out-of-scope paths, unselected files and oversized
responses are rejected. AI output is not automatically executed or promoted.
**Preview copied HTML** opens the saved HTML in your default browser; its scripts
run as local webpage code. It does not provide a hosted server or full-stack
runtime preview.

**Apply reviewed changes…** requires passing checks on the current revision and
unchanged original hashes. It preserves the source file modes and baseline.
**Rollback applied changes…** restores that baseline only if no newer edits have
been made to the applied source files. Both are explicit local review actions;
the voice tool cannot apply to originals. Checks are limited to the reported
languages/profiles and do not prove that every behavior works. Source copies are
bounded to supported text files, at most 250 files / 16 MB, excluding private
folders, credential filenames, symlinks, dependencies and oversized files.

**Skills workflow:** save a recipe from a completed mission or saved routine, or
edit its declarative JSON in the Skills tab. Each save creates a new unapproved
version; review and approve that exact version before running it. Approval is
not a schedule: a skill runs only on an explicit request. Old versions remain
inspectable and approval can be revoked. Restaurant recipes discard the old
city and ask for a city each time. Learned mission recipes do not automatically
share files with AI.

For teaching, name the skill and choose **Begin teaching**, run supported saved
routines in Projects & Workspace, then **Stop teaching / save draft**. Only the
supported routine steps and their result classifications are captured, up to
12 steps. This does not observe arbitrary app activity, record keystrokes or
capture screen/audio. Review the resulting draft before approving it. Supported
routine actions remain open app/path, arrange window, set volume and activate a
saved project; shell commands are excluded.

Private copies, proposals, diffs, test output and rollback baselines are under
`memory/sandboxes/`; versioned workflows are in `memory/skills.db`. Both are
ignored by Git. No extra dependency was needed for these two additions.

Validation for this addition: 12 focused tests passed, including actual passing
and failing unittest runs in source copies, original preservation, CRLF rollback,
stale proposals/checks, conflict protection, unsafe path rejection, version
approval and per-run city requirements. The available regression set passed
92 tests; the existing Earth loopback-server test was excluded in this restricted
shell (it passed in the earlier full suite). Both new tabs rendered in a local
Qt UI check. Live AI edit generation was not called during this validation.

## Conversational learning, forex and cybersecurity

These features are part of ordinary JARVIS conversation, without new dashboard
tabs. The dashboard tab bar has been replaced with compact Missions, Sandbox and
Skills buttons; other existing setup screens are under More tools.

Automatic public refresh is enabled at the user's request, once per hour while
Mark LVI is running. It refreshes BBC world headlines, NASA science headlines,
ECB reference data and CISA KEV intelligence. Sources retain their original data
and fetch dates. An offline fallback is explicitly labeled and never gets a new
observation timestamp. The first forex cache contains the available 90-calendar-
day reference series; this is not a real-time broker feed. No trading account is
connected and no trade is executed. No network scanning/exploitation is performed.

Completed/failed missions automatically record deterministic outcome lessons
locally, so JARVIS can remember to check evidence, handle failures honestly and
avoid blindly repeating an unsuccessful workflow. These are not proof that a
research answer is correct. Evidence-backed factual corrections are drafts until
the user explicitly approves that lesson. Lessons expire, can be revoked, and
are retrieved into conversation rather than modifying model weights or code.

Try saying: “What have you learned recently?”, “Remember this correction with
this evidence…”, “Review my recorded mistakes”, “Give me the EUR/USD reference
update”, “Calculate a position-size scenario using these inputs…”, “Save this
realized trade result”, “Analyze my USD trade journal”, “What known-exploited
vulnerabilities affect [product]?”, “Look up CVE-…”, or “Give me world updates.”
Ask “Stop automatic learning” to disable the hourly refresh. Current conversation
can use the knowledge tool to access refreshed data; the compact source brief
and retained lessons are included when the voice session next connects.

Forex analytics include observation change, SMA20/50, simple RSI14 and historical
log-return volatility. These use daily observations, not OHLC candles, live
spreads or actionable signals. Position sizing is arithmetic on user-supplied
risk, equity, stop and currency-conversion inputs, excluding fees/slippage/gaps.
Trade-journal statistics use explicitly entered realized results and keep account
currencies separate. Journal data stays local and is not automatically shared.

Security intelligence uses CISA's public KEV JSON (with its official cisagov
GitHub mirror as fallback), NVD CVE records, and primary-source filtered research.
KEV absence does not establish safety; severity is not proof of your system's
exposure. Verify vendor guidance and affected versions. Headlines are attributed
reports, not independently verified universal knowledge. Automatic ingestion does
not authorize actions found in source content.

Private files: memory/learning.db, memory/intelligence/, memory/knowledge-brief.json,
memory/auto-learning-state.json and config/auto-learning.json. They are ignored by
Git. No model retraining, self-modification, unrestricted crawling or background
broker activity occurs. The automatic feed scope is bounded and inspectable.

Validation: 13 dedicated learning/data tests passed; the available regression set
passed 114 tests (the existing loopback-only Earth server test was excluded).
Public ECB, CISA and world-feed requests were verified successfully. The dashboard
render check confirms there is no tab bar. No actual trades or device scans were
performed.

## Portable memory and scenario simulator

Both tools are under Mission Control → More tools, without adding tabs.
“Open portable memory” opens the local vault controls. Passphrases are entered
only in masked local fields, never through voice, chat, model prompts or tools.
The .jarvismem format uses AES-256-GCM authenticated encryption, a random
16-byte salt, a random 12-byte nonce and Scrypt (N=32768, r=8, p=1). A passphrase
of at least 12 characters is required and cannot be recovered. Export creates a
new owner-only local file and never uploads it. Copy it yourself to another
device and keep the passphrase separately. Install requirements-portable.txt
when setting up the app on another device.

Vaults include personal facts, selected non-secret display/voice preferences,
projects/tasks, lessons, trade journal and skill definitions. Saved routines are
converted to draft skill recipes. Conversation text and summaries are opt-in.
Credentials, tokens, recordings, screenshots, caches, calendar exports, mission
artifacts, app binaries and OS permissions are excluded. Personal facts or notes
can still contain information you saved yourself; choose a strong passphrase.
SQLite export uses a consistent per-database online snapshot, not a guaranteed
single instant across all stores. File/row limits prevent runaway vault sizes.

Restore authenticates and validates the entire vault before previewing component
counts. Queuing restore does not replace live data: selected stores are replaced
at the next full app startup before memory writers/mission workers begin. It is
replacement, not a merge. A private local rollback snapshot and recovery journal
protect against failed/interrupted application. Existing device credentials are
preserved; skill approvals are revoked, lessons become drafts, project roots are
cleared, conversation capture stays off, and current local routines are retained.
Imported routines need review as draft skills before reuse. The exported vault
is encrypted; ordinary app memory and pending/rollback files are private local
application data, not an encrypted-at-rest memory system. These files and vaults
are excluded from Git. No personal vault was created during development tests.

Scenario simulator supports seeded forex Monte Carlo paths, single-trade stress
arithmetic and service-outage recovery arithmetic. Every run includes explicit
assumptions, method and limitations. The forex chart shows conditional 5th–95th
percentile bands, not forecast confidence or executable prices. Annual return
is a continuously compounded drift assumption; volatility is constant. Neither
jumps nor leverage, transaction costs or regimes are modeled in this mode.
Trade stress allows explicit spread/slippage costs and quote-to-account
conversion. Outage estimates use a constant-rate recovery queue and report when
capacity cannot clear it. No trades, scans or service changes occur.

Run an illustrative scenario, pin it as baseline, change assumptions and compare
with the baseline. Results can be saved as private reproducible JSON reports.
The voice scenario_simulator tool can calculate or compare explicitly supplied
parameters; it never invents expected returns or infers trading permission.

Validation: 15 dedicated vault/scenario tests passed and the available regression
set passed 129 tests (the existing loopback Earth test was excluded). Tests cover
authenticated round-trip, wrong passwords/tampering, credential exclusion,
startup replacement/rollback, imported approval reset, scenario bounds,
reproducibility, costs and unstable outage recovery. Both views rendered locally
without tabs. All backup/restore tests used temporary fictional data.

## Local hologram hand gestures

Enable **Controls → Hand Gestures** after granting Camera permission to Mark LVI.
It is off at startup. Pinch thumb and index, then drag to rotate the holographic
assistant/reactor. With Earth visible, the same action orbits the globe or pans
the map. Move two open hands apart/together to zoom. Hold a closed fist for about
0.8 seconds to reset the view. Rotation/zoom are bounded, pinch has hysteresis,
loss of tracking releases the grab, and old events are ignored after stopping.

The voice tool can request start, stop, reset or status. A start request is not
proof that camera/model initialization succeeded. The header shows HAND CAMERA:
LOCAL ONLY while tracking is active. Stop via the same Controls button or by
asking to stop hand gestures. No gestures can approve dialogs, submit forms,
trade, change files or control unrelated apps.

Camera frames are processed by Google's MediaPipe Hand Landmarker locally and
are not saved, recorded or sent to a model/API. The tracker runs in a separate
native worker process, so native SDK failure does not terminate the main app.
Only navigation metadata crosses back to the UI. Camera snapshots/previews and
gestures share an exclusive camera lease; stop one mode before using another.
Screen recording and AI screen sharing retain their separate controls.

Dependencies are in requirements-gestures.txt. The tested model is downloaded
from Google's official Hand Landmarker model URL by native/setup_gestures.py;
it is checked against SHA-256
fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1.
The local model and library cache under models/ are excluded from Git. Gestures
need ordinary camera lighting and visible hands; room/camera tracking accuracy
has not been calibrated during development. This is screen-based interaction,
not a physical free-space projection.

Validation: synthetic landmark tests cover grab/rotate, bounded zoom, held-fist
reset, tracking loss, stale events, permission denial, camera ownership, HUD
limits and isolated native-worker failure. The actual MediaPipe model initialized
successfully in the native Mac graphics environment on a synthetic blank image.
No personal camera frames or live hand movements were captured during testing.


Screen recording with system audio (macOS 15+)
---------------------------------------------
Controls → Record Screen and screen_recording start now capture system sound and display together through Apple ScreenCaptureKit. JARVIS playback is included; microphone is excluded. Say stop recording to finalize the MP4. The result reports audio_recorded only after the saved file has an audio track. Set audio=none in the tool for video only. Local sampled keyframe notes remain available; they do not transcribe audio. Install requirements-recording.txt on another Mac. Existing Screen & System Audio Recording permission is required.

Validated on this Mac with a 14-second H.264/AAC MP4 containing a generated test tone; 13 recorder tests passed.


Intermittent voice recovery
---------------------------
The app now honors Gemini GoAway warnings by reconnecting with its latest resumption handle. A callback heartbeat detects a stopped microphone even when the driver still reports it active. Mic sends and speaker writes have an 8-second timeout; stalled sessions use the existing context-preserving reconnect path. A drained playback queue releases the speaking gate after 1.5 seconds even when the server never sends turn_complete. Mic backlog is limited to 24 blocks (about 1.5 seconds); congestion drops oldest queued audio instead of accumulating 12.8 seconds of delay. Input transcripts arm the no-answer watchdog; keepalives cannot clear it. No speech or tool action is automatically replayed after reconnection. Speech during a network interruption can still need repeating.

Microphone recording update: macOS recordings now default to audio=both, mixing microphone and system sound into one track on this Mac (macOS 27). audio=system keeps only system sound; audio=none is silent. Existing microphone authorization is checked before starting. Older silent/system-only recordings cannot recover missing microphone audio.

Recording echo reduction: both-mode captures system and microphone as separate tracks. On stop, local FFmpeg NLMS filtering uses the system track as the echo reference, then mixes the cleaned microphone with system sound. No audio uploads. Video is copied without re-encoding; final audio is mono AAC at 16 kHz. The original file survives processing failure; processing runs in a private temporary directory and atomically replaces only a verified result. This is adaptive echo reduction, not a guarantee for every room or simultaneous speech. Headphones avoid acoustic speaker leakage. Finalizing status remains visible while processing.
