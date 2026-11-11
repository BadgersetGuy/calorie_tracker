import base64
import copy
import io
import uuid
import unittest
from unittest.mock import patch, MagicMock
from PIL import Image

import test_mobile as support
from app import app, db, Meal
from openapi_spec_validator import validate_spec

def photo():
    buffer = io.BytesIO(); Image.new("RGB", (20, 20), "green").save(buffer, "JPEG")
    return buffer.getvalue()

class SharedAPITests(unittest.TestCase):
    setUp = support.MobileTests.setUp
    tearDown = support.MobileTests.tearDown
    post = support.MobileTests.post

    def data(self, **extra):
        result = support.result()
        # Imported scores must be ignored; the server must calculate its own.
        result["score"]["value"] = 999
        return dict(user_id=self.a.id, request_key=str(uuid.uuid4()),
            eaten_at="2026-11-09T19:00:00+02:00", timezone="Europe/Bucharest", analysis=result, **extra)

    def weight(self, person=None, kg=78):
        return self.post("/weights", dict(user_id=person or self.a.id, request_key=str(uuid.uuid4()),
            recorded_at="2026-11-09T08:00:00+02:00", weight_kg=kg, notes="Morning"))

    def test_import_chat_analysis_recalculates_score_without_model(self):
        data = self.data()
        with patch("analysis_engine.analyze") as provider:
            response = self.post("/meals", data)
            self.assertEqual(response.status_code, 201, response.json)
            provider.assert_not_called()
        record = response.json
        self.assertEqual(record["calories"], 130)
        self.assertEqual(record["analysis"]["score"]["value"], 75)
        self.assertEqual(record["analysis"]["model"], "client-supplied")
        self.assertEqual(record["discipline"]["value"], 8)
        again = self.post("/meals", data)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json["id"], record["id"])
        self.assertEqual(Meal.query.count(), 1)

    def test_manual_totals_do_not_invent_food_scores(self):
        data = dict(user_id=self.a.id, request_key=str(uuid.uuid4()), eaten_at="2026-11-09T12:00:00+02:00",
            timezone="Europe/Bucharest", description="Cappuccino", weight=250,
            totals=dict(calories=120, protein=6, carbs=10, fat=6))
        saved = self.post("/meals", data)
        self.assertEqual(saved.status_code, 201, saved.json)
        self.assertIsNone(saved.json["analysis"])
        changed = copy.deepcopy(data); changed["totals"]["calories"] = 130
        self.assertEqual(self.post("/meals", changed).status_code, 409)

    def test_multipart_photo_import_and_authenticated_retrieval(self):
        import json
        data = self.data()
        response = self.client.post("/api/v2/meals", data=dict(payload=json.dumps(data),
            meal_photo=(io.BytesIO(photo()), "meal.jpg")), content_type="multipart/form-data", headers=self.headers)
        self.assertEqual(response.status_code, 201, response.json)
        meal_id = response.json["id"]
        minimal = self.client.get(f"/api/v2/meals/{meal_id}", headers={"Authorization": "Bearer test-household"}).json
        self.assertTrue(minimal["has_photo"])
        self.assertIsNone(minimal["image_data"])
        photo_response = self.client.get(f"/api/v2/meals/{meal_id}/photo", headers=self.headers)
        self.assertEqual(photo_response.status_code, 200)
        self.assertEqual(photo_response.mimetype, "image/jpeg")
        self.assertEqual(self.client.get(f"/api/v2/meals/{meal_id}/photo").status_code, 401)

    def test_action_file_ref_download_is_bounded_and_without_bearer(self):
        data = self.data(openaiFileIdRefs=[dict(id="file-test", mime_type="image/jpeg",
            download_link="https://files.oaiusercontent.com/file-test?temporary=signature")])
        response = MagicMock()
        response.__enter__.return_value = response
        response.status_code = 200
        response.iter_content.return_value = [photo()]
        with patch("photo_inputs.requests.get", return_value=response) as download:
            saved = self.post("/meals", data)
            self.assertEqual(saved.status_code, 201, saved.json)
            self.assertTrue(saved.json["has_photo"])
            self.assertFalse(download.call_args.kwargs["allow_redirects"])
            self.assertNotIn("headers", download.call_args.kwargs)

    def test_attachment_rejects_untrusted_redirects_oversize_and_missing_refs(self):
        for link in ["http://files.oaiusercontent.com/file", "https://127.0.0.1/file", "https://files.oaiusercontent.com.evil.example/file"]:
            with patch("photo_inputs.requests.get") as get:
                self.assertEqual(self.post("/meals", self.data(openaiFileIdRefs=[dict(download_link=link)])).status_code, 400)
                get.assert_not_called()
        for status in [302, 403]:
            response = MagicMock(); response.__enter__.return_value = response; response.status_code = status
            with patch("photo_inputs.requests.get", return_value=response):
                self.assertEqual(self.post("/meals", self.data(openaiFileIdRefs=[dict(download_link="https://files.oaiusercontent.com/file")])).status_code, 400)
        with patch("photo_inputs.MAX_BYTES", 10):
            response = MagicMock(); response.__enter__.return_value = response; response.status_code = 200
            response.iter_content.return_value = [b"x" * 11]
            with patch("photo_inputs.requests.get", return_value=response):
                self.assertEqual(self.post("/meals", self.data(openaiFileIdRefs=[dict(download_link="https://files.oaiusercontent.com/file")])).status_code, 400)
        self.assertEqual(self.post("/meals", self.data(openaiFileIdRefs=["file-test"])).status_code, 400)

    def test_edit_requires_current_revision_and_clears_old_score_for_manual_totals(self):
        saved = self.post("/meals", self.data()).json
        updated_data = dict(revision=saved["revision"], description="Corrected oats", weight=200,
            totals=dict(calories=140, protein=6, carbs=18, fat=4))
        edited = self.client.patch(f"/api/v2/meals/{saved['id']}", json=updated_data, headers=self.headers)
        self.assertEqual(edited.status_code, 200, edited.json)
        self.assertEqual(edited.json["id"], saved["id"])
        self.assertEqual(edited.json["calories"], 140)
        self.assertIsNone(edited.json["analysis"])
        stale = self.client.patch(f"/api/v2/meals/{saved['id']}", json=updated_data, headers=self.headers)
        self.assertEqual(stale.status_code, 409)

    def test_weights_create_update_delete_and_stale_versions(self):
        first = self.weight()
        self.assertEqual(first.status_code, 201, first.json)
        record = first.json
        data = dict(revision=record["revision"], weight_kg=77.5, recorded_at=record["recorded_at"], notes="Correction")
        updated = self.client.put(f"/api/v2/weights/{record['id']}", json=data, headers=self.headers)
        self.assertEqual(updated.status_code, 200, updated.json)
        self.assertEqual(updated.json["weight_kg"], 77.5)
        self.assertEqual(self.client.put(f"/api/v2/weights/{record['id']}", json=data, headers=self.headers).status_code, 409)
        self.assertEqual(self.client.delete(f"/api/v2/weights/{record['id']}", json={"revision": updated.json["revision"]}, headers=self.headers).status_code, 200)

    def test_summary_totals_timing_weights_empty_days_and_profile_filter(self):
        self.post("/meals", self.data())
        self.weight()
        self.weight(self.b.id, 60)
        response = self.client.get(f"/api/v2/summaries?user_id={self.a.id}&start=2026-11-09&end=2026-11-10&timezone=Europe/Bucharest", headers={"Authorization": "Bearer test-household"})
        self.assertEqual(response.status_code, 200, response.json)
        first, empty = response.json["days"]
        self.assertEqual(first["totals"], dict(calories=130, protein=5.5, carbs=17, fat=4.5, fiber=2))
        self.assertEqual(first["discipline"]["value"], 8)
        self.assertEqual(first["body_weights"][0]["weight_kg"], 78)
        self.assertEqual(first["dietary_pattern"]["scored_meals"], 1)
        self.assertNotIn("image_data", first["meals"][0])
        self.assertEqual(empty["totals"]["calories"], 0)
        self.assertIsNone(empty["discipline"]["value"])
        self.assertIsNone(empty["dietary_pattern"]["value"])
        self.assertEqual(empty["body_weights"], [])

    def test_daily_and_period_score_averages_weight_meals_not_daily_averages(self):
        first = self.post("/meals", self.data()).json
        second_data = self.data()
        second_data["eaten_at"] = "2026-11-10T00:30:00+02:00"
        for item in second_data["analysis"]["ingredients"]:
            item["grams"] *= 3
            item["group"] = "neutral"
        second = self.post("/meals", second_data).json
        db.session.get(Meal, first["id"]).psoriasis_score = 8
        db.session.get(Meal, second["id"]).psoriasis_score = 2
        db.session.commit()
        self.post("/meals", dict(user_id=self.a.id, request_key=str(uuid.uuid4()),
            eaten_at="2026-11-10T12:00:00+02:00", timezone="Europe/Bucharest",
            description="Unscored meal", weight=100, totals=dict(calories=130, protein=5, carbs=10, fat=5)))
        other = self.data(); other["user_id"] = self.b.id
        self.post("/meals", other)
        response = self.client.get(f"/api/v2/summaries?user_id={self.a.id}&start=2026-11-09&end=2026-11-11&timezone=Europe/Bucharest", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        result = response.json
        self.assertEqual([day["dietary_pattern"]["value"] for day in result["days"]], [75, 50, None])
        self.assertEqual([day["legacy_psoriasis"]["value"] for day in result["days"]], [8, 2, None])
        self.assertEqual(result["score_averages"]["dietary_pattern"]["value"], 56.25)
        self.assertEqual(result["score_averages"]["legacy_psoriasis"]["value"], 3.5)
        self.assertEqual(result["score_averages"]["dietary_pattern"]["calorie_coverage_percent"], 80)
        self.assertEqual(result["score_averages"]["dietary_pattern"]["unscored_meals"], 1)
        self.assertNotIn("image_data", str(result))

    def test_weight_pagination_scope_and_change_log(self):
        saved = self.weight().json
        self.weight(self.b.id, 60)
        response = self.client.get(f"/api/v2/weights?user_id={self.a.id}&limit=1", headers=self.headers)
        self.assertEqual(response.json["total"], 1)
        self.assertEqual(response.json["weights"][0]["id"], saved["id"])
        logs = self.client.get(f"/api/v2/logs?user_id={self.a.id}", headers=self.headers).json
        self.assertTrue(any(r["entity"] == "body_weight" and r["record_id"] == saved["id"] for r in logs["logs"]))
        self.assertTrue(all(r["entity"] != "body_weight" or r["snapshot"]["weight_kg"] == 78 for r in logs["logs"]))

    def test_openapi_is_public_valid_and_covers_every_mobile_operation(self):
        spec = self.client.get("/openapi.json").json
        validate_spec(spec)
        ids = []
        for path in spec["paths"].values():
            ids.extend(op["operationId"] for op in path.values())
        self.assertEqual(len(ids), len(set(ids)))
        operations = sum(len(r.methods - {"HEAD", "OPTIONS"}) for r in app.url_map.iter_rules() if r.rule.startswith("/api/v2/"))
        self.assertEqual(len(ids), operations)
        self.assertIn("/api/v2/summaries", spec["paths"])
        self.assertIn("/api/v2/weights", spec["paths"])

    def test_new_routes_remain_authenticated(self):
        for path in ["/api/v2/summaries?user_id=1", "/api/v2/weights?user_id=1", "/api/v2/logs?user_id=1", "/api/v2/analyses?user_id=1"]:
            self.assertEqual(self.client.get(path).status_code, 401)

    def test_previous_chat_analysis_is_kept_in_change_log(self):
        saved = self.post("/meals", self.data()).json
        replacement = dict(revision=saved["revision"], description="Corrected meal", weight=200,
            totals=dict(calories=140, protein=6, carbs=18, fat=4))
        changed = self.client.patch(f"/api/v2/meals/{saved['id']}", json=replacement, headers=self.headers)
        self.assertEqual(changed.status_code, 200)
        logs = self.client.get(f"/api/v2/logs?user_id={self.a.id}", headers=self.headers).json["logs"]
        replaced = next(r for r in logs if r["action"] == "analysis_replaced")
        self.assertEqual(replaced["snapshot"]["before"]["analysis"]["score"]["value"], 75)
        self.assertNotIn("image_data", replaced["snapshot"]["before"])

    def test_deleted_meal_analysis_is_archived_without_photo_bytes(self):
        saved = self.post("/meals", self.data(image_data=base64.b64encode(photo()).decode())).json
        deleted = self.client.delete(f"/api/v2/meals/{saved['id']}", headers=self.headers)
        self.assertEqual(deleted.status_code, 200)
        logs = self.client.get(f"/api/v2/logs?user_id={self.a.id}", headers=self.headers).json["logs"]
        archived = next(r for r in logs if r["action"] == "archived")
        self.assertEqual(archived["snapshot"]["analysis"]["model"], "client-supplied")
        self.assertNotIn("image_data", archived["snapshot"])

    def test_early_meals_do_not_dilute_discipline_penalty(self):
        for timestamp in ("2026-11-09T09:00:00+02:00", "2026-11-09T20:00:00+02:00"):
            data = self.data(); data["eaten_at"] = timestamp
            self.assertEqual(self.post("/meals", data).status_code, 201)
        result = self.client.get(f"/api/v2/summaries?user_id={self.a.id}&date=2026-11-09&timezone=Europe/Bucharest", headers=self.headers).json
        self.assertEqual(result["days"][0]["discipline"]["value"], 6)
