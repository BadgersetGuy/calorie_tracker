import unittest
import uuid
from datetime import datetime
from unittest.mock import patch

import test_mobile as support
from app import db, Meal
import meal_timing
import meal_suggestions as suggestions

class TimingTests(unittest.TestCase):
    def test_cutoff_and_half_hour_steps(self):
        for stamp, expected in [("17:59:59", 10), ("18:00:00", 10), ("18:00:01", 9),
                ("18:30:00", 9), ("18:30:01", 8), ("19:00:00", 8),
                ("20:00:00", 6), ("23:00:00", 0), ("23:59:59", 0), ("00:00:00", 10)]:
            local = meal_timing.confirmed_time("2026-11-09T" + stamp + "+02:00", "Europe/Bucharest")
            self.assertEqual(meal_timing.score(local)["value"], expected)

    def test_timezone_offset_is_validated(self):
        with self.assertRaises(ValueError): meal_timing.confirmed_time("2026-11-09T19:00:00+00:00", "Europe/Bucharest")
        with self.assertRaises(ValueError): meal_timing.zone("Not/AZone")
        with self.assertRaises(ValueError): meal_timing.confirmed_time("2026-11-09T19:00:00")

    def test_summer_and_winter_both_use_local_six(self):
        for stamp in ["2026-07-09T18:00:00+03:00", "2026-11-09T18:00:00+02:00"]:
            self.assertEqual(meal_timing.score(meal_timing.confirmed_time(stamp, "Europe/Bucharest"))["value"], 10)

class SuggestionTests(unittest.TestCase):
    def test_familiarity_counts_once_per_meal_and_understands_romanian(self):
        history = [dict(description="Somon cu spanac. Somon", ingredients=["salmon"])] * 3
        result = suggestions.suggest(history, set(), {}, [])
        counts = {p["ingredient"]: p["meals"] for p in result["preferences"]}
        self.assertEqual(counts["salmon"], 3)
        self.assertEqual(counts["spinach"], 3)

    def test_rotation_and_constraints_are_strict(self):
        first = suggestions.suggest([], set(), {}, [])
        ids = {r["id"] for r in first["ideas"]}
        second = suggestions.suggest([], ids, {}, [], 1)
        self.assertFalse(ids & {r["id"] for r in second["ideas"]})
        constrained = suggestions.suggest([], set(), {}, ["fish", "nuts", "milk", "gluten"])
        self.assertTrue(constrained["ideas"])
        for item in constrained["ideas"]:
            self.assertFalse(set(item["tags"]) & {"fish", "nuts", "dairy", "gluten"})

    def test_skip_and_exhaustion_do_not_relax_exclusions(self):
        feedback = {item["id"]: "skip" for item in suggestions.RECIPES}
        result = suggestions.suggest([], set(), feedback, [])
        self.assertEqual(result["ideas"], [])
        self.assertTrue(result["empty_reason"])

    def test_seeded_results_are_reproducible_and_varied(self):
        first = suggestions.suggest([], set(), {}, [])
        self.assertEqual(first, suggestions.suggest([], set(), {}, []))
        self.assertEqual(len({idea["group"] for idea in first["ideas"]}), 3)

