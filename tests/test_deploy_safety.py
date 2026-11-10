import copy
import hashlib
import gzip
import json
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import deploy_fly, fly_sqlite_guard as guard


class DeploymentSafetyTests(unittest.TestCase):
    def test_private_result_poll_retries_a_transient_exec_timeout(self):
        calls = []
        def fly(args, **kwargs):
            calls.append(args)
            if len(calls) == 2: raise RuntimeError("Fly exec deadline_exceeded")
            output = {} if len(calls) == 1 else dict(exit_code=0, stdout=json.dumps(dict(integrity="ok")))
            return json.dumps(dict(exit_code=0, stdout=json.dumps(output)))
        with patch.object(deploy_fly, "run", side_effect=fly), patch.object(deploy_fly.time, "sleep"), patch.object(deploy_fly, "urlopen", side_effect=OSError):
            self.assertEqual(deploy_fly.remote("local-machine", "model"), {"integrity": "ok"})
        self.assertEqual(sum("subprocess.Popen" in call[3] for call in calls), 1)

    def test_actual_remote_helper_fits_the_fly_exec_payload_limit(self):
        calls = []
        def fly(args, **kwargs):
            calls.append(args)
            self.assertLess(len(args[3].encode()), 16000)
            output = {} if len(calls) == 1 else dict(exit_code=0, stdout=json.dumps(dict(integrity="ok")))
            return json.dumps(dict(exit_code=0, stdout=json.dumps(output)))
        with patch.object(deploy_fly, "run", side_effect=fly), patch.object(deploy_fly.time, "sleep"), patch.object(deploy_fly, "urlopen", side_effect=OSError):
            self.assertEqual(deploy_fly.remote("local-machine", "model"), {"integrity": "ok"})

    def test_rollout_requires_a_distinct_household_secret_before_fly_operations(self):
        for household in ("", "short", "deployment-secret-" * 3):
            with patch.dict(os.environ, FLY_API_TOKEN="deployment-secret-" * 3, MOBILE_API_TOKEN=household), patch.object(deploy_fly, "run") as fly:
                with self.assertRaises(RuntimeError):
                    deploy_fly.main()
                fly.assert_not_called()

    def test_remote_check_survives_a_detached_command_and_returns_private_result(self):
        with tempfile.TemporaryDirectory() as folder:
            scripts = Path(folder) / "scripts"
            scripts.mkdir()
            (scripts / "fly_sqlite_guard.py").write_text('import json, time; time.sleep(.05); print(json.dumps({"integrity": "ok"}))')
            def execute_locally(args, **kwargs):
                process = subprocess.run(shlex.split(args[3]), text=True, capture_output=True, timeout=5)
                return json.dumps(dict(exit_code=process.returncode, stdout=process.stdout))
            with patch.object(deploy_fly, "ROOT", Path(folder)), patch.object(deploy_fly, "run", side_effect=execute_locally), patch.object(deploy_fly.time, "sleep"), patch.object(deploy_fly, "urlopen", side_effect=OSError):
                self.assertEqual(deploy_fly.remote("local-machine", "test"), {"integrity": "ok"})

    def test_online_backup_preserves_records_and_is_private(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "meals.db"
            with sqlite3.connect(path) as db:
                db.executescript('''
                    CREATE TABLE user (id INTEGER PRIMARY KEY, username TEXT,
                        target_calories REAL, target_protein REAL, target_carbs REAL, target_fat REAL);
                    CREATE TABLE meal (id INTEGER PRIMARY KEY, user_id INTEGER, date TEXT,
                        weight REAL, calories REAL, protein REAL, carbs REAL, fat REAL,
                        image_data TEXT, psoriasis_score REAL);
                    INSERT INTO user VALUES (1, 'Private name', 2000, 100, 200, 60);
                    INSERT INTO meal VALUES (1, 1, '2026-11-10', 200, 400, 20, 30, 10, 'photo', 8);
                ''')
            before = path.read_bytes()
            with patch.dict(os.environ, DATABASE_URL="sqlite:///" + str(path)):
                result = guard.backup(root)
            backup = Path(result["backup_path"])
            self.assertEqual(path.read_bytes(), before)
            with sqlite3.connect(path) as source, sqlite3.connect(backup) as saved:
                self.assertEqual(list(source.iterdump()), list(saved.iterdump()))
            self.assertEqual(result["counts"], {"user": 1, "meal": 1})
            self.assertEqual(result["sha256"], hashlib.sha256(backup.read_bytes()).hexdigest())
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            manifest = backup.with_suffix(".json")
            self.assertEqual(manifest.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(manifest.read_text()), result)
            with patch.dict(os.environ, DATABASE_URL="sqlite:///" + str(path)):
                with patch.object(guard.shutil, "disk_usage", return_value=type("Space", (), {"free": 0})()):
                    self.assertEqual(guard.backup(root), result)
                with sqlite3.connect(path) as changed:
                    changed.execute("UPDATE meal SET calories=500 WHERE id=1")
                with patch.object(guard.shutil, "disk_usage", return_value=type("Space", (), {"free": 0})()):
                    with self.assertRaises(RuntimeError):
                        guard.backup(root)
            with patch.dict(os.environ, DATABASE_URL="sqlite:////tmp/missing-meals.db"):
                with self.assertRaises(RuntimeError):
                    guard.database_path(root)
            with tempfile.TemporaryDirectory() as scratch:
                original_backup = backup.read_bytes()
                guard.compress_old_backup(manifest, Path(root) / "backups", Path(scratch), root)
                archived = json.loads(manifest.read_text())
                self.assertEqual(gzip.decompress(Path(archived["backup_path"]).read_bytes()), original_backup)
                self.assertEqual(archived["compression"], "gzip")

    def test_low_volume_space_keeps_a_verified_compressed_current_backup(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "meals.db"
            with sqlite3.connect(path) as db:
                db.executescript('''
                    CREATE TABLE user (id INTEGER PRIMARY KEY, username TEXT,
                        target_calories REAL, target_protein REAL, target_carbs REAL, target_fat REAL);
                    CREATE TABLE meal (id INTEGER PRIMARY KEY, user_id INTEGER, date TEXT,
                        weight REAL, calories REAL, protein REAL, carbs REAL, fat REAL,
                        image_data TEXT, psoriasis_score REAL);
                    INSERT INTO user VALUES (1, 'Private name', 2000, 100, 200, 60);
                    INSERT INTO meal VALUES (1, 1, '2026-11-10', 200, 400, 20, 30, 10, '', 8);
                ''')
                db.execute("UPDATE meal SET image_data=?", ("A" * 150000,))
            before = path.read_bytes()
            def space(location):
                free = 64 * 1024 * 1024 + 4096 if str(location) == root else 2 * 1024 * 1024 * 1024
                return type("Space", (), {"free": free})()
            with patch.dict(os.environ, DATABASE_URL="sqlite:///" + str(path)), patch.object(guard.shutil, "disk_usage", side_effect=space):
                result = guard.backup(root)
                reused = guard.backup(root)
            self.assertEqual(reused, result)
            self.assertEqual(result["compression"], "gzip")
            archive = Path(result["backup_path"])
            self.assertEqual(hashlib.sha256(gzip.decompress(archive.read_bytes())).hexdigest(), result["sha256"])
            self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
            self.assertTrue(Path(result["manifest_path"]).is_file())
            self.assertEqual(path.read_bytes(), before)

    def test_config_preserves_mounts_and_existing_environment(self):
        original = dict(app=deploy_fly.APP, processes={"web": "old"},
            mounts=[dict(source="meal_data", destination="/data")],
            http_service=dict(internal_port=8080), env=dict(KEEP="existing"))
        saved = copy.deepcopy(original)
        config, port = deploy_fly.configuration(original, "revision", "accessible-model")
        self.assertEqual(port, 8080)
        self.assertEqual(config["mounts"], original["mounts"])
        self.assertEqual(config["env"]["KEEP"], "existing")
        self.assertEqual(config["env"]["RELEASE_COMMIT"], "revision")
        self.assertEqual(config["env"]["MEAL_ANALYSIS_MODEL"], "accessible-model")
        self.assertEqual(config["build"]["dockerfile"], "Dockerfile")
        self.assertTrue((deploy_fly.ROOT / config["build"]["dockerfile"]).is_file())
        self.assertIn('python -c "import app"', config["processes"]["web"])
        self.assertEqual(config["http_service"]["auto_stop_machines"], "off")
        self.assertEqual(config["http_service"]["min_machines_running"], 1)
        self.assertEqual(original, saved)
        del original["mounts"]
        with self.assertRaises(RuntimeError):
            deploy_fly.configuration(original, "revision", "model")

    def test_refuses_unexpected_machine_or_volume_layout(self):
        for machines in ([], [{}, {}], [dict(config={})]):
            with self.assertRaises(RuntimeError):
                deploy_fly.primary(machines)


if __name__ == "__main__":
    unittest.main()
