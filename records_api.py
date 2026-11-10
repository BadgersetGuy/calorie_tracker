"""REST reporting, direct chat imports, editable records and body-weight history."""
import base64
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import uuid

from flask import jsonify, request, Response, current_app
from jsonschema import validate, ValidationError
from sqlalchemy import event

import analysis_engine as engine
import meal_timing
from photo_inputs import photo_from_request
from media_previews import photo_bytes


def register_record_routes(api, db, User, Meal, Details, Draft, Timing, services):
    body, user, day = (services[n] for n in ("body", "user", "day"))
    serialize, timing_input, store_timing, signature = (services[n] for n in ("serialize", "timing_input", "store_timing", "signature"))

    class BodyWeight(db.Model):
        __tablename__ = "mobile_body_weight"
        id = db.Column(db.String(36), primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        recorded_at = db.Column(db.DateTime, nullable=False)
        weight_kg = db.Column(db.Float, nullable=False)
        notes = db.Column(db.Text, nullable=False, default="")
        revision = db.Column(db.Integer, nullable=False, default=1)

    class ChangeLog(db.Model):
        __tablename__ = "mobile_change_log"
        id = db.Column(db.String(36), primary_key=True)
        user_id = db.Column(db.Integer, nullable=False)
        entity = db.Column(db.String(30), nullable=False)
        record_id = db.Column(db.String(36), nullable=False)
        action = db.Column(db.String(20), nullable=False)
        timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        snapshot = db.Column(db.Text, nullable=False)

    with db.engine.begin() as connection:
        db.metadata.create_all(connection, tables=[BodyWeight.__table__, ChangeLog.__table__])

    def listen(model, entity, fields):
        for action, hook in (("created", "after_insert"), ("updated", "after_update"), ("deleted", "after_delete")):
            def record_change(mapper, connection, record, action=action):
                values = {name: getattr(record, name) for name in fields}
                snapshot = {name: value.isoformat() + "Z" if isinstance(value, datetime) else value for name, value in values.items()}
                connection.execute(ChangeLog.__table__.insert().values(id=str(uuid.uuid4()),
                    user_id=record.id if entity == "profile" else record.user_id,
                    entity=entity, record_id=str(record.id), action=action,
                    timestamp=datetime.utcnow(), snapshot=json.dumps(snapshot)))
            event.listen(model, hook, record_change)

    listen(Meal, "meal", ["id", "date", "weight", "description", "calories", "protein", "carbs", "fat", "psoriasis_score"])
    listen(BodyWeight, "body_weight", ["id", "recorded_at", "weight_kg", "notes"])
    listen(User, "profile", ["id", "username", "target_calories", "target_protein", "target_carbs", "target_fat"])

    def archive_meal(record):
        snapshot = serialize(record)
        snapshot.pop("image_data", None)
        db.session.add(ChangeLog(id=str(uuid.uuid4()), user_id=record.user_id, entity="meal",
            record_id=str(record.id), action="archived", snapshot=json.dumps(snapshot)))

    current_app.extensions["archive_meal"] = archive_meal

    def bounded_text(value, maximum=8000):
        if not isinstance(value, str) or len(value) > maximum:
            raise ValueError("Text is invalid or too long")
        return value.strip()

    def request_key(value):
        try:
            return str(uuid.UUID(value))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("A UUID request_key is required") from None

    def page():
        offset = int(request.args.get("offset", 0))
        limit = int(request.args.get("limit", 30))
        if not 0 <= offset <= 100000 or not 1 <= limit <= 100:
            raise ValueError("Use offset >= 0 and limit between 1 and 100")
        return offset, limit

    def date_range():
        local_zone = meal_timing.zone(request.args.get("timezone"))
        today = datetime.now(local_zone).date().isoformat()
        first = day(request.args.get("start", request.args.get("date", today)))
        last = day(request.args.get("end", request.args.get("date", today)))
        if last < first or (last - first).days > 365:
            raise ValueError("Choose a date range of at most 366 days")
        begin = first.replace(tzinfo=local_zone).astimezone(timezone.utc).replace(tzinfo=None)
        end = (last + timedelta(days=1)).replace(tzinfo=local_zone).astimezone(timezone.utc).replace(tzinfo=None)
        return local_zone, first, last, begin, end

    def imported_analysis(data):
        analysis = copy.deepcopy(data.get("analysis"))
        if analysis is None:
            return None
        # Ignore client-generated totals/scores: recompute them with the same server rubric.
        core = {name: analysis[name] for name in engine.schema()["required"] if name in analysis} if isinstance(analysis, dict) else {}
        try:
            validate(core, engine.schema())
        except ValidationError:
            raise ValueError("Analysis must match the published MealAnalysis schema") from None
        if core["status"] != "ready":
            raise ValueError("Resolve clarification questions before importing an analysis")
        core = engine.calculate(core)
        core.update(model="client-supplied", prompt_version="external-import-1", source="conversation_or_manual_import")
        return core

    def meal_values(data):
        analysis = imported_analysis(data)
        if analysis:
            return dict(description=analysis["description"], weight=analysis["weight"],
                **{n: analysis["totals"][n] for n in ("calories", "protein", "carbs", "fat")}), analysis
        description = bounded_text(data.get("description", ""))
        if not description:
            raise ValueError("Provide a meal description or structured analysis")
        totals = data.get("totals")
        if not isinstance(totals, dict):
            raise ValueError("Provide calories, protein, carbs and fat in totals, or a structured analysis")
        values = {n: engine.positive(totals.get(n), n, maximum=20000 if n == "calories" else 2000)
                  for n in ("calories", "protein", "carbs", "fat")}
        return dict(description=description, weight=engine.positive(data.get("weight", 0), "Weight", maximum=20000), **values), None

    @api.post("/meals")
    def import_meal():
        data = body()
        profile = user(data.get("user_id"))
        key = request_key(data.get("request_key"))
        values, analysis = meal_values(data)
        utc, local = timing_input(data)
        photo = photo_from_request(data)
        checksum = engine.fingerprint(dict(user=profile.id, values=values, analysis=analysis,
            date=utc.isoformat(), zone=str(local.tzinfo)), photo)
        existing = Details.query.filter_by(request_key=key).first()
        if existing:
            if existing.copy_signature != checksum:
                return jsonify(error="Request key was already used for a different meal"), 409
            record = db.session.get(Meal, existing.meal_id)
            if not record: return jsonify(error="The imported meal was deleted"), 410
            return jsonify(serialize(record))
        record = Meal(user_id=profile.id, date=utc, image_data=photo, **values)
        db.session.add(record); db.session.flush()
        db.session.add(Details(meal_id=record.id, request_key=key, copy_signature=checksum,
            analysis=json.dumps(analysis) if analysis else None))
        store_timing(record, local)
        db.session.commit()
        return jsonify(serialize(record)), 201

    @api.patch("/meals/<int:meal_id>")
    def edit_meal(meal_id):
        record = db.session.get(Meal, meal_id)
        if not record: raise ValueError("Meal not found")
        data = body()
        if data.get("revision") != signature(record):
            return jsonify(error="Meal changed; retrieve and review its current revision before editing"), 409
        before = serialize(record)
        before.pop("image_data", None)
        if data.get("analysis") is None and "weight" not in data:
            raise ValueError("Supply edible weight for a manual replacement, or 0 if unknown")
        values, analysis = meal_values(data)
        # Require an explicit replacement nutrition estimate; retain no stale score.
        for name, value in values.items(): setattr(record, name, value)
        if data.get("eaten_at") or data.get("date"):
            record.date, local = timing_input(data); store_timing(record, local)
        if any(name in data for name in ("image_data", "openaiFileIdRefs")) or request.files:
            record.image_data = photo_from_request(data)
        detail = db.session.get(Details, record.id) or Details(meal_id=record.id)
        detail.analysis = json.dumps(analysis) if analysis else None
        db.session.add(detail)
        db.session.add(ChangeLog(id=str(uuid.uuid4()), user_id=record.user_id, entity="meal",
            record_id=str(record.id), action="analysis_replaced", snapshot=json.dumps(dict(before=before, after_analysis=analysis))))
        db.session.commit()
        return jsonify(serialize(record))

    @api.get("/meals/<int:meal_id>/photo")
    def meal_photo(meal_id):
        record = db.session.get(Meal, meal_id)
        if not record or not record.image_data:
            return jsonify(error="No photo is stored for this meal"), 404
        return Response(photo_bytes(record.image_data, request.args.get("size", "original")), mimetype="image/jpeg",
            headers={"Cache-Control": "private, no-store"})

    @api.patch("/profiles/<int:profile_id>")
    def rename_profile(profile_id):
        profile = user(profile_id)
        name = bounded_text(body().get("username", ""), 80)
        if not name: raise ValueError("Enter a profile name")
        profile.username = name; db.session.commit()
        return jsonify(id=profile.id, username=profile.username)

    @api.get("/analyses")
    def list_analyses():
        profile = user(request.args.get("user_id"))
        offset, limit = page()
        query = Draft.query.filter_by(user_id=profile.id)
        return jsonify(total=query.count(), analyses=[dict(id=d.id, user_id=d.user_id,
            revision=d.revision, created_at=d.created_at.isoformat() + "Z", saved_meal_id=d.saved_meal_id,
            result=json.loads(d.result), context=json.loads(d.context))
            for d in query.order_by(Draft.created_at.desc(), Draft.id.desc()).offset(offset).limit(limit)])

    def weight_data(record):
        return dict(id=record.id, user_id=record.user_id, recorded_at=record.recorded_at.isoformat() + "Z",
            weight_kg=record.weight_kg, notes=record.notes, revision=record.revision)

    @api.get("/weights")
    def weights():
        profile = user(request.args.get("user_id"))
        offset, limit = page()
        query = BodyWeight.query.filter_by(user_id=profile.id)
        if any(request.args.get(name) for name in ("start", "end", "date")):
            _, _, _, first, last = date_range()
            query = query.filter(BodyWeight.recorded_at >= first, BodyWeight.recorded_at < last)
        return jsonify(total=query.count(), weights=[weight_data(w) for w in query.order_by(BodyWeight.recorded_at.desc(), BodyWeight.id.desc()).offset(offset).limit(limit)])

    def weight_values(data):
        kilograms = engine.positive(data.get("weight_kg"), "Body weight", False, 700)
        when = services["meal_date"](data.get("recorded_at"))
        notes = bounded_text(data.get("notes", ""), 2000)
        return dict(weight_kg=kilograms, recorded_at=when, notes=notes)

    @api.post("/weights")
    def create_weight():
        data = body(); profile = user(data.get("user_id"))
        key = request_key(data.get("request_key")); values = weight_values(data)
        record = db.session.get(BodyWeight, key)
        if record:
            if record.user_id != profile.id or any(getattr(record, k) != v for k, v in values.items()):
                return jsonify(error="Request key was already used for another weight entry"), 409
            return jsonify(weight_data(record))
        record = BodyWeight(id=key, user_id=profile.id, **values)
        db.session.add(record); db.session.commit()
        return jsonify(weight_data(record)), 201

    @api.put("/weights/<entry_id>")
    def edit_weight(entry_id):
        record = db.session.get(BodyWeight, entry_id)
        if not record: raise ValueError("Weight entry not found")
        data = body()
        if data.get("revision") != record.revision:
            return jsonify(error="Weight entry changed; reload before editing"), 409
        values = weight_values(data)
        changed = db.session.execute(db.update(BodyWeight).where(BodyWeight.id == entry_id,
            BodyWeight.revision == data["revision"]).values(**values, revision=data["revision"] + 1))
        if changed.rowcount != 1:
            db.session.rollback(); return jsonify(error="Weight entry changed"), 409
        # Bulk SQL bypasses ORM hooks; capture this update in the same transaction.
        db.session.add(ChangeLog(id=str(uuid.uuid4()), user_id=record.user_id, entity="body_weight",
            record_id=record.id, action="updated", snapshot=json.dumps(dict(weight_kg=values["weight_kg"], recorded_at=values["recorded_at"].isoformat() + "Z", notes=values["notes"]))))
        db.session.commit(); db.session.expire_all()
        return jsonify(weight_data(db.session.get(BodyWeight, entry_id)))

    @api.get("/weights/<entry_id>")
    def get_weight(entry_id):
        record = db.session.get(BodyWeight, entry_id)
        if not record: raise ValueError("Weight entry not found")
        return jsonify(weight_data(record))

    @api.delete("/weights/<entry_id>")
    def delete_weight(entry_id):
        record = db.session.get(BodyWeight, entry_id)
        if not record: raise ValueError("Weight entry not found")
        if body().get("revision") != record.revision:
            return jsonify(error="Weight entry changed; reload before deleting"), 409
        db.session.delete(record); db.session.commit()
        return jsonify(success=True)

    @api.get("/summaries")
    def summaries():
        profile = user(request.args.get("user_id"))
        local_zone, first, last, begin, end = date_range()
        records = Meal.query.filter(Meal.user_id == profile.id, Meal.date >= begin, Meal.date < end).order_by(Meal.date).all()
        weights = BodyWeight.query.filter(BodyWeight.user_id == profile.id, BodyWeight.recorded_at >= begin, BodyWeight.recorded_at < end).all()
        days = []
        current = first
        while current <= last:
            key = current.date().isoformat()
            meals = [m for m in records if meal_timing.local_time(m.date, str(local_zone)).date().isoformat() == key]
            serialized = [serialize(m) for m in meals]
            scored = [m for m in serialized if m["analysis"] and m["analysis"].get("score")]
            versions = {}
            for meal in scored:
                versions.setdefault(meal["analysis"]["score"]["version"], []).append(meal)
            by_version = []
            for version, group in versions.items():
                known_grams = sum(m["weight"] for m in group)
                value = round(sum(m["analysis"]["score"]["value"] * m["weight"] for m in group) / known_grams, 2) if known_grams else None
                by_version.append(dict(version=version, value=value, meal_count=len(group)))
            pattern = by_version[0]["value"] if len(by_version) == 1 else None
            discipline = min(m["discipline"]["value"] for m in serialized) if meals else None
            known_fiber = [m["analysis"]["totals"]["fiber"] for m in serialized if m["analysis"] and "fiber" in m["analysis"].get("totals", {})]
            totals = {n: round(sum(getattr(m, n) for m in meals), 2) for n in ("calories", "protein", "carbs", "fat")}
            totals["fiber"] = round(sum(known_fiber), 2) if known_fiber else None
            days.append(dict(date=key, meal_count=len(meals),
                totals=totals, fiber_meals_with_data=len(known_fiber),
                dietary_pattern=dict(value=pattern, scale="0–100", scored_meals=len(scored),
                    by_version=by_version,
                    unscored_meals=len(meals) - len(scored), method="Meal mass-weighted average of saved versioned app scores; not a clinical inflammation measure"),
                discipline=dict(value=discipline, scale="0–10", method="Lowest meal score of the day; early meals do not offset late eating", inferred_meals=sum(m["discipline"]["inferred"] for m in serialized)),
                meals=serialized if request.args.get("include_meals") == "true" else [dict(id=m["id"], date=m["date"], discipline=m["discipline"], legacy_psoriasis_score=m["legacy_psoriasis_score"]) for m in serialized],
                body_weights=[weight_data(w) for w in weights if meal_timing.local_time(w.recorded_at, str(local_zone)).date().isoformat() == key]))
            current += timedelta(days=1)
        return jsonify(user_id=profile.id, timezone=str(local_zone), days=days,
            targets={n: getattr(profile, "target_" + n) for n in ("calories", "protein", "carbs", "fat")})

    @api.get("/logs")
    def logs():
        profile = user(request.args.get("user_id"))
        offset, limit = page()
        query = ChangeLog.query.filter_by(user_id=profile.id)
        return jsonify(total=query.count(), coverage="Changes recorded since the upgraded backend was installed; older meals remain available through history.",
            logs=[dict(id=r.id, entity=r.entity, record_id=r.record_id, action=r.action,
                timestamp=r.timestamp.isoformat() + "Z", snapshot=json.loads(r.snapshot))
                for r in query.order_by(ChangeLog.timestamp.desc(), ChangeLog.id.desc()).offset(offset).limit(limit)])
