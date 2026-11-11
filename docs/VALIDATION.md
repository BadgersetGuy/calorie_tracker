# Validation record

Updated 11 November 2026, against public repository base `7ea45b8`.

- `python -m unittest discover -s tests -q`: 98 tests passed, temporary SQLite database. Additional coverage includes backdated eating-day totals, unchanged fingerprints across chunked photo hashing, full 30-meal legacy pages with bounded previews/only one original loaded, and unreadable legacy photo handling.
- `gradlew assembleDebug`: native APK compiled and packaged successfully.
- `gradlew lintDebug`: 0 errors; dependency-update and KTX style warnings remain.
- Android SDK `apksigner verify --verbose`: APK signature verified (v2 scheme).
- APK metadata: `com.badgerset.meals`, version `2.0.3`, minimum Android API 26,
  target API 35. Debug signing is for testing, not a Play Store release.

Tests include clarification context, stale draft revisions, replacing a saved meal,
rejecting edits to a meal changed on another device, save/copy retry idempotency,
profile-scoped searchable/paginated history, grams/percentage copying for both profiles,
legacy meals with no ingredient data, authentication, invalid inputs, local-day filtering,
photo normalization, deterministic scoring, and the mocked provider request contract.

Not validated here: camera/gallery behaviour on a real device, visual/screen-reader
usability on hardware, comparative food recognition accuracy, or a live ChatGPT handoff.
Production deployment checks inspect only database integrity/schema and row counts;
no individual household records or credentials are published in logs. The GitHub PR
and public APK release exist. See the rollout notes below for live checks.

The newer app.py and index.html supplied by the user are integrated. Additional tests
verify existing target interoperability, unchanged historical scores when copying or
reanalysing, legacy deletion metadata cleanup, and startup against independently built
old/new schemas. The explicit older-schema upgrade adds nullable columns idempotently.
A restored copy of the actual Fly database has not been tested.

Additional checks cover direct chat-analysis import, deterministic score recalculation,
manual nutrition, multipart/photo references, attachment restrictions, authentication,
revision conflicts, body-weight CRUD, daily summary coverage and profile isolation.
The generated OpenAPI contract validates and covers every mobile API operation.
The official MCP client has verified live transport, tool discovery and an authenticated
read-only call. The plugin is packaged; installation/authentication in the user's actual
ChatGPT account and the Custom GPT attachment handoff remain unverified.


Compression checks cover detailed/high-resolution camera photos, the 1280-pixel/200-KiB
limit, EXIF removal/orientation, byte-identical repeated normalization, legacy ingest,
compression on meal copy without rewriting the source, and dry-run/apply maintenance
without nutrition/score changes. Android uses software-decoded bitmaps for JPEG encoding.


Pre-deployment dependency update (10 November 2026): Flask 3.1.3, Werkzeug 3.1.9,
Pillow 13.0.0, requests 2.34.2, python-dotenv 1.2.4 and Gunicorn 26.2.0. All 65 tests
pass with these versions. pip-audit reports no known vulnerabilities in the updated
local Python environment; this is not an OS/container-image vulnerability assessment.
Gunicorn HTTP smoke checks on a temporary database pass for health, rejected unauthenticated
access, and authenticated profile access. The container build upgrades pip to 26.3.
Production deployment succeeded on 10 November 2026 from commit
`47e251db05d3e41789f91a7a867ae5d5d72a1e44`:
https://github.com/BadgersetGuy/calorie_tracker/actions/runs/42849314508 .
The existing Machine/data volume, private backup integrity, current SQLite integrity,
preserved meal/profile counts, authenticated profiles and a real structured text-meal
analysis passed. The selected model is gpt-6.1-sol; its synthetic-image access probe
also passed. No test meal was inserted into household history. Public health confirms
the deployed revision, and private/legacy data routes reject unauthenticated requests.
The live OpenAPI contract includes all 30 operations, including ingredient editing.
These checks do not establish photo-recognition accuracy or real-device UX quality.
The household runtime token is separate from the Fly deployment credential.

