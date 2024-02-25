import alexandria as alx

import tempfile
from unittest import TestCase
from unittest.mock import patch
from alexandria import Webpage
from datetime import datetime

ENCODE = "utf-8"
HTML_CONTENT = "<html><head><title>Wikipedia - Python</title></head>\n"


class WebpageTestCase:
    def tmp_html(self):
        tmp_path = tempfile.TemporaryDirectory("alexandria")
        tmp_html = tempfile.NamedTemporaryFile("w+b", dir=tmp_path.name, suffix=".html", delete=False)
        tmp_html.write(bytes(HTML_CONTENT, ENCODE))

        path = tmp_path.name.split("/")[-1]
        file = tmp_html.name.split("/")[-1]
        return (tmp_path, file, f"http://{path}/{file}")

    @classmethod
    def setUpClass(cls):
        cls.path, cls.html, cls.url = cls.tmp_html(None)
        alx.ALEXANDRIA_PATH = cls.path.name
        alx.DATABASE_PATH = cls.path.name + "database"
        alx.DATABASE_README = cls.path.name + "README.md"
        alx.MIRRORS_PATH = "/tmp/"

    def tearDown(self):
        alx.DEBUG = False


class TestWebpage(WebpageTestCase, TestCase):
    @patch('builtins.print')
    def test_created_new(self, mock_stdout):
        alx.DEBUG = True
        webpage = Webpage(self.url)

        mock_stdout.assert_called_with(f"[DEBUG] Generated - {webpage.url}")
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

        mock_stdout.assert_called_with(f"[DEBUG] Reloaded - {webpage.url}")
        self.assertEqual(webpage.created_at, expected_date)

    def test_eq(self):
        webpage = Webpage(self.url)
        webpage_two = Webpage(self.url)

        self.assertEqual(webpage, webpage_two)

    def test_sanitize_title(self):
        webpage = Webpage(self.url)
        webpage.title = "Python | language\n"

        self.assertEqual(webpage.sanitize_title(), "Python - language")

    def test_to_md(self):
        webpage = Webpage(self.url)
        expected_md = (f"| [Wikipedia - Python]({self.url}) | "
                       f"{webpage.created_at.strftime(alx.DATETIME_FMT)} |")

        self.assertEqual(webpage.to_md(), expected_md)

    def test_to_html(self):
        webpage = Webpage(self.url)

        self.assertIn("<tr>", webpage.to_html())
        self.assertIn(self.html, webpage.to_html())
        self.assertIn(webpage.title, webpage.to_html())
        self.assertIn("</tr>", webpage.to_html())
