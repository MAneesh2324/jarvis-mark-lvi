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
