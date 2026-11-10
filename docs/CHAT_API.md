# Android and chat share one REST API

REST is the source of truth. No MCP server is required for the Android app, a private
Custom GPT Action, or a Codex skill that can make HTTP requests. A general ChatGPT plugin
would still need a thin MCP adapter; a skill supplies instructions, not transport or
credentials. No ChatGPT connection, GPT, or MCP server has been created in your account.

Use a separate household token, not the Fly deployment credential. Configure the same
random value (at least 32 characters) as the GitHub repository Actions secret
`MOBILE_API_TOKEN` and in the Android/chat credential settings. The deployment workflow
stages that value as the Fly runtime secret without putting it in command arguments,
public logs, the APK, or the OpenAPI contract.

Ready analyses expose an `ingredients` list with names, grams and nutrient estimates
per 100 g. To change quantities or remove items without another model call, PUT
`/api/v2/analyses/ID/ingredients` with `revision` and `items: [{index: 0, grams: 150}]`.
Indices refer to the current draft list; omitted indices are removed. At least one
item must remain. Totals and the dietary-pattern score are recalculated. New foods
can be introduced through clarification text. For an existing meal, first POST an
analysis with `source_meal_id` and `use_existing_analysis: true`; then review and save
using `replace_meal_id` to update it in place. Older meals without item details need
analysis first.

## Connection options

### Private Custom GPT

1. Deploy the backend and set `MOBILE_API_TOKEN`, `HOUSEHOLD_TIMEZONE` and the existing
   production database configuration. Use HTTPS. Set `PUBLIC_API_URL` if the origin is
   different from the existing Fly address.
2. In the GPT editor, add an Action and import `docs/openapi.json` or the deployed
   `/openapi.json`. Choose API-key authentication with bearer auth and enter the household
   token in the editor's credential settings, not in chat, knowledge files or the schema.
3. Use `GPT_INSTRUCTIONS.md` as the workflow instructions. Keep the GPT private to the
   intended household: its configured token can read/write both profiles.
4. Test profile lookup, a text meal, a photo meal, correction, reuse, a daily summary,
   and body-weight logging. A successful API call—not the model's prose—confirms a save.

The Action schema is OpenAPI 3.1 and includes every `/api/v2` operation. It is generated
from actual Flask routes and validated in tests. Its response descriptions are intentionally
flexible; see the resource definitions below for semantics. Runtime authentication is
required for all household data; only the health check and contract are public.

Photo inputs use `openaiFileIdRefs` as specified by OpenAI: the Actions runtime replaces
the conversation file IDs with objects containing short-lived `download_link` values.
The backend accepts exactly one photo, downloads only HTTPS attachments on the documented
`files.oaiusercontent.com` host, refuses redirects, caps the size and validates/re-encodes
the image. Signed URLs and the diary token are not stored or forwarded to that host.
The real ChatGPT Action handoff is not tested here; use the GPT editor to verify it.

