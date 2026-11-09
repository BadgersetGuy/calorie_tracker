"""Integration checks against independently created pre-upgrade SQLite schemas."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class ExistingDatabaseTests(unittest.TestCase):
    def check_schema(self, newer):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.db"
            target_columns = ", target_calories FLOAT, target_protein FLOAT, target_carbs FLOAT, target_fat FLOAT" if newer else ""
            score_column = ", psoriasis_score FLOAT" if newer else ""
            connection = sqlite3.connect(path)
            connection.executescript(f'''
                CREATE TABLE user (id INTEGER PRIMARY KEY, username VARCHAR(80) UNIQUE NOT NULL,
                    created_at DATETIME NOT NULL {target_columns});
                CREATE TABLE meal (id INTEGER PRIMARY KEY, date DATETIME NOT NULL, weight FLOAT NOT NULL,
                    description TEXT, calories FLOAT NOT NULL, protein FLOAT NOT NULL, carbs FLOAT NOT NULL,
                    fat FLOAT NOT NULL, image_data TEXT, user_id INTEGER NOT NULL {score_column});
                INSERT INTO user (id,username,created_at) VALUES(7,'Existing profile','2025-01-02 03:04:00.000000');
                INSERT INTO meal (id,date,weight,description,calories,protein,carbs,fat,image_data,user_id)
                    VALUES(42,'2025-04-05 12:30:00.000000',400,'Original dish',600,30,70,20,'existing-image',7);
            ''')
            if newer:
                connection.execute('UPDATE user SET target_calories=2200, target_protein=120 WHERE id=7')
                connection.execute('UPDATE meal SET psoriasis_score=7.5 WHERE id=42')
            connection.commit()
            before_user = connection.execute('SELECT * FROM user').fetchall()
            before_meal = connection.execute('SELECT * FROM meal').fetchall()
            original_sql = connection.execute("SELECT name,sql FROM sqlite_master WHERE name IN ('user','meal') ORDER BY name").fetchall()
            connection.close()
            code = '''
from app import app, db
from sqlalchemy import inspect
if NEED_UPGRADE:
    runner = app.test_cli_runner()
    first = runner.invoke(args=['upgrade-legacy-schema'])
    assert first.exit_code == 0, first.output
    second = runner.invoke(args=['upgrade-legacy-schema'])
    assert second.exit_code == 0, second.output
client=app.test_client()
headers={'Authorization':'Bearer compatibility-test'}
profiles=client.get('/api/v2/profiles',headers=headers)
assert profiles.status_code==200, profiles.json
meal=client.get('/api/v2/meals/42?include_images=true',headers=headers)
assert meal.status_code==200,meal.json
assert meal.json['image_data']=='existing-image'
assert meal.json['calories']==600
assert meal.json['date']=='2025-04-05T12:30:00Z'
assert meal.json['analysis'] is None
assert meal.json['legacy_psoriasis_score']==EXPECTED_SCORE
if not NEED_UPGRADE:
    assert profiles.json[0]['targets']['calories']==2200
'''.replace('NEED_UPGRADE', repr(not newer)).replace('EXPECTED_SCORE', repr(7.5 if newer else None))
            environment = dict(os.environ, DATABASE_URL="sqlite:///" + str(path), MOBILE_API_TOKEN="compatibility-test")
            process = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=environment,
                capture_output=True, text=True, timeout=20)
            self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
            connection = sqlite3.connect(path)
            after_user = connection.execute('SELECT * FROM user').fetchall()
            after_meal = connection.execute('SELECT * FROM meal').fetchall()
            if newer:
                self.assertEqual(original_sql, connection.execute("SELECT name,sql FROM sqlite_master WHERE name IN ('user','meal') ORDER BY name").fetchall())
                self.assertEqual(before_user, after_user)
                self.assertEqual(before_meal, after_meal)
            else:
                self.assertEqual(before_user[0], after_user[0][:len(before_user[0])])
                self.assertEqual(before_meal[0], after_meal[0][:len(before_meal[0])])
            connection.close()

    def test_uploaded_schema_starts_without_changing_existing_rows_or_columns(self):
        self.check_schema(newer=True)

    def test_old_repository_schema_upgrade_is_additive_and_idempotent(self):
        self.check_schema(newer=False)
