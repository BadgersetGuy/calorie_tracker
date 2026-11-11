# Validation record

Updated 11 November 2026, against public repository base `7ea45b8`.

- `python -m unittest discover -s tests -q`: 91 tests passed, temporary SQLite database. Additional coverage includes backdated eating-day totals, unchanged fingerprints across chunked photo hashing, full 30-meal legacy pages with bounded previews/only one original loaded, and unreadable legacy photo handling.
- `gradlew assembleDebug`: native APK compiled and packaged successfully.
- `gradlew lintDebug`: 0 errors; dependency-update and KTX style warnings remain.
- Android SDK `apksigner verify --verbose`: APK signature verified (v2 scheme).
- APK metadata: `com.badgerset.meals`, version `2.0.2`, minimum Android API 26,
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


11 November History repair: worker logs contain out-of-memory/SIGKILL events on the
256-MiB server. Full older-Android pages now serialize one stored original at a time,
return display previews bounded to 640 pixels/48 KiB, and preserve stored originals.
Compact queries also defer the trailing user_id column to avoid old-photo overflow-page
reads. Fingerprints remain byte-compatible after switching to chunked hashing.
Backdated eating time and local-day nutrition totals pass a dedicated regression test.
All 91 backend tests pass; official MCP checks pass locally after these changes.

Deployment is NOT yet complete. Attempts 42979643281 and 42981059808 stopped safely
before rollout because the volume cannot retain the new verified backup plus reserve.
Read-only diagnostic run 42981569510 reports a 1-GB volume, about 245 MB free,
243 MB database and 474 MB backups (three files). Lossless compression/consolidation
preserves every distinct restore point and dated manifest. The existing production
revision remains 767cf0639003d9c22c6e2d870829f2c61cae5089.
A tested, opt-in workflow input can extend ONLY the same 1-GB volume to 2 GB and
then continue backup/deployment checks. It defaults off and awaits owner approval;
Fly's published volume rate is $0.15/GB/month. No storage extension was performed.
Full legacy/summary History checks for every profile remain required after rollout.