[Configuring GPT Actions](https://help.openai.com/en/articles/9442513-configuring-actions-in-gpts)
and [file-reference format](https://developers.openai.com/api/docs/actions/sending-files).

### Codex skill / other HTTP-capable agent

Install `skills/meal-diary` into the runtime's supported skill location. Configure
`MEAL_API_URL` and the secret `MEAL_API_TOKEN` in that runtime's secret settings. The
bundled standard-library client supports GET/POST/PUT/PATCH/DELETE, real file attachment
encoding and binary downloads. It refuses redirects and never prints the credential.
Installing these files alone does not connect an ordinary ChatGPT conversation.

## Resources

| Resource | Read | Create / edit |
|---|---|---|
| Profiles | `GET /profiles` | `POST /profiles`, `PATCH /profiles/{id}` |
| Targets | Included in profiles and summaries; legacy target route also retained | `PUT /profiles/{id}/targets` |
| Meals | `GET /meals`, `/history`, `/meals/{id}`, `/meals/{id}/photo` | `POST /meals`, `PATCH /meals/{id}`, `DELETE /meals/{id}` |
| Reuse | Retrieve original meal | `POST /meals/{id}/copy` |
| Server analysis | `GET /analyses`, `/analyses/{id}`, `/analyses/{id}/photo` | `POST /analyses`, `POST /analyses/{id}/clarifications`, `POST /analyses/{id}/save` |
| Meal ideas | `GET /suggestions` | `POST /suggestions`, `PUT /suggestions/{recipe_id}/feedback`, `DELETE /suggestions/feedback` |
| Body weight | `GET /weights`, `/weights/{id}` | `POST /weights`, `PUT /weights/{id}`, `DELETE /weights/{id}` |
| Daily/range reports | `GET /summaries` | Calculated from current records |
| Change logs | `GET /logs` | Recorded automatically for meal/profile/body-weight mutations |

All paths above start with `/api/v2`. List/report operations take `user_id`. Resource
IDs remain accessible to the authenticated household, which includes both profiles.
History uses pages of 30 and `offset`; weights, analysis history and logs use `offset`
and `limit` (1–100). The default summary date is the current day in the requested or
household timezone. Use `date` for one day, or `start`/`end` for up to 366 days.

Examples:

```
GET /api/v2/summaries?user_id=7&date=2026-11-09&timezone=Europe/Bucharest
GET /api/v2/summaries?user_id=7&start=2026-11-01&end=2026-11-09&timezone=Europe/Bucharest
GET /api/v2/history?user_id=7&query=salmon&offset=0
GET /api/v2/weights?user_id=7&limit=30&offset=0
GET /api/v2/analyses/DRAFT_UUID?include_context=true
```

Summaries return daily calories/protein/carbs/fat, known fibre and its coverage, timing,
discipline, recorded body weights, and dietary score coverage grouped by version. They
never blend different rubric versions into one score. Historical 1–10 psoriasis values
remain available separately on the meal records. There is no measured inflammation
biomarker in this database. Empty days mean no logged intake, not proven fasting.

Reports omit full meal objects unless `include_meals=true`. Photos are omitted from JSON
by default; request `include_images=true` or use the authenticated photo endpoint. Android
opts in with `X-Meal-Client: android`. This keeps chat responses compact.

Change logs start when this upgraded backend is installed, and include deleted record
snapshots without photo bytes. They are not a retroactive audit of the old application.
Direct analysis corrections retain the previous analysis in the log; deleting a meal
archives its nutrition, analysis, scores and timing before removing the active record.
Existing meals and historical scores are not rewritten by these read operations.

## Two analysis routes

1. **Analysis in chat:** POST `/meals` with `user_id`, UUID `request_key`, offset-aware
   `eaten_at`, IANA `timezone`, and `analysis` matching `MealAnalysis` in the contract.
   Scores/totals supplied by the client are ignored and recomputed from ingredient grams
   and per-100g nutrients. Provenance is marked `client-supplied`; no second model is called.
   Alternatively provide `description`, edible `weight` and explicit `totals` without
   ingredient analysis; this does not fabricate a dietary score.
2. **Server analysis:** POST `/analyses` with text/photo, respond to any clarification
   questions using the returned draft ID and revision, and save once ready. Saving with
   `replace_meal_id` updates that original meal instead of creating another entry.

JSON requests can attach actual base64 `image_data`. POST `/meals` and `/analyses` also
accept multipart `payload` (the request as JSON text) and binary `meal_photo`. Custom GPT
Actions instead use a single `openaiFileIdRefs` attachment. Never send multiple photo
sources together. Analysis requests can take longer than an Action timeout; using the
conversation's own analysis avoids that extra model request.

## Corrections, retries and units

Use one UUID per creation and reuse it only for exact retries. A different payload under
the same key returns 409. Fetch the latest meal revision before PATCH. PATCH requires a
complete replacement ingredient analysis or manual nutrition values; manual replacement
clears the previous food score. Correcting via analysis drafts also preserves history.
Body-weight update/delete use the numeric entry revision. A 409 requires a fresh read.

Eating timestamps must carry an offset consistent with the supplied timezone. Discipline
uses the eating time, not import time. Copied meals retain the food composition score but
receive a new discipline score. Meal portion weights are grams; body weight is kg.

## Development

```
pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python scripts/export_openapi.py docs/openapi.json
```

The schema exporter uses a temporary database even if a production DATABASE_URL exists.
It never connects to the production database. Server rollout still needs a real database
backup and configured hosting credentials; integration tests use reconstructed schemas.
