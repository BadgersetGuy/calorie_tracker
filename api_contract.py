"""OpenAPI contract for REST clients and private Custom GPT Actions."""
import copy
import os
import re
import analysis_engine

def obj(properties, required=()):
    return dict(type="object", properties=properties, required=list(required), additionalProperties=False)

S = {"type": "string"}
N = {"type": "number"}
I = {"type": "integer"}
WHEN = dict(type="string", format="date-time")
UUID = dict(type="string", format="uuid")
PHOTO = {"image_data": dict(type="string", format="byte", description="Actual base64 photo bytes, only from a file-capable client; never fabricate them."),
    "openaiFileIdRefs": dict(type="array", items={"type": "string"}, maxItems=1,
        description="Exactly one meal photo uploaded in this conversation. GPT Actions replace its file ID with attachment metadata including a short-lived download_link.")}
TIME = dict(eaten_at=WHEN, timezone=dict(type="string", description="IANA eating timezone, e.g. Europe/Bucharest"))
TOTALS = obj({n: dict(type="number", minimum=0) for n in ("calories", "protein", "carbs", "fat")}, ("calories", "protein", "carbs", "fat"))
WRITE_MEAL = obj(dict(user_id=I, request_key=UUID, description=S, weight=N, totals=TOTALS,
    analysis={"$ref": "#/components/schemas/MealAnalysis"}, **TIME, **PHOTO), ("user_id", "request_key", "eaten_at", "timezone"))
EDIT_MEAL = copy.deepcopy(WRITE_MEAL)
EDIT_MEAL["properties"]["revision"] = dict(type="string", description="Revision returned by the latest meal retrieval")
EDIT_MEAL["required"] = ["revision"]

REQUESTS = {
    ("/profiles", "post"): obj(dict(username=S), ["username"]),
    ("/profiles/{profile_id}", "patch"): obj(dict(username=S), ["username"]),
    ("/profiles/{profile_id}/targets", "put"): TOTALS,
    ("/meals", "post"): WRITE_MEAL,
    ("/meals/{meal_id}", "patch"): EDIT_MEAL,
    ("/meals/{meal_id}/copy", "post"): obj(dict(user_id=I, request_key=UUID, portion_percent=N, weight=N, **TIME), ["user_id", "request_key", "eaten_at", "timezone"]),
    ("/analyses", "post"): obj(dict(user_id=I, text=S, weight=N, source_meal_id=I, use_existing_analysis=dict(type="boolean"), **PHOTO), ["user_id"]),
    ("/analyses/{draft_id}/ingredients", "put"): obj(dict(revision=I,
        items=dict(type="array", minItems=1, maxItems=40, items=obj(dict(index=dict(type="integer", minimum=0), grams=dict(type="number", exclusiveMinimum=0, maximum=20000)), ["index", "grams"]))), ["revision", "items"]),
    ("/analyses/{draft_id}/clarifications", "post"): obj(dict(revision=I, text=S, weight=N), ["revision", "text"]),
    ("/analyses/{draft_id}/save", "post"): obj(dict(revision=I, replace_meal_id=I, **TIME), ["revision", "eaten_at", "timezone"]),
    ("/suggestions", "post"): obj(dict(user_id=I, request_key=UUID, avoid=dict(type="array", items=S)), ["user_id", "request_key"]),
    ("/suggestions/{recipe_id}/feedback", "put"): obj(dict(user_id=I, action=dict(type="string", enum=["like", "skip", "clear"])), ["user_id", "action"]),
    ("/suggestions/feedback", "delete"): obj(dict(user_id=I), ["user_id"]),
    ("/weights", "post"): obj(dict(user_id=I, request_key=UUID, weight_kg=N, recorded_at=WHEN, notes=S), ["user_id", "request_key", "weight_kg", "recorded_at"]),
    ("/weights/{entry_id}", "put"): obj(dict(revision=I, weight_kg=N, recorded_at=WHEN, notes=S), ["revision", "weight_kg", "recorded_at"]),
    ("/weights/{entry_id}", "delete"): obj(dict(revision=I), ["revision"]),
}

DESCRIPTIONS = {
    ("/meals", "post"): "Log a meal with an analysis already produced in chat, or explicit manual nutrition totals. Provide structured analysis OR description/totals, and one photo source if available. The server recomputes scores and ingredient totals; it does not call another model. Reuse a request_key only to retry the same submission.",
    ("/meals/{meal_id}", "patch"): "Edit a meal using its current revision. Supply a complete replacement analysis OR description, weight and totals. A manual replacement clears the previous dietary score; historical 1–10 scores remain separate. Optional eating time/photo replace those values.",
    ("/meals/{meal_id}/copy", "post"): "Reuse a past meal for either profile. Supply portion_percent OR weight in grams. Nutrition scales arithmetically, dietary composition score stays fixed, discipline uses the new eating time.",
    ("/analyses", "post"): "Start server-side photo/text analysis. This can make a paid model request. Returns a persisted draft with status ready or clarify. Never claim a meal is saved until save succeeds.",
    ("/analyses/{draft_id}/ingredients", "put"): "Change grams or remove items from a ready draft without another model request. Submit the retained original ingredient indices and positive grams. Omitted items are removed. Totals and dietary score are recalculated from unchanged nutrient densities. To edit an existing meal, first create a draft using source_meal_id and use_existing_analysis=true, then review and save it. Add or identify new foods through clarification text.",
    ("/analyses/{draft_id}/save", "post"): "Save a reviewed ready draft. replace_meal_id updates that original meal only when the draft was created from it; otherwise creates a meal. Repeating a successful save returns the saved meal.",
    ("/summaries", "get"): "Daily or ranged calories, protein/carbs/fat, meal timestamps, personal discipline scores, dietary-pattern score coverage, historical psoriasis scores, and logged body weights. No meals means zero logged intake, not proof of fasting. Dietary scores are app heuristics, not clinical inflammation measurements.",
    ("/logs", "get"): "Paginated creation/update/deletion records since the upgraded backend was installed. Older meal history remains available separately.",
    ("/weights", "get"): "Read body weight in kg; distinguishes it from meal portion weight. Paginated, optionally date-filtered.",
}

