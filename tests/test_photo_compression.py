import base64
from functools import lru_cache
import io
import unittest
from unittest.mock import patch
from PIL import Image

import test_mobile as support
from app import db, Meal
import analysis_engine as engine
from photo_maintenance import compress_existing_photos

@lru_cache(maxsize=1)
def large_photo():
    image = Image.effect_noise((2400, 1800), 100).convert("RGB")
    buffer = io.BytesIO(); image.save(buffer, "JPEG", quality=98)
    return base64.b64encode(buffer.getvalue()).decode()

class CompressionTests(unittest.TestCase):
    def test_large_detailed_photo_is_bounded_and_smaller(self):
        original = large_photo()
        normalized = engine.normalize_photo(original)
        raw = base64.b64decode(normalized)
        self.assertLessEqual(len(raw), 200 * 1024)
        self.assertLess(len(normalized), len(original) / 4)
        photo = Image.open(io.BytesIO(raw))
        self.assertEqual(photo.format, "JPEG")
        self.assertLessEqual(max(photo.size), 1280)

    def test_repeated_compression_does_not_degrade_canonical_photos(self):
        normalized = engine.normalize_photo(large_photo())
        self.assertEqual(engine.normalize_photo(normalized), normalized)

    def test_small_jpeg_metadata_removed_and_orientation_preserved(self):
        photo = Image.new("RGB", (40, 20), "red")
        exif = Image.Exif(); exif[274] = 6; exif[270] = "Private camera metadata"
        buffer = io.BytesIO(); photo.save(buffer, "JPEG", exif=exif)
        normalized = engine.normalize_photo(base64.b64encode(buffer.getvalue()).decode())
        output = Image.open(io.BytesIO(base64.b64decode(normalized)))
        self.assertEqual(output.size, (20, 40))
        self.assertFalse(output.getexif())
        self.assertNotIn("exif", output.info)

    def test_full_resolution_mobile_jpeg_uses_decoder_downsampling(self):
        photo = Image.new("RGB", (8000, 6000), "green")
        buffer = io.BytesIO(); photo.save(buffer, "JPEG"); photo.close()
        output = engine.normalize_photo(base64.b64encode(buffer.getvalue()).decode())
        photo = Image.open(io.BytesIO(base64.b64decode(output)))
        self.assertLessEqual(max(photo.size), 1280)
        self.assertLessEqual(len(base64.b64decode(output)), 200 * 1024)

class CompressionAPITests(unittest.TestCase):
    setUp = support.MobileTests.setUp
    tearDown = support.MobileTests.tearDown
    post = support.MobileTests.post

    def test_saving_a_pre_upgrade_draft_compresses_its_old_photo(self):
        with patch("analysis_engine.analyze", return_value=support.result()):
            draft = self.post("/analyses", dict(user_id=self.a.id, text="Oats and milk")).json
        table = db.metadata.tables["mobile_analysis_draft"]
        db.session.execute(db.update(table).where(table.c.id == draft["id"]).values(photo=large_photo()))
        db.session.commit()
        saved = self.post(f"/analyses/{draft['id']}/save", dict(revision=1, date="2026-11-09T12:00:00Z"))
        self.assertEqual(saved.status_code, 201, saved.json)
        self.assertLessEqual(len(base64.b64decode(saved.json["image_data"])), 200 * 1024)

    def test_legacy_upload_and_save_share_compression_policy(self):
        with patch("app.analyze_image_with_openai", return_value='{}') as analyze:
            response = self.client.post("/upload", data=dict(weight="200", meal_photo=(io.BytesIO(base64.b64decode(large_photo())), "meal.jpg")), headers=self.headers)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertLessEqual(len(base64.b64decode(analyze.call_args.args[0])), 200 * 1024)
        values = dict(user_id=self.a.id, weight=200, description="Meal", calories=300, protein=20, carbs=30, fat=10,
            image_data=large_photo())
        saved = self.client.post("/save_meal", json=values, headers=self.headers)
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertLessEqual(len(base64.b64decode(Meal.query.one().image_data)), 200 * 1024)

    def test_copy_compresses_old_photo_without_rewriting_original(self):
        import uuid
        original = Meal(user_id=self.a.id, weight=200, description="Old meal", calories=300,
            protein=20, carbs=30, fat=10, psoriasis_score=8, image_data=large_photo())
        db.session.add(original); db.session.commit()
        copied = self.post(f"/meals/{original.id}/copy", dict(user_id=self.b.id, portion_percent=70,
            date="2026-11-09T12:00:00Z", request_key=str(uuid.uuid4())))
        self.assertEqual(copied.status_code, 201, copied.json)
        self.assertLessEqual(len(base64.b64decode(copied.json["image_data"])), 200 * 1024)
        self.assertEqual(db.session.get(Meal, original.id).image_data, large_photo())

    def test_maintenance_dry_run_and_apply_preserve_nutrition_and_scores(self):
        original = Meal(user_id=self.a.id, weight=200, description="Old meal", calories=300,
            protein=20, carbs=30, fat=10, psoriasis_score=8, image_data=large_photo())
        db.session.add(original); db.session.commit()
        dry = compress_existing_photos(db)
        self.assertEqual(dry["updated"], 0)
        self.assertGreater(dry["candidate_bytes_saved"], 0)
        self.assertEqual(db.session.get(Meal, original.id).image_data, large_photo())
        applied = compress_existing_photos(db, apply=True)
        self.assertEqual(applied["updated"], 1)
        db.session.expire_all()
        record = db.session.get(Meal, original.id)
        self.assertEqual((record.calories, record.protein, record.weight, record.psoriasis_score), (300, 20, 200, 8))
        self.assertLessEqual(len(base64.b64decode(record.image_data)), 200 * 1024)
        self.assertEqual(compress_existing_photos(db, apply=True)["updated"], 0)
