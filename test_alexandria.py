import alexandria as alx

import tempfile
from unittest import TestCase
from unittest.mock import patch
from alexandria import WebPage
from datetime import datetime

alx.DEBUG = True
ENCODE = "utf-8"


class WebpageTestCase:
    def tmp_html(self):
        html_content = "<html><head><title>Wikipedia - Python</title></head>\n"
        tmp_path = tempfile.TemporaryDirectory("alexandria", delete=False)
        tmp_html = tempfile.NamedTemporaryFile("w+b", dir=tmp_path.name, suffix=".html", delete=False)
        tmp_html.write(bytes(html_content, ENCODE))

        path = tmp_path.name.split("/")[-1]
        file = tmp_html.name.split("/")[-1]
        return (tmp_path, tmp_html, f"http://{path}/{file}")

    @classmethod
    def setUpClass(cls):
        cls.path, _, cls.url = cls.tmp_html(None)
        alx.ALEXANDRIA_PATH = cls.path.name
        alx.DATABASE_PATH = cls.path.name + "database"
        alx.DATABASE_README = cls.path.name + "README.md"
        alx.MIRRORS_PATH = "/tmp/"


class TestWebPage(WebpageTestCase, TestCase):
    @patch('builtins.print')
    def test_was_created(self, mock_stdout):
        webpage = WebPage(self.url)
        mock_stdout.assert_called_with(f"[DEBUG] Generated - {webpage.url}")

    @patch('builtins.print')
    def test_was_loaded_from_webpate(self, mock_stdout):
        expected_date = datetime(1972, 12, 17)
        webpage_base = WebPage(self.url, expected_date)
        webpage = WebPage.from_webpage(webpage_base)

        mock_stdout.assert_called_with(f"[DEBUG] Reloaded - {webpage.url}")
        self.assertEqual(webpage.created_at, expected_date)

    def test_eq(self):
        webpage = WebPage(self.url)
        webpage_two = WebPage(self.url)

        self.assertEqual(webpage, webpage_two)
