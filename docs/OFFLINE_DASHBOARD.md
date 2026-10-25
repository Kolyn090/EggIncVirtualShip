# One active mission plan, offline

The PWA lives in `pwa/`. It is a static app; it needs no API, user account,
optimizer process, or plan-upload server. The optimizer, dashboard generator,
and mission schedules are unchanged.

## Open and install

From the project root:

```sh
python3 -m http.server 8000 --bind 127.0.0.1 --directory pwa
```

Open <http://localhost:8000/> on that computer. Use the browser's **Install app**
action if desired. For another device, serve the same `pwa/` directory on an
HTTPS static host and use its install/Add to Home Screen action. Opening
`index.html` directly with `file://` does not provide service-worker offline
installation. Production usage does not need Node or Python; they are only
build/development tools.

Wait for **Ready offline** on the first visit. The installed app can then
restart without the server or network. Plans remain private on the device:
choosing an HTML file reads its embedded mission data locally, never uploads it,
and does not execute its scripts or load its images/links.

## GitHub Pages deployment

The production URL is <https://kolyn090.github.io/EggIncVirtualShip/> once the
first deployment succeeds. In the repository's **Settings → Pages**, select
**GitHub Actions** under **Build and deployment → Source** (requires repository
administration access). Then push a relevant change to `main`, or open
**Actions → Deploy offline dashboard to GitHub Pages → Run workflow**, choosing
`main`. Check the workflow's deployment job/environment link for the live URL.
If configuration fails because Pages is not enabled, select that source first
and rerun the workflow. Repository/organization policy must permit Pages and
the `github-pages` deployment environment.

The workflow in `.github/workflows/deploy-pwa.yml` runs on changes to `pwa/**`,
the dashboard bundler/source template, or the workflow itself. It regenerates
the trusted template and content-based service-worker cache version, then
uploads **only the contents of `pwa/`** as the Pages website root. It does not
publish repository files, results, inventory, or imported plans. Python runs
only during the Actions build; production is entirely static HTTPS with no
Node/Python server or API. Manual workflow dispatch is also available.

Assets, manifest URLs and the service-worker registration use relative paths,
so `/EggIncVirtualShip/` is the app root and service-worker scope. Keep the
trailing slash in bookmarks. Wait for **Ready offline** on the first online
visit before relying on offline reopening. Deployments refresh the app shell
without deleting the active plan or checklist in IndexedDB. Localhost and
GitHub Pages are different origins: existing local progress is not migrated;
use the original HTML and an explicit progress backup when moving to Pages.

To run the browser suite against the same repository subpath locally:

```sh
PWA_TEST_SUBPATH=1 npm run test:pwa
```

This stages the app at `/EggIncVirtualShip/` on a local static server and tests
imports, autosave, full offline browser restart, confirmed closure, progress
backups and installability there as well as at the default `/` test root.

## Workflow

1. With no active plan, **Import Plan** is the only plan-entry screen. Choose an
   optimizer-generated `plan.html` or another named HTML dashboard export.
2. The existing dashboard, launch cards, filters, balance tables, completion
   marks and next-unfinished-mission scrolling open with that exact mission data.
3. Checking or unchecking a mission saves automatically. **Saved on this device**
   means the storage transaction committed. Reopening the app, including offline,
   restores that plan and its checklist. A failed save is shown with a retry
   action; it is not silently reported as saved.
4. While active, the app hides/disables HTML-plan import. Reloading, another
   window, a queued file-selection event, or a direct import attempt cannot
   replace the active plan.
5. Use **Close Current Plan** in the app header. The confirmation explains that
   the plan and its entire checklist progress will be deleted from local app
   storage. **Keep current plan** or Escape leaves them intact.
6. Only **Close and delete** removes the active record and returns to Import
   Plan. A new import starts with an empty checklist, even when importing the
   same HTML again. There are no saved-plan lists, switching, or automatic
   progress migration.

The original HTML file and any downloaded JSON backups are external files;
closing a plan does not delete those files. It deletes the app's active mission
data and progress together. Keep the original HTML if you want to reimport it.

## Completion highlights and compact checklist

Completed missions stay green except for the most recently completed mission,
which is yellow. Each completed card shows its completion time: **Just now**,
**3 min ago**, **Today, 8:42 PM**, **Yesterday, 8:42 PM**, or a dated time for
older entries. Exact times are available in the timestamp tooltip. Relative
labels refresh every 15 seconds while open and when the dashboard regains
focus. Dates and times use the device's local timezone.

Check/uncheck updates save completion timestamps (milliseconds since the Unix
epoch) alongside checklist progress in the same atomic IndexedDB record. A
failed save/retry keeps the original click time. Completing another mission
moves the yellow highlight; unchecking it falls back to the latest remaining
completion. The highlight and timestamps survive offline browser restarts.

Existing active plans and checkmarks remain intact without a database reset.
Older completions have no recoverable timestamp and show **Completion time
unavailable**. Until a timestamped completion exists, the last completed entry
in the saved progress order is highlighted as a fallback; this does not infer
an actual completion time. Once new completions are recorded, their timestamps
determine the highlight. Equal timestamps use saved completion order to break
ties. Unchecking removes that entry's timestamp; rechecking records a new one.

