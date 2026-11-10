import base64
import copy
import io
import os
import tempfile
import unittest
import uuid
from datetime import datetime
from unittest.mock import patch

directory = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = "sqlite:///" + directory.name + "/test.db"
os.environ["MOBILE_API_TOKEN"] = "test-household"
from app import app, db, User, Meal
import analysis_engine as engine
from PIL import Image


def result():
    return engine.calculate(dict(status="ready", description="Oats and milk", questions=[],
        assumptions=["Prepared weight"], confidence="medium", ingredients=[
            dict(name="Cooked oats", grams=100, group="whole_grains", tags=[], source_note="Generic estimate",
                 per_100g=dict(calories=70, protein=2.5, carbs=12, fat=1.5, fiber=2)),
            dict(name="Milk", grams=100, group="neutral", tags=["dairy"], source_note="Generic estimate",
                 per_100g=dict(calories=60, protein=3, carbs=5, fat=3, fiber=0))]))


class MobileTests(unittest.TestCase):
    def setUp(self):
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.a = User(username="Me"); self.b = User(username="Wife")
        db.session.add_all([self.a, self.b]); db.session.commit()
        self.client = app.test_client()
        self.headers = {"Authorization": "Bearer test-household", "X-Meal-Client": "android"}

    def tearDown(self):
        db.session.remove(); self.ctx.pop()

    def post(self, path, data):
        return self.client.post("/api/v2" + path, json=data, headers=self.headers)

    def start(self, extra=None):
        with patch("analysis_engine.analyze", return_value=result()):
            response = self.post("/analyses", dict(user_id=self.a.id, text="200 g oats and milk", **(extra or {})))
        self.assertEqual(response.status_code, 201, response.json)
        return response.json

    def save(self, draft, **extra):
        return self.post(f"/analyses/{draft['id']}/save", dict(revision=draft["revision"], date="2026-11-09T12:00:00+02:00", **extra))

    def test_auth_covers_new_and_legacy_routes(self):
        for path in ["/api/v2/profiles", "/users", "/meals?user_id=1"]:
            self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_unconfigured_api_fails_closed(self):
        with patch.dict(os.environ, {"MOBILE_API_TOKEN": ""}):
            self.assertEqual(self.client.get("/api/v2/profiles").status_code, 503)

    def test_existing_user_targets_are_shared_with_android(self):
        self.a.target_calories = 2400
        self.a.target_protein = 150
        db.session.commit()
        profiles = self.client.get("/api/v2/profiles", headers=self.headers).json
        profile = next(p for p in profiles if p["id"] == self.a.id)
        self.assertEqual(profile["targets"]["calories"], 2400)
        values = dict(calories=1800, protein=100, carbs=200, fat=60)
        response = self.client.put(f"/api/v2/profiles/{self.a.id}/targets", json=values, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        legacy = self.client.get(f"/users/{self.a.id}/targets", headers=self.headers).json
        self.assertEqual(legacy["target_calories"], 1800)
        self.client.put(f"/users/{self.a.id}/targets", json={"target_calories": 2100}, headers=self.headers)
        updated = self.client.get("/api/v2/profiles", headers=self.headers).json
        self.assertEqual(next(p for p in updated if p["id"] == self.a.id)["targets"]["calories"], 2100)

    def test_historical_score_survives_copy_and_reanalysis(self):
        image = io.BytesIO(); Image.new("RGB", (20, 20), "green").save(image, "JPEG")
        original_photo = base64.b64encode(image.getvalue()).decode()
        original = Meal(user_id=self.a.id, date=datetime(2025, 5, 6, 12), weight=200,
            description="Old oats", calories=130, protein=5.5, carbs=17, fat=4.5,
            psoriasis_score=8.2, image_data=original_photo)
        db.session.add(original); db.session.commit()
        copied = self.post(f"/meals/{original.id}/copy", dict(user_id=self.b.id, portion_percent=70,
            date="2026-11-09T12:00:00Z", request_key=str(uuid.uuid4())))
        self.assertEqual(copied.status_code, 201)
        self.assertEqual(copied.json["legacy_psoriasis_score"], 8.2)
        self.assertIsNone(copied.json["analysis"])
        with patch("analysis_engine.analyze", return_value=result()):
            draft = self.post("/analyses", dict(user_id=self.a.id, source_meal_id=original.id, text="Correct oats")).json
        revised = self.save(draft, replace_meal_id=original.id)
        self.assertEqual(revised.json["legacy_psoriasis_score"], 8.2)
        self.assertEqual(revised.json["analysis"]["score"]["value"], 75)
        self.assertEqual(revised.json["image_data"], original_photo)
        self.assertEqual(revised.json["date"], "2025-05-06T12:00:00Z")

    def test_legacy_delete_removes_mobile_metadata(self):
        saved = self.save(self.start()).json
        response = self.client.delete(f"/delete_meal/{saved['id']}?user_id={self.a.id}", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(db.session.execute(db.text('SELECT COUNT(*) FROM mobile_meal_details')).scalar(), 0)

    def test_http_errors_keep_their_status(self):
        self.assertEqual(self.client.get("/not-a-route", headers=self.headers).status_code, 404)

    def test_legacy_score_average_does_not_treat_unscored_meals_as_zero(self):
        for score in (8.0, None):
            db.session.add(Meal(user_id=self.a.id, date=datetime(2026, 11, 9, 12), weight=200,
                description="Meal", calories=100, protein=5, carbs=15, fat=2, psoriasis_score=score))
        db.session.commit()
        response = self.client.get(f"/meal_history?user_id={self.a.id}&start=2026-11-09&end=2026-11-09", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["psoriasis_scores"], [8.0])

    def test_text_only_analysis_save_and_retry(self):
        draft = self.start()
        first = self.save(draft); second = self.save(draft)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json["id"], second.json["id"])
        self.assertEqual(Meal.query.count(), 1)
        self.assertEqual(first.json["date"], "2026-11-09T10:00:00Z")

    def test_clarify_then_reanalyse_with_history(self):
        question = dict(status="clarify", description="Drink", questions=["Which milk?"], assumptions=[], confidence="low", ingredients=[])
        with patch("analysis_engine.analyze", return_value=question):
            draft = self.post("/analyses", dict(user_id=self.a.id, text="250ml cappuccino")).json
        self.assertEqual(self.save(draft).status_code, 400)
        with patch("analysis_engine.analyze", return_value=result()) as provider:
            updated = self.post(f"/analyses/{draft['id']}/clarifications", dict(revision=1, text="Whole milk, no sugar"))
            self.assertEqual(updated.status_code, 200, updated.json)
            context = provider.call_args.args[0]
            self.assertEqual(context["conversation"][0]["answer"], "Whole milk, no sugar")
        self.assertEqual(self.save(draft).status_code, 409)
        self.assertEqual(self.save(updated.json).status_code, 201)

    def test_identical_input_is_cached(self):
        self.start()
        with patch("analysis_engine.analyze") as provider:
            self.start()
            provider.assert_not_called()

    def test_copy_to_self_or_wife_scales_without_model(self):
        saved = self.save(self.start()).json
        for profile in [self.a, self.b]:
            with patch("analysis_engine.analyze") as provider:
                data = dict(user_id=profile.id, portion_percent=70, date="2026-11-10T09:00:00+02:00", request_key=str(uuid.uuid4()))
                copied = self.post(f"/meals/{saved['id']}/copy", data)
                self.assertEqual(copied.status_code, 201, copied.json)
                self.assertAlmostEqual(copied.json["calories"], saved["calories"] * .7)
                self.assertAlmostEqual(copied.json["weight"], 140)
                self.assertEqual(copied.json["analysis"]["score"], saved["analysis"]["score"])
                retried = self.post(f"/meals/{saved['id']}/copy", data)
                self.assertEqual(retried.json["id"], copied.json["id"])
                provider.assert_not_called()
        self.assertEqual(Meal.query.count(), 3)

    def test_weight_copy_and_conflicting_retry(self):
        saved = self.save(self.start()).json
        data = dict(user_id=self.b.id, weight=50, date="2026-11-10T09:00:00Z", request_key=str(uuid.uuid4()))
        copied = self.post(f"/meals/{saved['id']}/copy", data)
        self.assertEqual(copied.json["weight"], 50)
        data["weight"] = 100
        self.assertEqual(self.post(f"/meals/{saved['id']}/copy", data).status_code, 409)

    def test_old_meal_can_be_reused_without_ingredients(self):
        old = Meal(user_id=self.a.id, weight=400, description="Old meal", calories=600, protein=30, carbs=70, fat=20)
        db.session.add(old); db.session.commit()
        response = self.post(f"/meals/{old.id}/copy", dict(user_id=self.b.id, portion_percent=70,
            date="2026-11-09T12:00:00Z", request_key=str(uuid.uuid4())))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["calories"], 420)
        self.assertIsNone(response.json["analysis"])
        self.assertEqual(db.session.get(Meal, old.id).calories, 600)

    def test_edit_existing_meal_preserves_id_date_and_count(self):
        saved = self.save(self.start()).json
        revised = result(); revised["description"] = "Corrected oats"
        with patch("analysis_engine.analyze", return_value=revised):
            draft = self.post("/analyses", dict(user_id=self.a.id, source_meal_id=saved["id"], text="Actually oats")).json
        edited = self.save(draft, replace_meal_id=saved["id"])
        self.assertEqual(edited.status_code, 201, edited.json)
        self.assertEqual(edited.json["id"], saved["id"])
        self.assertEqual(edited.json["date"], saved["date"])
        self.assertEqual(Meal.query.count(), 1)

    def test_cannot_replace_other_profiles_meal(self):
        saved = self.save(self.start()).json
        with patch("analysis_engine.analyze", return_value=result()):
            draft = self.post("/analyses", dict(user_id=self.b.id, source_meal_id=saved["id"], text="Copy estimate")).json
        self.assertEqual(self.save(draft, replace_meal_id=saved["id"]).status_code, 400)

    def test_edit_refuses_a_meal_changed_on_other_phone(self):
        saved = self.save(self.start()).json
        with patch("analysis_engine.analyze", return_value=result()):
            draft = self.post("/analyses", dict(user_id=self.a.id, source_meal_id=saved["id"], text="Correcting meal")).json
        record = db.session.get(Meal, saved["id"])
        record.calories = 999
        db.session.commit()
        self.assertEqual(self.save(draft, replace_meal_id=saved["id"]).status_code, 409)
        self.assertEqual(db.session.get(Meal, saved["id"]).calories, 999)

    def test_local_day_includes_utc_previous_evening(self):
        draft = self.start()
        self.post(f"/analyses/{draft['id']}/save", dict(revision=1, date="2026-11-09T00:30:00+02:00"))
        rows = self.client.get(f"/api/v2/meals?user_id={self.a.id}&date=2026-11-09&offset_minutes=120", headers=self.headers)
        self.assertEqual(len(rows.json), 1)
        rows = self.client.get(f"/api/v2/meals?user_id={self.a.id}&date=2026-11-08&offset_minutes=120", headers=self.headers)
        self.assertEqual(len(rows.json), 0)

    def test_history_search_is_profile_scoped_and_paginated(self):
        for i in range(35):
            db.session.add(Meal(user_id=self.a.id, weight=100, description="Oats breakfast", calories=200, protein=10, carbs=30, fat=5))
        db.session.add(Meal(user_id=self.b.id, weight=100, description="Oats for wife", calories=200, protein=10, carbs=30, fat=5))
        db.session.commit()
        response = self.client.get(f"/api/v2/history?user_id={self.a.id}&query=Oats", headers=self.headers)
        self.assertEqual(response.json["total"], 35)
        self.assertEqual(len(response.json["meals"]), 30)
        next_page = self.client.get(f"/api/v2/history?user_id={self.a.id}&query=Oats&offset=30", headers=self.headers)
        self.assertEqual(len(next_page.json["meals"]), 5)
        self.assertFalse({m["id"] for m in response.json["meals"]} & {m["id"] for m in next_page.json["meals"]})
        escaped = self.client.get(f"/api/v2/history?user_id={self.a.id}&query=%25", headers=self.headers)
        self.assertEqual(escaped.json["total"], 0)

    def test_bad_inputs_do_not_write_meals(self):
        self.assertEqual(self.post("/analyses", dict(user_id=self.a.id)).status_code, 400)
        self.assertEqual(self.post("/analyses", dict(user_id=999, text="food")).status_code, 400)
        self.assertEqual(self.post("/analyses", dict(user_id=self.a.id, text="food", weight=-1)).status_code, 400)
        self.assertEqual(self.post("/analyses", dict(user_id=self.a.id, text="food", image_data="not base64")).status_code, 400)
        self.assertEqual(Meal.query.count(), 0)

    def test_delete_cleans_details(self):
        saved = self.save(self.start()).json
        response = self.client.delete(f"/api/v2/meals/{saved['id']}", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Meal.query.count(), 0)


