import os
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from alexandria import Config, NeoDatabase

ENCODE = "utf-8"
HTML_CONTENT = "<html><head><title>Wikipedia - Python</title></head>\n"

# class ConfigTest(TestCase):
#     def test_config(self):
#         tmp_path_k = tempfile.TemporaryDirectory("alexandria")
#         tmp_path_k.cleanup()
#         tmp_path = tmp_path_k.name
#         pref = Config(path=tmp_path, _generate_readme)

#         self.assertDictEqual(
#             asdict(pref),
#             {
#                 "path": Path(tmp_path),
#                 "db_name": "database",
#                 "db_statics_name": "mirrors",
#                 "debug": False,
#                 "generate_readme": True,
#                 "readme_name": "README.md",
#                 "server_port": 8000,
#                 "skip_download": False,
#             },
#         )
#         self.assertEqual(pref.db, Path(f"{tmp_path}/{pref.db_name}"))
#         self.assertEqual(pref.db_statics, Path(f"{tmp_path}/{pref.db_statics_name}"))
#         self.assertEqual(pref.skip, False)
#         self.assertEqual(pref.statics_server, Path("./static"))


class DatabaseTest(TestCase):
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


# class AlexandriaTestCase:
#     def setup_db(self, db_path):
#         with open(db_path, "wb") as f:
#             f.write(DATABASE_DEFAULT)

#     def setup_html(self, path):
#         tmp_html = tempfile.NamedTemporaryFile("w+b", dir=path, suffix=".html", delete=False)
#         tmp_html.write(bytes(HTML_CONTENT, ENCODE))
#         html = tmp_html.name.split("/")[-1]
#         return html

#     @classmethod
#     def setUpClass(cls):
#         cls.tmp_path = tempfile.TemporaryDirectory("alexandria")
#         pref = Config(cls.tmp_path.name, generate_readme=True, debug=False)
#         pref.db_static.mkdir()

#         cls.pref = pref
#         cls.html = cls.setup_html(cls, pref.db_static)
#         cls.setup_db(cls, pref.db)

#         path = cls.tmp_path.name.split("/")[-1]
#         cls.url = f"http://{path}/{cls.html}"

#     def tearDown(self):
#         self.tmp_path.cleanup()


# class TestSanitizers(TestCase):
#     def test_sanitize_title(self):
#         title = "Python | language\n"
#         expected_title = "Python - language"
#         self.assertEqual(sanitize_title(title), expected_title)

#     def test_sanitize_url(self):
#         url = r"https://test-how-to-do-long-urls.com/whoistoolongurltoshoweverthingint\heview.html"
#         self.assertEqual(sanitize_url(url), "test-how-to-do-long-urls.com/whoistoolongurlt(...)")

#     def test_sanitize_datetime(self):
#         today = datetime(1997, 1, 1)
#         self.assertEqual(sanitize_datetime(today), "01. January 1997 12:00AM")

#     def test_size(self):
#         sizes = (0,
#                  1024,
#                  1024*1024,
#                  1024*1024*1024,
#                  1024*1024*8)
#         sizes_expected = ("0 B", "1.0 KiB", "1.0 MiB", "1.0 GiB", "8.0 MiB")
#         for size, expected in zip(sizes, sizes_expected):
#             self.assertEqual(sanitize_size(size), expected)


# class TestLog(AlexandriaTestCase, TestCase):
#     def test_border(self):
#         msg = border("Test msg")
#         border_msg = ("*" * 25)
#         expected_msg = border_msg + "\nTest msg\n" + border_msg

#         self.assertEqual(msg, expected_msg)

#     @patch("builtins.print")
#     def test_border_print_no_border(self, mock_print):
#         msg = debug_print("Test msg", add_border=False)
#         expected_msg = "[DEBUG] Test msg"

#         self.assertEqual(msg, expected_msg)
#         mock_print.assert_not_called()

#     @patch("builtins.print")
#     def test_border_print_border(self, mock_print):
#         alx.DEBUG = True
#         border_msg = ("*" * 25)
#         msg = debug_print("Test msg", add_border=True)
#         expected_msg = border_msg + "\n[DEBUG] Test msg\n" + border_msg

#         self.assertEqual(msg, expected_msg)
#         mock_print.assert_called_once()

#     @patch("builtins.print")
#     def test_title_print(self, mock_print):
#         title = title_print("Alexandria")
#         expected_title = "\n" + ("*" * 8) + " Alexandria " + ("*" * 8)

#         self.assertEqual(title, expected_title)

# class TestWebpage(AlexandriaTestCase, TestCase):
#     @patch("builtins.print")
#     def test_created_new(self, mock_stdout):
#         alx.DEBUG = True
#         webpage = Webpage(self.url)

#         mock_stdout.assert_called_with(f"[DEBUG] [GENERATED] {webpage!r}")
#         self.assertEqual(webpage.title, "Wikipedia - Python")
#         self.assertEqual(webpage.url, self.url)
#         self.assertEqual(webpage.base_path, self.path.name)
#         self.assertEqual(webpage.full_path, (self.path.name + "/" + self.html))

#     @patch('builtins.print')
#     def test_was_loaded_from_webpate(self, mock_stdout):
#         alx.DEBUG = True
#         expected_date = datetime(1972, 12, 17)
#         webpage_base = Webpage(self.url, expected_date)
#         webpage = Webpage.from_webpage(webpage_base)

#         mock_stdout.assert_called_with(f"[DEBUG] [RELOADED] {webpage!r}")
#         self.assertEqual(webpage.created_at, expected_date)
#         self.assertEqual(webpage, webpage_base)
#         self.assertNotEqual(id(webpage), id(webpage_base))

#     def test_eq(self):
#         webpage = Webpage(self.url)
#         webpage_two = Webpage(self.url)

#         self.assertEqual(webpage, webpage_two)

#     def test_to_md_line(self):
#         webpage = Webpage(self.url)
#         created_at = sanitize_datetime(webpage.created_at)
#         expected_md = (f"| [Wikipedia - Python]({self.url}) | {(created_at)} |")

#         self.assertEqual(webpage.to_md_line(), expected_md)

#     def test_to_html(self):
#         webpage = Webpage(self.url)

#         self.assertIn("<tr>", webpage.to_html())
#         self.assertIn(self.html, webpage.to_html())
#         self.assertIn(webpage.title, webpage.to_html())
#         self.assertIn("</tr>", webpage.to_html())

#     def test_calculate_size_disk(self):
#         webpage = Webpage(self.url)
#         self.assertEqual(webpage.calculate_size_disk(self.path.name), len(bytes(HTML_CONTENT, ENCODE)))
