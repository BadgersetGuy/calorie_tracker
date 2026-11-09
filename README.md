# Everyday Meals

A native Android meal diary with a Flask backend. Photograph a meal or describe it in
text, answer focused clarification questions, review the estimate, and save. Correct an
analysis with more detail. Reuse meals from history for yourself or another household
profile with a percentage or gram adjustment.

The Kotlin / Jetpack Compose app lives in `android/`. The existing web interface remains
in `templates/` for reference; it is not used by the Android app.

## Start here

- [Android build, connection, server configuration and rollout](docs/ANDROID.md)
- [Score definition, evidence and limitations](docs/SCORING.md)
- `.env.example` lists server settings without credentials.

The provided source is older than the live Fly app. Reconcile the deployed source and
test on a database backup before deploying. No production data has been migrated.

## Local backend

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
# Configure a private .env from .env.example, including MOBILE_API_TOKEN.
.venv/bin/gunicorn --bind 0.0.0.0:5000 --timeout 150 app:app
```

Use HTTPS when connecting Android. Never put the OpenAI key in the APK.

```sh
.venv/bin/python -m unittest discover -s tests -v
cd android
./gradlew assembleDebug lintDebug
```

The dietary-pattern score uses a fixed, versioned formula. It is an app heuristic, not a
validated clinical psoriasis or inflammation score. Model-estimated nutrition and portions
remain estimates; copy/portion calculations use deterministic arithmetic.