class CalculationTests(unittest.TestCase):
    def test_score_is_fixed_and_portion_invariant(self):
        original = result()
        self.assertEqual(original["score"]["value"], 75)
        for item in original["ingredients"]:
            item["grams"] *= .7
        scaled = engine.calculate(original)
        self.assertEqual(scaled["score"]["value"], 75)
        self.assertEqual(scaled["totals"]["calories"], 91)

    def test_invalid_nutrients_rejected(self):
        for value in [-1, float("nan"), float("inf"), True]:
            with self.assertRaises(ValueError):
                engine.positive(value, "calories")
        data = result()
        data["ingredients"][0]["per_100g"]["calories"] = 900
        with self.assertRaises(ValueError): engine.calculate(data)

    def test_photo_transcoded_and_metadata_removed(self):
        buffer = io.BytesIO(); Image.new("RGB", (1800, 900)).save(buffer, "PNG")
        normalized = engine.normalize_photo(base64.b64encode(buffer.getvalue()).decode())
        photo = Image.open(io.BytesIO(base64.b64decode(normalized)))
        self.assertEqual(photo.format, "JPEG"); self.assertEqual(photo.size, (1280, 640))

    def test_provider_receives_photo_and_schema_and_no_storage(self):
        payload = result()
        for key in ["totals", "score", "tags", "weight"]: payload.pop(key)
        import json
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), patch("requests.post") as post:
            post.return_value.ok = True
            post.return_value.json.return_value = dict(status="completed", output=[dict(type="message", content=[dict(type="output_text", text=json.dumps(payload))])])
            output = engine.analyze(dict(text="Oats", weight=200), "test-photo")
            self.assertEqual(output["totals"]["calories"], 130)
            sent = post.call_args.kwargs["json"]
            self.assertFalse(sent["store"])
            self.assertTrue(sent["text"]["format"]["strict"])
            self.assertEqual(sent["input"][0]["content"][1]["type"], "input_image")


if __name__ == "__main__": unittest.main()