def build_openapi(app):
    paths = {}
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api/v2/"): continue
        path = re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", rule.rule)
        short = path[len("/api/v2"):]
        entry = paths.setdefault(path, {})
        for method in sorted(rule.methods - {"OPTIONS", "HEAD"}):
            verb = method.lower()
            operation = dict(operationId=rule.endpoint.replace(".", "_"),
                summary=rule.endpoint.rsplit(".", 1)[-1].replace("_", " ").capitalize(),
                description=DESCRIPTIONS.get((short, verb), "Authenticated household meal diary operation."),
                responses={"200": dict(description="Successful JSON response", content={"application/json": {"schema": {"type": "object", "properties": {}, "additionalProperties": True}}}),
                           "400": dict(description="Invalid input"), "401": dict(description="Missing/invalid household token"), "409": dict(description="Revision or idempotency conflict")})
            params = []
            for name in sorted(rule.arguments):
                params.append(dict(name=name, **{"in": "path"}, required=True,
                    schema=I if name in ("meal_id", "profile_id") else S))
            if verb == "get":
                if short in ("/meals", "/history", "/analyses", "/suggestions", "/weights", "/summaries", "/logs"):
                    params.append(dict(name="user_id", **{"in": "query"}, required=True, schema=I))
                if short in ("/history", "/analyses", "/weights", "/logs"):
                    for name in ("offset", "limit"):
                        if name == "limit" and short == "/history": continue
                        params.append(dict(name=name, **{"in": "query"}, schema=I))
                if short in ("/summaries", "/weights"):
                    for name in ("date", "start", "end", "timezone"):
                        params.append(dict(name=name, **{"in": "query"}, schema=S))
                if short == "/summaries": params.append(dict(name="include_meals", **{"in": "query"}, schema={"type": "boolean", "default": False}))
                if short == "/meals":
                    params.extend([dict(name="date", **{"in": "query"}, schema=S), dict(name="offset_minutes", **{"in": "query"}, schema=I)])
                if short == "/history": params.append(dict(name="query", **{"in": "query"}, schema=S))
                if short == "/analyses/{draft_id}": params.append(dict(name="include_context", **{"in": "query"}, schema={"type": "boolean"}))
            if "/photo" not in short and (short.startswith("/meals") or short in ("/history", "/summaries", "/analyses/{draft_id}/save")):
                params.append(dict(name="include_images", **{"in": "query"}, schema={"type": "boolean", "default": False}, description="False keeps chat responses compact. Fetch a stored photo through the authenticated photo endpoint."))
            if params: operation["parameters"] = params
            schema = REQUESTS.get((short, verb))
            if schema:
                operation["requestBody"] = dict(required=True, content={"application/json": {"schema": copy.deepcopy(schema)}})
                if short in ("/meals", "/analyses") and verb == "post":
                    operation["requestBody"]["content"]["multipart/form-data"] = {"schema": obj(dict(payload=dict(type="string", description="JSON-encoded request body"), meal_photo=dict(type="string", format="binary")), ["payload", "meal_photo"])}
            if short.endswith("/photo"):
                operation["responses"]["200"] = dict(description="Stored JPEG", content={"image/jpeg": {"schema": dict(type="string", format="binary")}})
            if verb == "post": operation["responses"]["201"] = dict(description="Created successfully")
            if short in ("/profiles", "/meals") and verb == "get":
                operation["responses"]["200"]["content"]["application/json"]["schema"] = dict(type="array", items={"type": "object", "properties": {}, "additionalProperties": True})
            entry[verb] = operation
    return dict(openapi="3.1.0", info=dict(title="Everyday Meals household API", version="2.1.0",
        description="Shared API for Android, private GPT Actions and REST-based skills. Household bearer access covers both profiles."),
        servers=[dict(url=os.getenv("PUBLIC_API_URL", "https://calorie-tracker-billowing-rain-2129.fly.dev").rstrip("/"))],
        security=[dict(householdBearer=[])], paths=paths,
        components=dict(securitySchemes=dict(householdBearer=dict(type="http", scheme="bearer")), schemas=dict(MealAnalysis=analysis_engine.schema())))