At widths up to 650px, the checklist uses smaller padding, card widths and lane
spacing while retaining ship, target, launch/finish times and status. The
390px-wide test fixture's lane height drops from 208.5px to about 155px (about 35%
more lanes in the same vertical space). Cards remain at least 108px tall and
schedule-table check buttons retain 44px touch targets. Longer names or visible
completion timestamps can increase card height. Desktop card dimensions and
the checklist ordering are unchanged.

## Progress backups

The dashboard's existing **Export progress** and **Import progress** buttons
remain available while a plan is active. They are checklist-backup operations,
not plan imports. Existing `reggference-progress-v1` JSON files remain compatible
with the same target and schedule. Another plan's backup is rejected; explicit
backup import is the only way to restore a previous checklist after closing
and reimporting a plan. No standalone dashboard's old browser progress is
picked up automatically.

New v1 backups include an optional `completionTimes` map keyed by mission key,
so explicit backup restore also restores known completion times. Older backups
without this field still work: known times for checks retained in the active
plan are preserved; newly restored checks have unknown times rather than the
time of the import. Invalid timestamp fields are rejected before progress is
changed. Older standalone dashboards can read new backups' completion lists
but ignore the optional timestamp field.

The active record belongs to this browser profile/app origin. Normal browser
restarts retain it. Clearing site data, private-session termination, or browser/
OS storage eviction can remove local data; external progress backups and the
original HTML remain the recovery mechanism. The browser test covers a full
normal-browser shutdown/restart with network access disabled. Physical iOS
installation has not been tested; the mobile layout is tested in Chromium.

## Architecture

- `store.mjs` keeps **one** IndexedDB key, `active`, containing mission data,
  filename, unique active-session ID, progress, completion timestamps and revision. There is no plan
  collection or history. Import uses a serialized read/write transaction and
  `add`, so simultaneous imports cannot overwrite each other. Closure deletes
  that single record atomically. Late updates/deletions must match its ID and
  cannot resurrect a closed plan or alter a later one.
- `plan.mjs` reads the exported JSON directly from the HTML string without
  putting imported markup into a DOM. It validates the data and calculates
  the existing dashboard's exact progress-backup identity.
- `dashboard-template.mjs` is the unchanged trusted dashboard template bundled
  from `build_plan_dashboard.py`. Only this code runs in an opaque-origin
  sandboxed frame. The small storage bridge directs checklist writes to the
  parent record and validates their source, session token, plan ID and keys.
  The frame has no network access or access to parent storage.
- Progress writes apply per-mission changes in transactions, preserving updates
  from other windows showing the same active plan. Broadcast notifications
  synchronize views; notification storage contains no plan/progress. No progress
  is ever migrated to another plan. A closed frame's browsing context is
  discarded so iframe Back history cannot become a plan switcher.
- `checklist.mjs` adds the PWA-only completion highlight, live timestamp labels,
  timestamp-aware compatible backups and compact mobile styles around the
  unchanged trusted template. The optimizer, source dashboard generator and
  mission scheduling logic are untouched.
- The service worker caches only app assets. An asset update does not delete or
  migrate the active record. All data is local; no imported files are requested
  by or posted to a server.

## Build and test

The trusted template and service-worker asset version are committed, so a
normal static deployment needs no build. After changing the existing dashboard
or PWA assets, regenerate the template/cache version:

```sh
npm ci
npm run build:pwa
npm test
npm run test:pwa
.venv/bin/python -m unittest discover -s tests -v
```

Browser tests use `/usr/bin/chromium` when available, or the Playwright browser:

```sh
npx playwright install chromium
# Optional system/browser override:
PLAYWRIGHT_CHROMIUM_EXECUTABLE=/path/to/chromium npm run test:pwa
```

Eleven browser tests cover local import, auto-saving check and uncheck, normal
reload, a full persistent-profile browser restart while offline, offline close
and reimport, blocked replacement, cancellation/confirmed deletion, stale
writes, concurrent windows, explicit progress backups, untrusted HTML,
mobile controls, storage-failure recovery and Chromium installability. Added
coverage checks persistent timestamps and yellow highlights after an offline
restart, live relative labels, uncheck fallback, legacy records/backups,
timestamp backup round trips, cross-window timestamp-only updates, invalid
dates, original click times after save retries, mobile density and unchanged
desktop dimensions.
Five Node tests cover parsing, malformed input, data preservation, backup-key
compatibility and script escaping. A Python parity test ensures the offline
bundle exactly matches the existing dashboard design and behavior.

Verified commands for this implementation:

- `npm run build:pwa`
- `npm run test:pwa` — 11 real Chromium browser tests passed.
- `npm test` — 14 Node tests passed, including the existing source-data tests.
- `.venv/bin/python -m unittest discover -s tests -v` — 66 tests passed.

A real 360-mission HTML export was also imported on a 390×844 viewport. Its
stored mission data matched the source exactly; check/save/reload and timeline
scrolling passed. The existing runner test now uses an explicit 40-launch test
fixture rather than depending on the user's configurable 360-launch default.
The actual runner configuration and optimizer sources were not changed.
