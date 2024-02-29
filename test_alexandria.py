import alexandria as alx

import tempfile
import os
from unittest import TestCase
from unittest.mock import patch
from alexandria import (Webpage, Database,
                        sanitize_datetime, sanitize_size, sanitize_title, sanitize_url)
from datetime import datetime

ENCODE = "utf-8"
HTML_CONTENT = "<html><head><title>Wikipedia - Python</title></head>\n"
DATABASE_DEFAULT = b"\x80\x05\x5D\x94."


class AlexandriaTestCase:
    def setup_db(self):
        db_path = self.path.name + "/database"
        with open(db_path, "wb") as f:
            f.write(DATABASE_DEFAULT)
        return db_path

    def setup_tmp_path(self):
        return tempfile.TemporaryDirectory("alexandria")

    def setup_html(self, path):
        tmp_html = tempfile.NamedTemporaryFile("w+b", dir=path, suffix=".html", delete=False)
        tmp_html.write(bytes(HTML_CONTENT, ENCODE))
        html = tmp_html.name.split("/")[-1]
        return html

    @classmethod
    def setUpClass(cls):
        cls.path = cls.setup_tmp_path(cls)
        cls.html = cls.setup_html(cls, cls.path.name)

        path = cls.path.name.split("/")[-1]
        cls.url = f"http://{path}/{cls.html}"

        alx.ALEXANDRIA_PATH = cls.path.name
        alx.MIRRORS_PATH = "/tmp/"
        alx.DEBUG = False

    def tearDown(self):
        alx.DEBUG = False


class TestSanitizers(TestCase):
    def test_sanitize_title(self):
        title = "Python | language\n"
        expected_title = "Python - language"
        self.assertEqual(sanitize_title(title), expected_title)

    def test_sanitize_url(self):
        url = "https://test-how-to-do-long-urls.com/whoistoolongurltoshoweverthingintheview.html"
        self.assertEqual(sanitize_url(url), "test-how-to-do-long-urls.com/whoistoolongurlt(...)")

    def test_sanitize_datetime(self):
        today = datetime(1997, 1, 1)
        self.assertEqual(sanitize_datetime(today), "01. January 1997 12:00AM")

    def test_size(self):
        sizes = (1024,            # 1KB
                 1024*1024,       # 1MB
                 1024*1024*1024,  # 1GB
                 1024*1024*8,)    # 8,4MB
        sizes_expected = ("1.0 KB", "1.0 MB", "1.1 GB", "8.4 MB")
        for size, expected in zip(sizes, sizes_expected):
            self.assertEqual(sanitize_size(size), expected)


class TestDatabase(AlexandriaTestCase, TestCase):
    @patch("alexandria.Database.add")
    @patch("alexandria.Database.save")
    def test_new_without_migration(self, save_mock, add_mock):
        db_path = self.setup_db()
        database = Database(db_path)

        save_mock.assert_not_called()
        add_mock.assert_not_called()
        self.assertEqual(database.path, db_path)
        self.assertEqual(len(database.data), 0)

    @patch("alexandria.Database.add")
    def test_new_with_migration(self, add_mock):
        expected_dir = "/alx"
        database_path = self.path.name + f"{expected_dir}/database"

        database = Database(database_path)

        add_mock.assert_not_called()
        self.assertTrue(os.path.exists(self.path.name + expected_dir))
        self.assertEqual(database.path, database_path)
        self.assertEqual(len(database.data), 0)

    def test_save(self):
        db_path = self.setup_db()
        database = Database(db_path)
        webpage = Webpage(self.url)

        database.add(webpage)
        database.save()

        self.assertEqual(database.data, [webpage])
        with open(db_path, "rb") as f:
            db = f.read()
        self.assertNotEqual(db, DATABASE_DEFAULT)


class TestWebpage(AlexandriaTestCase, TestCase):
    @patch("builtins.print")
    def test_created_new(self, mock_stdout):
        alx.DEBUG = True
        webpage = Webpage(self.url)

        mock_stdout.assert_called_with(f"[DEBUG] [GENERATED] {webpage!r}")
        self.assertEqual(webpage.title, "Wikipedia - Python")
        self.assertEqual(webpage.size, len(bytes(HTML_CONTENT, ENCODE)))
        self.assertEqual(webpage.url, self.url)
        self.assertEqual(webpage.base_path, self.path.name)
        self.assertEqual(webpage.full_path, (self.path.name + "/" + self.html))

    @patch('builtins.print')
    def test_was_loaded_from_webpate(self, mock_stdout):
        alx.DEBUG = True
        expected_date = datetime(1972, 12, 17)
        webpage_base = Webpage(self.url, expected_date)
        webpage = Webpage.from_webpage(webpage_base)

        mock_stdout.assert_called_with(f"[DEBUG] [RELOADED] {webpage!r}")
        self.assertEqual(webpage.created_at, expected_date)
        self.assertEqual(webpage, webpage_base)
        self.assertNotEqual(id(webpage), id(webpage_base))

    def test_eq(self):
        webpage = Webpage(self.url)
        webpage_two = Webpage(self.url)

        self.assertEqual(webpage, webpage_two)

    def test_to_md(self):
        webpage = Webpage(self.url)
        created_at = sanitize_datetime(webpage.created_at)
        expected_md = (f"| [Wikipedia - Python]({self.url}) | {(created_at)} |")

        self.assertEqual(webpage.to_md(), expected_md)

    def test_to_html(self):
        webpage = Webpage(self.url)

        self.assertIn("<tr>", webpage.to_html())
        self.assertIn(self.html, webpage.to_html())
        self.assertIn(webpage.title, webpage.to_html())
        self.assertIn("</tr>", webpage.to_html())
