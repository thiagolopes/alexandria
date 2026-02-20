import os
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import unittest
from unittest.mock import patch, Mock

from pathlib import Path

from alexandria import log
from alexandria import NeoDatabase
from alexandria import URL, InvalidURL
from alexandria import ExternalDependency, ExternalDependencyNotFound, ScreenshotPage

ENCODE = "utf-8"
HTML_CONTENT = "<html><head><title>Wikipedia - Python</title></head>\n"


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir_k = tempfile.TemporaryDirectory("alexandria")
        self.tmp_dir = Path(self.tmp_dir_k.name)
        self.db = NeoDatabase(self.tmp_dir / "test.json")
        self.db.initial_migration()

    def tearDown(self):
        self.tmp_dir_k.cleanup()
        del self.tmp_dir_k

    def test_initial_migration(self):
        db = NeoDatabase(self.tmp_dir / "test_mig.json")
        self.assertEqual(Path(self.tmp_dir / "test_mig.json").exists(), False)
        db.initial_migration()
        self.assertEqual(Path(self.tmp_dir / "test_mig.json").exists(), True)

    def test_save(self):
        self.db.insert_one("profile", {"username": "a", "checklist": True})
        self.db.insert_one("profile", {"username": "b", "checklist": False})
        self.db.insert_one("temps", 32)
        self.db.insert_one("temps", 36)
        self.db["version"] = "0.0.1"
        self.db.save()

        # new database instance
        db = NeoDatabase(self.db.database_file)
        db.load()

        self.assertDictEqual(
            db.data,
            {
                "profile": [
                    {"checklist": True, "username": "a"},
                    {"checklist": False, "username": "b"},
                ],
                "temps": [32, 36],
                "version": "0.0.1",
            },
        )

    def test_insert_one(self):
        self.assertDictEqual(self.db.data, {})
        self.db.insert_one("profile", {"username": "a", "checklist": True})
        self.assertDictEqual(
            self.db.data, {"profile": [{"username": "a", "checklist": True}]}
        )

    def test_find_one(self):
        payload = {"username": "a", "checklist": True}
        self.db.insert_one("profile", payload)
        self.db.insert_one("temps", 32)
        self.db["version"] = "0.0.1"

        self.assertDictEqual(self.db.find_one("profile", {"username": "a"}), payload)
        self.assertEqual(self.db.find_one("profile", {"username": "c"}), None)
        self.assertEqual(self.db.find_one("profile", {"not-exists": "x"}), None)
        self.assertEqual(self.db.find_one("not-exist", {"not-exist": "x"}), None)
        self.assertEqual(self.db.find_one("temps", 32), 32)
        self.assertEqual(self.db["version"], "0.0.1")

    def test_contains(self):
        payload = {"username": "a", "checklist": True}
        self.db.insert_one("profile", payload)

        self.assertTrue("profile" in self.db)
        self.assertFalse("not-exist" in self.db)


class URLTest(unittest.TestCase):
    def test_url_not_url(self):
        with self.assertRaises(InvalidURL) as err:
            URL("ftp:192.182.0.1")
        self.assertIn("not HTTP", str(err.exception))

    def test_url_not_valid(self):
        with self.assertRaises(InvalidURL) as err:
            URL("192.182.0.1")
        self.assertIn("not valid URL", str(err.exception))


    def test_url(self):
        url = URL("https://github.com.br")

        self.assertEqual(url, URL("https://github.com.br"))
        self.assertEqual(url.__hash__(), URL("https://github.com.br").__hash__())
        # self.assertEqual(url.unique(), "")


class ExternalDependencyTest(unittest.TestCase):
    class LS(ExternalDependency):
        cmd = ["ls"]
        args = ["-la"]

    @patch("subprocess.run")
    @patch("shutil.which", lambda _: True)
    def test_basic_overwrite(self, mock_run):
        ls = self.LS()

        ls.run(["-a", "-b", "./"])
        mock_run.assert_called_with(["ls", "-a", "-b", "./"], check=False, stderr=None, stdout=None)

    @patch("subprocess.run")
    @patch("shutil.which", lambda _: True)
    def test_basic_overwrite_merge(self, mock_run):
        ls = self.LS()

        ls.run(["-a", "-b", "./"], True)
        mock_run.assert_called_with(["ls", "-la", "-a", "-b", "./"], check=False, stderr=None, stdout=None)

    @patch("subprocess.run")
    @patch("shutil.which", lambda _: True)
    def test_basic_merge(self, mock_run):
        ls = self.LS()

        ls.run(merge_args=True)
        mock_run.assert_called_with(["ls", "-la"], check=False, stderr=None, stdout=None)

    @patch("subprocess.run")
    @patch("shutil.which", lambda _: True)
    def test_basic(self, mock_run):
        ls = self.LS()

        ls.run()
        self.assertEqual(ls.available_cmd(), "ls")
        mock_run.assert_called_with(["ls", "-la"], check=False, stderr=None, stdout=None)


    @patch("shutil.which", lambda _: False)
    def test_available_cmd_not_exists(self):
        ls = self.LS()

        self.assertIsNone(ls.run())

        ls.raise_not_found = True
        with self.assertRaises(ExternalDependencyNotFound) as err:
            ls.run()
        self.assertEqual("ls is required dependency, please install it using your package manager",
                         str(err.exception))


class ScreenshotPageTest(unittest.TestCase):
    @patch("subprocess.run")
    @patch("shutil.which", lambda _: True)
    def test_screenshot(self, mock_run):
        ss = ScreenshotPage(Path("~/doc"))
        ss.screenshot("url_test", "output")

        self.assertTrue(ss.quiet)
        self.assertEqual(ss.cmd, ["chromium", "chrome"])

        mock_run.assert_called_with(
            ['chromium',
             '--run-all-compositor-stages-before-draw',
             '--disable-gpu',
             '--headless=new',
             '--virtual-time-budget=30000',
             '--hide-scrollbars',
             '--window-size=1920,4000',
             '--screenshot=~/doc/output',
             'url_test'],
            check=False,
            stderr=-3,
            stdout=-3
        )


# TODO Wget
# TODO Git


if __name__ == "__main__":
    unittest.main()