class FeatureAPITests(unittest.TestCase):
    setUp = support.MobileTests.setUp
    tearDown = support.MobileTests.tearDown
    post = support.MobileTests.post
    start = support.MobileTests.start
    save = support.MobileTests.save

    def ideas(self, person=None, avoid=None, key=None):
        response = self.post("/suggestions", dict(user_id=person or self.a.id, avoid=avoid or [], request_key=key or str(uuid.uuid4())))
        self.assertEqual(response.status_code, 201, response.json)
        return response.json

    def test_score_uses_eating_time_not_analysis_time(self):
        draft = self.start()
        response = self.post(f"/analyses/{draft['id']}/save", dict(revision=1,
            eaten_at="2026-11-09T20:00:00+02:00", timezone="Europe/Bucharest"))
        self.assertEqual(response.status_code, 201, response.json)
        self.assertEqual(response.json["discipline"]["value"], 6)
        self.assertFalse(response.json["discipline"]["inferred"])
        self.assertEqual(response.json["date"], "2026-11-09T18:00:00Z")

    def test_copy_recalculates_timing_without_modifying_original(self):
        draft = self.start()
        original = self.post(f"/analyses/{draft['id']}/save", dict(revision=1, eaten_at="2026-11-09T20:00:00+02:00", timezone="Europe/Bucharest")).json
        copied = self.post(f"/meals/{original['id']}/copy", dict(user_id=self.b.id, portion_percent=70,
            eaten_at="2026-11-10T12:00:00+02:00", timezone="Europe/Bucharest", request_key=str(uuid.uuid4())))
        self.assertEqual(copied.status_code, 201, copied.json)
        self.assertEqual(copied.json["discipline"]["value"], 10)
        self.assertEqual(copied.json["analysis"]["score"], original["analysis"]["score"])
        original_again = self.client.get(f"/api/v2/meals/{original['id']}", headers=self.headers).json
        self.assertEqual(original_again["discipline"]["value"], 6)

    def test_reanalysis_can_correct_time_and_missing_explicit_time_preserves_it(self):
        original = self.save(self.start()).json
        with patch("analysis_engine.analyze", return_value=support.result()):
            draft = self.post("/analyses", dict(user_id=self.a.id, source_meal_id=original["id"], text="Same oats, later time")).json
        response = self.post(f"/analyses/{draft['id']}/save", dict(revision=1, replace_meal_id=original["id"],
            eaten_at="2026-11-09T19:00:00+02:00", timezone="Europe/Bucharest"))
        self.assertEqual(response.status_code, 201, response.json)
        self.assertEqual(response.json["discipline"]["value"], 8)

    def test_older_meals_are_marked_inferred(self):
        record = Meal(user_id=self.a.id, date=datetime(2025, 11, 9, 18), description="Old meal", weight=200,
            calories=100, protein=3, carbs=12, fat=4)
        db.session.add(record); db.session.commit()
        response = self.client.get(f"/api/v2/meals/{record.id}", headers=self.headers).json
        self.assertTrue(response["discipline"]["inferred"])
        self.assertEqual(response["discipline"]["value"], 6)

    def test_suggestions_rotate_last_two_batches_and_retry_is_idempotent(self):
        first = self.ideas(); second = self.ideas(); third = self.ideas()
        prior = {idea["id"] for batch in [first, second] for idea in batch["ideas"]}
        self.assertFalse(prior & {i["id"] for i in third["ideas"]})
        retried = self.post("/suggestions", dict(user_id=self.a.id, avoid=[], request_key=third["id"]))
        self.assertEqual(retried.status_code, 200)
        self.assertEqual(retried.json, third)

    def test_preferences_and_feedback_are_profile_scoped(self):
        for _ in range(3):
            db.session.add(Meal(user_id=self.a.id, description="Salmon with spinach", weight=200,
                calories=100, protein=3, carbs=12, fat=4))
        db.session.commit()
        mine = self.ideas(); wife = self.ideas(self.b.id)
        self.assertTrue(mine["preferences"])
        self.assertEqual(wife["preferences"], [])
        recipe = mine["ideas"][0]["id"]
        self.client.put(f"/api/v2/suggestions/{recipe}/feedback", json=dict(user_id=self.a.id, action="skip"), headers=self.headers)
        latest = self.client.get(f"/api/v2/suggestions?user_id={self.a.id}", headers=self.headers).json
        self.assertNotIn(recipe, {i["id"] for i in latest["ideas"]})
        next_batch = self.ideas()
        self.assertNotIn(recipe, {i["id"] for i in next_batch["ideas"]})
        wife_again = self.client.get(f"/api/v2/suggestions?user_id={self.b.id}", headers=self.headers).json
        self.assertTrue(all(i.get("feedback") is None for i in wife_again["ideas"]))

    def test_suggestions_work_without_model_access_and_do_not_log_meals(self):
        with patch("analysis_engine.analyze") as provider:
            result = self.ideas(avoid=["fish", "nuts"])
            self.assertTrue(result["ideas"])
            provider.assert_not_called()
        self.assertEqual(Meal.query.count(), 0)

    def test_invalid_timezone_and_conflicting_suggestion_key_are_rejected(self):
        draft = self.start()
        bad = self.post(f"/analyses/{draft['id']}/save", dict(revision=1, eaten_at="2026-11-09T19:00:00Z", timezone="Europe/Bucharest"))
        self.assertEqual(bad.status_code, 400)
        first = self.ideas()
        conflict = self.post("/suggestions", dict(user_id=self.b.id, request_key=first["id"], avoid=[]))
        self.assertEqual(conflict.status_code, 409)

    def test_feedback_reset_does_not_change_other_profile(self):
        recipe = suggestions.RECIPES[0]["id"]
        for profile in (self.a, self.b):
            response = self.client.put(f"/api/v2/suggestions/{recipe}/feedback", json=dict(user_id=profile.id, action="skip"), headers=self.headers)
            self.assertEqual(response.status_code, 200)
        response = self.client.delete("/api/v2/suggestions/feedback", json=dict(user_id=self.a.id), headers=self.headers)
        self.assertEqual(response.status_code, 200)
        rows = db.session.execute(db.text('SELECT user_id FROM mobile_suggestion_feedback')).all()
        self.assertEqual([row[0] for row in rows], [self.b.id])

    def test_new_meals_mark_suggestions_for_refresh(self):
        self.ideas()
        before = self.client.get(f"/api/v2/suggestions?user_id={self.a.id}", headers=self.headers).json
        self.assertFalse(before["needs_refresh"])
        db.session.add(Meal(user_id=self.a.id, description="New meal", weight=200, calories=100, protein=3, carbs=12, fat=4))
        db.session.commit()
        after = self.client.get(f"/api/v2/suggestions?user_id={self.a.id}", headers=self.headers).json
        self.assertTrue(after["needs_refresh"])
