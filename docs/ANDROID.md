# Everyday Meals for Android

Native Kotlin / Jetpack Compose app, Android 8.0 or newer. There is no WebView.
The Flask server retains the database, photos, analysis credentials, and household data.

## What is implemented

- Today, Add meal, History and Ideas; household profiles and daily targets.
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
gunicorn --bind 0.0.0.0:8080 --workers 2 --timeout 150 app:app
```

`GET /health` should return `{"api_version":2,"status":"ok"}`. New data endpoints are
under `/api/v2`. Android access fails closed until `MOBILE_API_TOKEN` is configured.
Once configured, the legacy data routes also require the same token. The old web UI
does not supply that token and will no longer load household data.

### Existing production data

The newer `app.py` and `index.html` supplied in chat have now been integrated. The
backend retains the supplied `/data/meals.db` default, existing User target columns,
nullable Meal `psoriasis_score`, legacy target/deletion/history routes, and current web
template. Android reads and writes the same User target columns as the legacy API;
there is no second source of target settings.

Additional `mobile_*` tables store analysis drafts, meal details, cached analyses,
confirmed meal timing, suggestion batches and per-profile suggestion feedback.
Startup creates missing tables but does not alter existing columns or rewrite old rows.
Historical 1–10 psoriasis scores remain in `meal.psoriasis_score`, are returned separately
as `legacy_psoriasis_score`, and are copied unchanged with a meal. New 0–100 dietary-pattern
scores live in versioned analysis metadata. Reanalysis preserves the historical number as
an original record; it is not converted to, or mixed with, the new rubric.

Compatibility tests construct databases independently from both the older repository
schema and the supplied updated schema. They verify existing IDs, dates, photos, totals,
targets and scores survive startup. They do not substitute for checking the real database.

Before rollout:

1. Take a verified backup of the existing database and Fly persistent volume.
2. Test this checkout against a restored copy using its existing DATABASE_URL. Preserve
   the `/data` mount and database URI rather than creating a new empty database.
3. If that database predates the supplied source's target/score columns, run the explicit
   additive upgrade after backing it up:

   ```
   flask --app app upgrade-legacy-schema
   ```

   This only adds missing nullable target/score columns. It is safe to run again and does
   not overwrite existing values. Databases already matching the supplied app need no
   column changes. No legacy scores are recalculated automatically.
4. Verify profiles, target values, meal counts/dates/photos, and copying an older meal.
5. Deploy the backend with the existing Fly port configuration (the supplied app defaults
   to port 8080), configure secrets, and connect both Android phones.

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
pip install -r requirements-dev.txt
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


## Discipline and meal ideas

Discipline is a separate personal timing goal, not an inflammation/medical score.
Through 18:00 local eating time it is 10. After that, subtract one point for each
started 30-minute interval, to a floor of 0: 19:00=8, 20:00=6, 23:00=0. The next
calendar day starts a new goal day. This rule is versioned as `discipline-18h-1.0`.

Use the eating date/time controls when logging later. Confirmed scores retain the
original local timestamp, timezone and version, independently of analysis time.
Reanalysis preserves the original timezone even if the phone has travelled. Meal
copies use the new eating time. For old records with no confirmed local time, the
app marks the score as inferred, using HOUSEHOLD_TIMEZONE (default Europe/Bucharest).
Daily discipline is the lowest logged meal score, so early meals do not dilute a
late meal penalty; an empty day has no score. It is never combined with the food composition score.

Ideas use an initial catalog of 18 Mediterranean-style dishes and ingredient lists.
Ranking reads up to 120 recent meals for that profile, including legacy descriptions
and structured ingredient names (with common Romanian aliases). Ingredients logged
at least twice are familiarity signals, not proof of enjoyment. New ingredients get
a novelty bonus, ingredients in the last seven meals are down-ranked, and the last
two suggestion batches are excluded. The batch favours different food groups.

Like adds a preference signal; Skip excludes an idea until that profile resets
likes/skips. Avoid ingredients are applied before ranking, and persisted in the
latest batch so both phones can see them. These are text/tag filters, not a clinical
allergen certification; check every ingredient list. Constraints are never relaxed
silently if the catalog is exhausted. Starting an idea only opens an unsaved entry;
actual portions still need to be provided/analyzed. No suggestion creates a meal
log automatically. This feature works without a model API call.

Body-weight history is available through the top-bar scale icon; log a new kg value,
tap an entry to correct it, or delete it. It is shared with the chat API.
See [CHAT_API.md](CHAT_API.md) for API reporting, chat logging and integration setup.
