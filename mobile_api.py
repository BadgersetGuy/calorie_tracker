"""Additive Android API. Existing user/meal records are reused, never recreated."""
import copy
from datetime import datetime, timedelta, timezone
import hmac
import json
import os
import uuid

from flask import Blueprint, jsonify, request, Response
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer

import analysis_engine as engine
import meal_timing
import meal_suggestions
from photo_inputs import photo_from_request


def register_mobile_api(app, db, User, Meal):
    class Draft(db.Model):
        __tablename__ = "mobile_analysis_draft"
        id = db.Column(db.String(36), primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        revision = db.Column(db.Integer, nullable=False, default=1)
        context = db.Column(db.Text, nullable=False)
        photo = db.Column(db.Text)
        result = db.Column(db.Text, nullable=False)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        saved_meal_id = db.Column(db.Integer)

    class Details(db.Model):
        __tablename__ = "mobile_meal_details"
        meal_id = db.Column(db.Integer, db.ForeignKey("meal.id"), primary_key=True)
        analysis = db.Column(db.Text)
        source_meal_id = db.Column(db.Integer)
        source_draft_id = db.Column(db.String(36), unique=True)
        request_key = db.Column(db.String(36), unique=True)
        copy_signature = db.Column(db.String(64))

    class CachedAnalysis(db.Model):
        __tablename__ = "mobile_analysis_cache"
        key = db.Column(db.String(64), primary_key=True)
        result = db.Column(db.Text, nullable=False)

    class Timing(db.Model):
        __tablename__ = "mobile_meal_timing"
        meal_id = db.Column(db.Integer, db.ForeignKey("meal.id"), primary_key=True)
        score_data = db.Column(db.Text, nullable=False)

    class SuggestionBatch(db.Model):
        __tablename__ = "mobile_suggestion_batch"
        id = db.Column(db.String(36), primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        payload = db.Column(db.Text, nullable=False)

    class SuggestionFeedback(db.Model):
        __tablename__ = "mobile_suggestion_feedback"
        user_id = db.Column(db.Integer, db.ForeignKey("user.id"), primary_key=True)
        recipe_id = db.Column(db.String(80), primary_key=True)
        action = db.Column(db.String(10), nullable=False)

    with app.app_context():
        # Only create these additive tables. Do not alter live tables or overwrite old scores.
        db.metadata.create_all(db.engine, tables=[Draft.__table__, Details.__table__, CachedAnalysis.__table__,
            Timing.__table__, SuggestionBatch.__table__, SuggestionFeedback.__table__])

    api = Blueprint("mobile", __name__, url_prefix="/api/v2")

    @app.before_request
    def mobile_auth():
        # With a household token configured protect legacy endpoints too: otherwise they
        # would bypass authentication and still expose the same meals.
        if request.path in ("/health", "/", "/openapi.json"):
            return None
        token = os.getenv("MOBILE_API_TOKEN", "")
        if not token:
            if request.path.startswith("/api/v2") or request.path == "/mcp":
                return jsonify(error="Android access is not configured on the server"), 503
            return None
        provided = request.headers.get("Authorization", "")
        if not hmac.compare_digest(provided, "Bearer " + token):
            return jsonify(error="Connect with your household access token"), 401

    @app.get("/health")
    def health():
        return jsonify(status="ok", api_version=2, release=os.getenv("RELEASE_COMMIT", "local"))

    @app.get("/openapi.json")
    def openapi_contract():
        from api_contract import build_openapi
        return jsonify(build_openapi(app))

    @api.errorhandler(ValueError)
    def bad_input(error):
        db.session.rollback()
        return jsonify(error=str(error)), 400

    @api.errorhandler(IntegrityError)
    def conflict(error):
        db.session.rollback()
        return jsonify(error="This change was already saved or conflicts with an existing record. Refresh and try again."), 409

    def body():
        if request.mimetype == "multipart/form-data":
            try:
                data = json.loads(request.form.get("payload", ""))
            except ValueError:
                raise ValueError("Multipart uploads require a JSON payload form field") from None
        else:
            data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError("A JSON object is required")
        return data

    def user(value):
        try:
            found = db.session.get(User, int(value))
        except (ValueError, TypeError):
            found = None
        if not found:
            raise ValueError("Select an existing profile")
        return found

    def day(value):
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except (ValueError, TypeError):
            raise ValueError("Date must be YYYY-MM-DD") from None

    def meal_date(value):
        # Android supplies an offset timestamp so history is correct in the user's timezone.
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError()
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Meal time must include a timezone offset") from None

    def text(value, maximum=8000):
        if not isinstance(value, str) or len(value) > maximum:
            raise ValueError("Text is too long or invalid")
        return value.strip()

    def serialize(meal):
        detail = db.session.get(Details, meal.id)
        timing = db.session.get(Timing, meal.id)
        discipline = json.loads(timing.score_data) if timing else meal_timing.score(meal_timing.local_time(meal.date), inferred=True)
        return dict(id=meal.id, user_id=meal.user_id, date=meal.date.isoformat() + "Z",
                    weight=meal.weight, description=meal.description or "Meal",
                    calories=meal.calories, protein=meal.protein, carbs=meal.carbs,
                    fat=meal.fat, image_data=meal.image_data if (request.args.get("include_images") == "true" or (request.args.get("include_images") != "false" and request.headers.get("X-Meal-Client") == "android")) else None,
                    has_photo=bool(meal.image_data), revision=meal_signature(meal),
                    legacy_psoriasis_score=meal.psoriasis_score,
                    discipline=discipline,
                    analysis=json.loads(detail.analysis) if detail and detail.analysis else None,
                    source_meal_id=detail.source_meal_id if detail else None)

    def summaries(query, full_analysis=False):
        # Avoid selecting large historical photos, hashing them for revisions, or
        # running per-row metadata queries merely to draw a list.
        rows = query.options(defer(Meal.image_data)).add_columns(Meal.image_data.isnot(None)).all()
        ids = [meal.id for meal, _ in rows]
        details = {d.meal_id: d for d in Details.query.filter(Details.meal_id.in_(ids)).all()} if ids else {}
        timings = {t.meal_id: t for t in Timing.query.filter(Timing.meal_id.in_(ids)).all()} if ids else {}
        result = []
        for meal, photo in rows:
            detail, timing = details.get(meal.id), timings.get(meal.id)
            analysis = json.loads(detail.analysis) if detail and detail.analysis else None
            result.append(dict(id=meal.id, user_id=meal.user_id, date=meal.date.isoformat() + "Z",
                weight=meal.weight, description=meal.description or "Meal", calories=meal.calories,
                protein=meal.protein, carbs=meal.carbs, fat=meal.fat, has_photo=bool(photo),
                legacy_psoriasis_score=meal.psoriasis_score,
                discipline=json.loads(timing.score_data) if timing else meal_timing.score(meal_timing.local_time(meal.date), inferred=True),
                analysis=(analysis if full_analysis else dict(score=analysis.get("score"))) if analysis else None,
                source_meal_id=detail.source_meal_id if detail else None))
        return result

    def meal_signature(record):
        detail = db.session.get(Details, record.id)
        # Snapshot used to detect edits from a second phone while a draft is open.
        return engine.fingerprint(dict(id=record.id, weight=record.weight, description=record.description,
            date=record.date.isoformat(),
            legacy_psoriasis_score=record.psoriasis_score,
            totals={n: getattr(record, n) for n in ("calories", "protein", "carbs", "fat")},
            analysis=detail.analysis if detail else None), record.image_data)

    def draft_data(draft):
        return dict(id=draft.id, user_id=draft.user_id, revision=draft.revision,
                    result=json.loads(draft.result), saved_meal_id=draft.saved_meal_id)

    def get_draft(draft_id):
        draft = db.session.get(Draft, draft_id)
        if not draft:
            raise ValueError("Analysis draft was not found")
        return draft

    def timing_input(data):
        timestamp = data.get("eaten_at") or data.get("date")
        utc = meal_date(timestamp)
        local = (meal_timing.confirmed_time(timestamp, data.get("timezone")) if data.get("eaten_at")
                 else meal_timing.local_time(utc, data.get("timezone")))
        return utc, local

    def store_timing(record, local):
        timing = db.session.get(Timing, record.id) or Timing(meal_id=record.id)
        timing.score_data = json.dumps(meal_timing.score(local))
        db.session.add(timing)

    def perform(context, photo):
        key = engine.fingerprint(context, photo)
        cached = db.session.get(CachedAnalysis, key)
        if cached:
            return json.loads(cached.result)
        result = engine.analyze(context, photo)
        # Cache only validated responses. Database conflict is safe to retry.
        db.session.add(CachedAnalysis(key=key, result=json.dumps(result)))
        return result

    @api.get("/profiles")
    def profiles():
        return jsonify([dict(id=u.id, username=u.username,
            targets={n: getattr(u, "target_" + n) for n in ("calories", "protein", "carbs", "fat")}
                if any(getattr(u, "target_" + n) is not None for n in ("calories", "protein", "carbs", "fat")) else None)
            for u in User.query.order_by(User.username).all()])

    @api.post("/profiles")
    def create_profile():
        name = text(body().get("username", ""), 80)
        if not name:
            raise ValueError("Enter a profile name")
        if User.query.filter_by(username=name).first():
            raise ValueError("A profile already has that name")
        record = User(username=name)
        db.session.add(record)
        db.session.commit()
        return jsonify(id=record.id, username=record.username, targets=None), 201

    @api.put("/profiles/<int:profile_id>/targets")
    def targets(profile_id):
        profile = user(profile_id)
        data = body()
        result = {n: engine.positive(data.get(n), n, maximum=20000 if n == "calories" else 2000)
                  for n in ("calories", "protein", "carbs", "fat")}
        for nutrient, value in result.items():
            setattr(profile, "target_" + nutrient, value)
        db.session.commit()
        return jsonify(result)

    @api.get("/meals")
    def meals():
        profile = user(request.args.get("user_id"))
        date = day(request.args.get("date", datetime.utcnow().strftime("%Y-%m-%d")))
        offset = int(request.args.get("offset_minutes", "0"))
        if not -840 <= offset <= 840:
            raise ValueError("Timezone offset is invalid")
        start = date - timedelta(minutes=offset)
        records = Meal.query.filter(Meal.user_id == profile.id, Meal.date >= start,
                Meal.date < start + timedelta(days=1)).order_by(Meal.date.desc())
        return jsonify(summaries(records) if request.args.get("view") == "summary" else [serialize(record) for record in records.all()])

    @api.get("/history")
    def history():
        profile = user(request.args.get("user_id"))
        query = text(request.args.get("query", ""), 120)
        offset = int(request.args.get("offset", 0))
        limit = int(request.args.get("limit", 30))
        if not 0 <= offset <= 100000:
            raise ValueError("History offset is invalid")
        if not 1 <= limit <= 30:
            raise ValueError("History limit must be between 1 and 30")
        records = Meal.query.filter(Meal.user_id == profile.id)
        if query:
            records = records.filter(Meal.description.contains(query, autoescape=True))
        total = records.count()
        page = records.order_by(Meal.date.desc(), Meal.id.desc()).offset(offset).limit(limit)
        return jsonify(meals=summaries(page) if request.args.get("view") == "summary" else [serialize(record) for record in page.all()], total=total)

    @api.get("/meals/<int:meal_id>")
    def get_meal(meal_id):
        record = db.session.get(Meal, meal_id)
        if not record:
            raise ValueError("Meal not found")
        return jsonify(serialize(record))

    @api.delete("/meals/<int:meal_id>")
    def delete_meal(meal_id):
        record = db.session.get(Meal, meal_id)
        if not record:
            raise ValueError("Meal not found")
        app.extensions["archive_meal"](record)
        Details.query.filter_by(meal_id=record.id).delete()
        Timing.query.filter_by(meal_id=record.id).delete()
        db.session.delete(record)
        db.session.commit()
        return jsonify(success=True)

    @api.post("/analyses")
    def new_analysis():
        data = body()
        profile = user(data.get("user_id"))
        description = text(data.get("text", ""))
        photo = photo_from_request(data)
        previous = None
        source_signature = None
        reused = None
        if data.get("source_meal_id"):
            source = db.session.get(Meal, int(data["source_meal_id"]))
            if not source:
                raise ValueError("Original meal not found")
            detail = db.session.get(Details, source.id)
            source_signature = meal_signature(source)
            photo = photo or engine.normalize_stored_photo(source.image_data)
            previous = json.loads(detail.analysis) if detail and detail.analysis else {
                "description": source.description, "weight": source.weight,
                "totals": {n: getattr(source, n) for n in ("calories", "protein", "carbs", "fat")}}
            if data.get("use_existing_analysis") is True:
                if previous.get("status") != "ready" or not previous.get("ingredients"):
                    raise ValueError("This older meal needs analysis before individual items can be edited")
                reused = engine.calculate(previous)
        elif data.get("use_existing_analysis"):
            raise ValueError("Choose an existing meal to edit its items")
        if not description and not photo:
            raise ValueError("Take a photo or describe your meal")
        weight = engine.positive(data["weight"], "Weight", False, 20000) if data.get("weight") else None
        context = dict(text=description, weight=weight, previous=previous, conversation=[],
            source_meal_id=data.get("source_meal_id"), source_signature=source_signature)
        try:
            result = reused if reused is not None else perform(context, photo)
        except RuntimeError as error:
            return jsonify(error=str(error)), 502
        draft = Draft(id=str(uuid.uuid4()), user_id=profile.id, context=json.dumps(context),
                      photo=photo, result=json.dumps(result))
        db.session.add(draft)
        db.session.commit()
        return jsonify(draft_data(draft)), 201

    @api.get("/analyses/<draft_id>")
    def read_analysis(draft_id):
        draft = get_draft(draft_id)
        result = draft_data(draft)
        result["has_photo"] = bool(draft.photo)
        if request.args.get("include_context") == "true": result["context"] = json.loads(draft.context)
        return jsonify(result)

    @api.get("/analyses/<draft_id>/photo")
    def draft_photo(draft_id):
        draft = get_draft(draft_id)
        if not draft.photo: return jsonify(error="No photo is stored in this draft"), 404
        import base64
        return Response(base64.b64decode(draft.photo), mimetype="image/jpeg", headers={"Cache-Control": "private, no-store"})

    @api.post("/analyses/<draft_id>/clarifications")
    def clarify(draft_id):
        data = body()
        draft = get_draft(draft_id)
        revision = int(data.get("revision", 0))
        if draft.saved_meal_id:
            return jsonify(error="Meal is already saved; start a new analysis from History"), 409
        if revision != draft.revision:
            return jsonify(error="Analysis changed. Reload before clarifying."), 409
        message = text(data.get("text", ""))
        if not message:
            raise ValueError("Enter a clarification")
        context = json.loads(draft.context)
        previous = json.loads(draft.result)
        if len(context["conversation"]) >= 30:
            raise ValueError("Please start a new analysis")
        context["conversation"].append(dict(questions=previous.get("questions", []), answer=message))
        context["previous"] = previous
        if data.get("weight"):
            context["weight"] = engine.positive(data["weight"], "Weight", False, 20000)
        # Corrections in natural language supersede the original total; ask the model
        # to resolve it rather than enforcing a stale number on a changed portion.
        else:
            context["previous_explicit_weight"] = context.get("weight")
            context["weight"] = None
        try:
            result = perform(context, draft.photo)
        except RuntimeError as error:
            return jsonify(error=str(error)), 502
        updated = db.session.execute(update(Draft).where(Draft.id == draft.id,
            Draft.revision == revision, Draft.saved_meal_id.is_(None)).values(
                context=json.dumps(context), result=json.dumps(result), revision=revision + 1))
        if updated.rowcount != 1:
            db.session.rollback()
            return jsonify(error="Analysis changed while you were editing; reload it."), 409
        db.session.commit()
        db.session.expire_all()
        return jsonify(draft_data(get_draft(draft_id)))

    @api.put("/analyses/<draft_id>/ingredients")
    def edit_ingredients(draft_id):
        data = body()
        draft = get_draft(draft_id)
        revision = int(data.get("revision", 0))
        if draft.saved_meal_id or revision != draft.revision:
            return jsonify(error="Analysis changed or was saved. Reload before editing items."), 409
        result = json.loads(draft.result)
        if result.get("status") != "ready":
            raise ValueError("Finish the clarification before editing item quantities")
        items = data.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 40:
            raise ValueError("Keep at least one item, with at most 40 items")
        original = result["ingredients"]
        kept, seen = [], set()
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Each item needs its original index and grams")
            index = item.get("index")
            if type(index) is not int or not 0 <= index < len(original) or index in seen:
                raise ValueError("Item indices must be unique and refer to the current analysis")
            seen.add(index)
            component = dict(original[index])
            component["grams"] = engine.positive(item.get("grams"), "Item grams", False, 20000)
            kept.append(component)
        if sum(item["grams"] for item in kept) > 20000:
            raise ValueError("Total meal weight must be at most 20000 grams")
        result["ingredients"] = kept
        result["description"] = ", ".join(f'{item["name"]} ({item["grams"]:g} g)' for item in kept)
        note = "Item quantities and removals were set by the user; retained nutrient estimates per 100 g are unchanged."
        result["assumptions"] = list(dict.fromkeys([*result.get("assumptions", []), note]))
        result = engine.calculate(result)
        context = json.loads(draft.context)
        if len(context["conversation"]) >= 30:
            raise ValueError("Please start a new analysis")
        context["conversation"].append(dict(questions=[], answer="Replace the earlier item list and quantities with exactly: " + result["description"] + ". Removed items are no longer in this meal."))
        context["previous"] = result
        context["previous_explicit_weight"] = context.get("weight")
        context["weight"] = None
        updated = db.session.execute(update(Draft).where(Draft.id == draft.id,
            Draft.revision == revision, Draft.saved_meal_id.is_(None)).values(
                context=json.dumps(context), result=json.dumps(result), revision=revision + 1))
        if updated.rowcount != 1:
            db.session.rollback()
            return jsonify(error="Analysis changed while you were editing; reload it."), 409
        db.session.commit()
        db.session.expire_all()
        return jsonify(draft_data(get_draft(draft_id)))

    @api.post("/analyses/<draft_id>/save")
    def save_analysis(draft_id):
        data = body()
        draft = get_draft(draft_id)
        if draft.saved_meal_id:
            saved_record = db.session.get(Meal, draft.saved_meal_id)
            if not saved_record:
                return jsonify(error="This saved meal has been deleted"), 410
            return jsonify(serialize(saved_record))
        if int(data.get("revision", 0)) != draft.revision:
            return jsonify(error="Analysis changed. Review the current result before saving."), 409
        result = json.loads(draft.result)
        if result["status"] != "ready":
            raise ValueError("Answer the clarification questions before saving")
        replace_id = data.get("replace_meal_id")
        if replace_id:
            context = json.loads(draft.context)
            record = db.session.get(Meal, int(replace_id))
            if not record or record.user_id != draft.user_id or int(replace_id) != int(context.get("source_meal_id") or 0):
                raise ValueError("This analysis cannot replace that meal")
            if context.get("source_signature") != meal_signature(record):
                return jsonify(error="This meal changed on another device. Start a fresh analysis from History."), 409
            if data.get("eaten_at"):
                record.date, local = timing_input(data)
            else:
                local = None
        else:
            utc, local = timing_input(data)
            record = Meal(user_id=draft.user_id, date=utc)
        record.description = result["description"]
        record.weight = result["weight"]
        record.image_data = engine.normalize_stored_photo(draft.photo)
        for nutrient in ("calories", "protein", "carbs", "fat"):
            setattr(record, nutrient, result["totals"][nutrient])
        db.session.add(record)
        db.session.flush()
        if local is not None:
            store_timing(record, local)
        claimed = db.session.execute(update(Draft).where(Draft.id == draft.id,
            Draft.revision == int(data["revision"]), Draft.saved_meal_id.is_(None)).values(saved_meal_id=record.id))
        if claimed.rowcount != 1:
            db.session.rollback()
            return jsonify(error="Already saved or changed; refresh the analysis."), 409
        detail = db.session.get(Details, record.id) or Details(meal_id=record.id)
        detail.analysis = json.dumps(result)
        detail.source_draft_id = draft.id
        db.session.add(detail)
        db.session.commit()
        return jsonify(serialize(record)), 201

    @api.post("/meals/<int:meal_id>/copy")
    def copy_meal(meal_id):
        data = body()
        original = db.session.get(Meal, meal_id)
        if not original:
            raise ValueError("Original meal not found")
        target = user(data.get("user_id"))
        stamp, local = timing_input(data)
        key = text(data.get("request_key", ""), 36)
        try:
            uuid.UUID(key)
        except ValueError:
            raise ValueError("A unique request key is required") from None
        if ("weight" in data) == ("portion_percent" in data):
            raise ValueError("Provide a weight OR a percentage")
        if "weight" in data:
            if not original.weight or original.weight <= 0:
                raise ValueError("This meal has no known weight. Use a percentage instead.")
            factor = engine.positive(data["weight"], "Weight", False, 20000) / original.weight
        else:
            factor = engine.positive(data["portion_percent"], "Portion percent", False, 1000) / 100
        signature = engine.fingerprint(dict(source=meal_id, target=target.id, date=stamp.isoformat(),
            timezone=str(local.tzinfo), factor=factor), None)
        existing = Details.query.filter_by(request_key=key).first()
        if existing:
            if existing.copy_signature != signature:
                return jsonify(error="Request key already used for a different copy"), 409
            return jsonify(serialize(db.session.get(Meal, existing.meal_id)))
        detail = db.session.get(Details, original.id)
        analysis = copy.deepcopy(json.loads(detail.analysis)) if detail and detail.analysis else None
        if analysis:
            for ingredient in analysis["ingredients"]:
                ingredient["grams"] *= factor
            analysis = engine.calculate(analysis)
        record = Meal(user_id=target.id, date=stamp, description=original.description,
            psoriasis_score=original.psoriasis_score,
            image_data=engine.normalize_stored_photo(original.image_data), weight=original.weight * factor,
            **{n: getattr(original, n) * factor for n in ("calories", "protein", "carbs", "fat")})
        db.session.add(record)
        db.session.flush()
        store_timing(record, local)
        db.session.add(Details(meal_id=record.id, analysis=json.dumps(analysis) if analysis else None,
            source_meal_id=original.id, request_key=key, copy_signature=signature))
        db.session.commit()
        return jsonify(serialize(record)), 201

    @api.get("/suggestions")
    def latest_suggestions():
        profile = user(request.args.get("user_id"))
        batch = SuggestionBatch.query.filter_by(user_id=profile.id).order_by(SuggestionBatch.created_at.desc()).first()
        if not batch:
            return jsonify(ideas=[], version=meal_suggestions.VERSION)
        payload = json.loads(batch.payload)
        current_count = Meal.query.filter_by(user_id=profile.id).count()
        current_latest_id = db.session.query(db.func.max(Meal.id)).filter(Meal.user_id == profile.id).scalar()
        payload["needs_refresh"] = (payload.get("history_total") != current_count
            or payload.get("latest_meal_id") != current_latest_id
            or payload.get("generated_local_date") != datetime.now(meal_timing.zone()).date().isoformat())
        feedback = {f.recipe_id: f.action for f in SuggestionFeedback.query.filter_by(user_id=profile.id)}
        for idea in payload["ideas"]:
            idea["feedback"] = feedback.get(idea["id"])
        payload["ideas"] = [idea for idea in payload["ideas"] if idea.get("feedback") != "skip"]
        return jsonify(payload)

    @api.post("/suggestions")
    def new_suggestions():
        data = body()
        profile = user(data.get("user_id"))
        key = text(data.get("request_key", ""), 36)
        try:
            uuid.UUID(key)
        except ValueError:
            raise ValueError("A unique suggestion request key is required") from None
        avoid = data.get("avoid", [])
        if not isinstance(avoid, list) or len(avoid) > 30:
            raise ValueError("Enter up to 30 excluded ingredients")
        avoid = sorted({text(word, 80).casefold() for word in avoid if text(word, 80)})
        old = db.session.get(SuggestionBatch, key)
        if old:
            payload = json.loads(old.payload)
            if old.user_id != profile.id or payload.get("avoid", []) != avoid:
                return jsonify(error="Suggestion request key was already used"), 409
            return jsonify(payload)
        history = []
        recent = Meal.query.options(defer(Meal.image_data)).filter_by(user_id=profile.id).order_by(Meal.date.desc(), Meal.id.desc()).limit(120).all()
        recent_details = {d.meal_id: d for d in Details.query.filter(Details.meal_id.in_([m.id for m in recent])).all()} if recent else {}
        for record in recent:
            detail = recent_details.get(record.id)
            analysis = json.loads(detail.analysis) if detail and detail.analysis else {}
            history.append(dict(description=record.description or "", ingredients=[i["name"] for i in analysis.get("ingredients", [])]))
        batches = SuggestionBatch.query.filter_by(user_id=profile.id).order_by(SuggestionBatch.created_at.desc()).limit(2).all()
        excluded = {i["id"] for b in batches for i in json.loads(b.payload)["ideas"]}
        feedback = {f.recipe_id: f.action for f in SuggestionFeedback.query.filter_by(user_id=profile.id)}
        seed = SuggestionBatch.query.filter_by(user_id=profile.id).count()
        payload = meal_suggestions.suggest(history, excluded, feedback, avoid, seed)
        payload.update(id=key, user_id=profile.id, avoid=avoid, needs_refresh=False,
            history_total=Meal.query.filter_by(user_id=profile.id).count(),
            latest_meal_id=db.session.query(db.func.max(Meal.id)).filter(Meal.user_id == profile.id).scalar(),
            generated_local_date=datetime.now(meal_timing.zone()).date().isoformat())
        db.session.add(SuggestionBatch(id=key, user_id=profile.id, payload=json.dumps(payload)))
        db.session.commit()
        return jsonify(payload), 201

    @api.put("/suggestions/<recipe_id>/feedback")
    def suggestion_feedback(recipe_id):
        data = body()
        profile = user(data.get("user_id"))
        action = data.get("action")
        if recipe_id not in meal_suggestions.BY_ID or action not in ("like", "skip", "clear"):
            raise ValueError("Choose Like, Skip, or Clear for an existing idea")
        feedback = db.session.get(SuggestionFeedback, (profile.id, recipe_id))
        if action == "clear":
            if feedback: db.session.delete(feedback)
        else:
            feedback = feedback or SuggestionFeedback(user_id=profile.id, recipe_id=recipe_id)
            feedback.action = action
            db.session.add(feedback)
        db.session.commit()
        return jsonify(success=True)

    @api.delete("/suggestions/feedback")
    def clear_suggestion_feedback():
        profile = user(body().get("user_id"))
        SuggestionFeedback.query.filter_by(user_id=profile.id).delete()
        db.session.commit()
        return jsonify(success=True)

    from records_api import register_record_routes
    with app.app_context():
        register_record_routes(api, db, User, Meal, Details, Draft, Timing,
            dict(body=body, user=user, day=day, meal_date=meal_date, serialize=serialize, summarize=summaries,
                 timing_input=timing_input, store_timing=store_timing, signature=meal_signature))
    app.extensions["mobile_timing_model"] = Timing
    app.register_blueprint(api)
    return Details