The performance/MCP update is deployed from commit
`767cf0639003d9c22c6e2d870829f2c61cae5089`:
https://github.com/BadgersetGuy/calorie_tracker/actions/runs/42866033198 .
It passed backup/database/volume/record checks, structured analysis, an indexed history
query-plan check and live official MCP 2.3.0 client discovery of all 30 tools. The
always-warm single-Machine policy was independently verified:
https://github.com/BadgersetGuy/calorie_tracker/actions/runs/42865450876 .

Read-only timings on the same three history entries from a GitHub runner:

| Measurement | Result |
| --- | --- |
| History summary before index | 14,360 ms |
| History summary after index | 218 ms |
| Inline-photo list after index | 967 ms |
| Summary / inline-photo response bytes | 2,987 / 657,142 |
| Thumbnail bytes | 4,726 |

These are server/network checks from that runner, not measured Android-device timings.
The Android changes add immediate cached navigation, small lazy photos and background
decoding. The public v2.0.2 APK/ZIP checksum, signature and metadata were verified:
https://github.com/BadgersetGuy/calorie_tracker/releases/tag/android-test-2026-11-10-fast .


11 November repair and charts are deployed from
`dee6f76e854554f28d8b965906556562e12aebd7`:
https://github.com/BadgersetGuy/calorie_tracker/actions/runs/42986149751 .
Health, original volume identity, private backup/current database integrity, preserved
records, authenticated profiles, live structured analysis and official MCP checks pass.
The owner approved extending the existing volume from 1 to 2 GB (about $0.15/month
extra); the same volume remains mounted. No distinct restore point was deleted.

History pages now load one original at a time, return 640-pixel/48-KiB display previews,
and preserve stored originals. Fingerprint hashes remain byte-compatible. Dedicated
tests verify backdated eating-day totals and timing. Calorie-weighted daily/period
score aggregates exclude missing/zero-energy scores and separate historical psoriasis
scales and dietary rubric versions. All 98 backend tests pass locally and in CI:
https://github.com/BadgersetGuy/calorie_tracker/actions/runs/42986155574 .
Native v2.0.3 (code 4) build/lint pass (local lint: 0 errors, 11 warnings).

All-profile live verification passed:
https://github.com/BadgersetGuy/calorie_tracker/actions/runs/42986662399 .
Each of four profiles returned HTTP 200 for compact 30-meal History, older-Android
3/30-meal History and a 30-day weighted-report contract check. Summary responses
ranged 105–2759 ms; full older-Android pages ranged 106–8764 ms. Older photo-heavy
history can still take seconds, especially on an initial read; these runner timings
do not establish Android-device latency. The newer APK uses compact cached lists.
The 30-day reports took 156–226 ms. No diagnostic test meal was saved.

The initial rollout omitted the new summary module; automatic image rollback restored
the previous server without restoring/overwriting data. A packaged-file startup test
now catches missing runtime modules before deployment. Rollout checks now allow normal
Machine stopping/starting transitions, explicitly start replacements when needed, and
verify the exact live revision rather than treating a transient state as a failed boot.

Phone-downloadable v2.0.3 release:
https://github.com/BadgersetGuy/calorie_tracker/releases/tag/android-test-2026-11-11-trends .
The published ZIP was anonymously downloaded, checked for archive corruption, and its
APK matched the published SHA-256. Signature and package/API metadata were verified.
Published signer SHA-256: bd73bcb129cdf52baa8939ce6774ba8ffbe57e923542397ef44381683e20adb6.
It differs from the v2.0.2 evaluation signer: finish pending entries/save the household
token before uninstall/reinstall if Android reports a signature conflict. Server-saved
meals remain. Stable release signing is not configured: GitHub denied permission to
set a signing secret; no key was published. Real-device chart/camera UX remains untested.

A diagnostic run briefly logged Fly account actor metadata (name/email). The run and
its logs were deleted; release diagnostics now whitelist fields and classify startup
errors without raw application logs. No meal contents or access tokens were in that
run. The owner was informed. ChatGPT account connector installation remains pending;
a deployed MCP endpoint/package alone does not connect the account.
