# Everyday Meals for Android

Native Kotlin / Jetpack Compose app, Android 8.0 or newer. There is no WebView.
The Flask server retains the database, photos, analysis credentials, and household data.

## What is implemented

- Today, Add meal and History; household profiles and daily targets.
- Search all past meals, page through older results, or browse a specific date.
- Native camera intent and photo picker, optional photo, free-text meal/portion input.
- Persisted analysis drafts, targeted clarification questions and text corrections.
- Review estimates and assumptions, reanalyse before saving, or correct an existing meal
  without replacing its ID or original date. Unchanged meals remain saved until confirmation.
- Reuse any historical meal for the same person or another profile, on a chosen date.
  Scale by percentage or grams. Copying uses arithmetic and never calls the model.
- Previous meals without ingredient analysis can still be copied. No new score is fabricated.
- Fixed, explained dietary-pattern formula, ingredient breakdown and source notes.
- Household bearer authentication, Android keystore encryption for the token, HTTPS only.
- The current local entry and server draft ID survive activity/process recreation. Camera
  capture uses app cache, so an unsent photo can be lost if Android clears that cache.

## Server setup

Install `requirements.txt` in a virtual environment. Configure these runtime secrets/settings
through your hosting provider, never in the Android project or a committed file:

```
OPENAI_API_KEY=<server-only OpenAI key>
MOBILE_API_TOKEN=<a random household token of at least 32 characters>
SECRET_KEY=<a separate random Flask secret>
DATABASE_URL=<the EXISTING production database URL>
MEAL_ANALYSIS_MODEL=gpt-6.1-sol
```

Generate the household token privately with a password manager. Both phones use the same
household token and server address, then select their own profiles. It grants access to
all household profiles and photos; it is not a multi-household authentication system.
Tokens are revocable by changing the server environment value.

Run with a timeout that accommodates analysis:

```
gunicorn --bind 0.0.0.0:5000 --workers 2 --timeout 150 app:app
```

`GET /health` should return `{"api_version":2,"status":"ok"}`. New data endpoints are
under `/api/v2`. Android access fails closed until `MOBILE_API_TOKEN` is configured.
Once configured, the legacy data routes also require the same token. The old web UI
does not supply that token and will no longer load household data.

### Existing production data: reconcile before deployment

The supplied repository at commit `7ea45b8` is **older than the public Fly application**:
the public interface has psoriasis scores and user-target routes absent from this source.
Do not deploy this checkout over production without locating those uncommitted/deployed
changes and inspecting a backup of the real schema.

This implementation creates four new `mobile_*` tables and reuses the existing `user`
and `meal` tables. It does not issue `ALTER`, `DROP`, or data migrations on startup.
That preserves old rows on the repository's schema, but is not proof of compatibility
with unknown production columns, non-null constraints, timestamps, or extra functionality.
The mobile targets table is separate; existing production target settings are not imported
automatically. Existing production psoriasis scores remain in their original columns and
are not reinterpreted as the new score.

Before rollout:

1. Obtain the deployed source and take a verified backup of the real database and volumes.
2. Inspect its schema and port the new modules into that source. Reconcile any extra required
   meal columns and import target settings into `mobile_profile` explicitly.
3. Test against a restored database copy. Check user IDs, meal counts, dates, nutrition,
   photos, and a legacy meal copy; inspect historical scores without overwriting them.
4. Preserve the existing database URI and Fly persistent volume mount. The repository's
   default relative SQLite file is not a substitute for the real production data location.
5. Deploy the backend, configure secrets in hosting settings, then connect Android.

No production database, deployment, or repository remote has been modified by this work.

## Build and install

Use Android Studio with JDK 17+ and SDK 35, or the checked-in Gradle wrapper:

```
cd android
./gradlew assembleDebug
```

Install `app/build/outputs/apk/debug/app-debug.apk` on a test Android phone. In the first
screen enter the HTTPS server origin and household token. The existing deployed web
backend does not contain `/api/v2` until the updated backend is deployed.

The debug APK is for evaluation. For distribution, create a private release signing key
in Android Studio and retain it for updates. Do not commit it. A Play Store release also
requires listing/privacy work and a signed App Bundle; neither is claimed here.

## Testing

```
python -m unittest discover -s tests -v
cd android
./gradlew assembleDebug lintDebug
```

Backend tests use a temporary database and mocked model responses: clarification history,
save idempotency, stale revisions, edit-in-place, auth on legacy/new endpoints, photo
normalization, local-day filtering, cached results, and copying old/new meals by grams
or percentage. These do not demonstrate food recognition accuracy.

Before real use, test on an Android device: camera cancellation/retry, gallery selection,
rotation and process recreation, offline entry/retry, text-only cappuccino, an ambiguous
photo, clarification and correction, household switching, old meal reuse, small screen /
large font / screen reader, and timezone boundary meals.

## Analysis limitations and model choice

The model defaults to `gpt-6.1-sol`, configurable on the server. Its image input and
structured output support were checked in the official model catalog on 9 November 2026.
No live analysis or comparison against Astra was run because no OpenAI key is configured
in this workspace. Do not describe this as benchmark-proven food recognition.

The model proposes ingredients, edible gram estimates, food groups and per-100g nutrition.
Python validates ranges, macro/energy plausibility and any explicit total weight, then
calculates totals and the score. Nutrition is a generic composition estimate unless the
user supplies label values; no USDA or branded-food lookup is implemented. Identical
inputs under the same model/prompt/rubric version reuse a persisted result. A changed
clarification can still alter estimates; deterministic arithmetic does not make vision
or nutrition extraction exact.

References, interpretation and the exact score definition: [SCORING.md](SCORING.md).
