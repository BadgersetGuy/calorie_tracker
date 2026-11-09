# Validation record

9 November 2026, against public repository base `7ea45b8`.

- `python -m unittest discover -s tests -q`: 26 tests passed, temporary SQLite database.
- `gradlew assembleDebug`: native APK compiled and packaged successfully.
- `gradlew lintDebug`: 0 errors; dependency-update and KTX style warnings remain.
- Android SDK `apksigner verify --verbose`: APK signature verified (v2 scheme).
- APK metadata: `com.badgerset.meals`, version `2.0.0`, minimum Android API 26,
  target API 35. Debug signing is for testing, not a Play Store release.

Tests include clarification context, stale draft revisions, replacing a saved meal,
rejecting edits to a meal changed on another device, save/copy retry idempotency,
profile-scoped searchable/paginated history, grams/percentage copying for both profiles,
legacy meals with no ingredient data, authentication, invalid inputs, local-day filtering,
photo normalization, deterministic scoring, and the mocked provider request contract.

Not validated here: camera/gallery behaviour on a real device, visual/screen-reader
usability on hardware, live OpenAI calls, comparative food recognition accuracy, live
Fly database compatibility, deployment, or a GitHub PR. No production records were
read or changed. The public page and its frontend code were inspected.

The newer app.py and index.html supplied by the user are integrated. Additional tests
verify existing target interoperability, unchanged historical scores when copying or
reanalysing, legacy deletion metadata cleanup, and startup against independently built
old/new schemas. The explicit older-schema upgrade adds nullable columns idempotently.
A restored copy of the actual Fly database has not been tested.
