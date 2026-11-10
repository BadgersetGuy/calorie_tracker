# Validation record

Updated 10 November 2026, against public repository base `7ea45b8`.

- `python -m unittest discover -s tests -q`: 74 tests passed, temporary SQLite database, including private backup and deployment configuration guards, detached private checks, separate-token requirements, item editing, removal and reuse without another model call.
- `gradlew assembleDebug`: native APK compiled and packaged successfully.
- `gradlew lintDebug`: 0 errors; dependency-update and KTX style warnings remain.
- Android SDK `apksigner verify --verbose`: APK signature verified (v2 scheme).
- APK metadata: `com.badgerset.meals`, version `2.0.1`, minimum Android API 26,
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
No live Custom GPT or MCP handoff has been run; the Codex skill is prepared, not installed.


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
GitHub Actions deployment credentials now work. The existing Machine and persistent
volume were verified, and private SQLite backups passed integrity checks. The live
vision-access probe now succeeds for gpt-6.1-sol after API credit was added. Deployment
is being retried after fixing Fly configuration export to an existing private file.
