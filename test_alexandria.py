import alexandria as alx

import tempfile
from unittest import TestCase
from unittest.mock import patch
from alexandria import WebPage

alx.DEBUG = True
ENCODE = "utf-8"


class AlexandriaSetupTestCase(TestCase):
    html_content = "<html><head><title>Wikipedia - Python</title></head>\n"

    def tmp_html(self):
        tmp_path = tempfile.TemporaryDirectory("alexandria", delete=False)
        tmp_html = tempfile.NamedTemporaryFile(
            "w+b", dir=tmp_path.name, suffix=".html", delete=False
        )
        tmp_html.write(bytes(self.html_content, ENCODE))

        path = tmp_path.name.split("/")[-1]
        file = tmp_html.name.split("/")[-1]
        return path, file, f"http://{path}/{file}"

    def new_webpage(self):
        return WebPage(self.url)

    def setUp(self):
        path, _, self.url = self.tmp_html()
        alx.ALEXANDRIA_PATH = f"/tmp/{path}"
        alx.DATABASE_PATH = f"/tmp/{path}" + "database"
        alx.DATABASE_README = f"/tmp/{path}" + "README.md"
        alx.MIRRORS_PATH = "/tmp/"


class TestWebPage(AlexandriaSetupTestCase):
    @patch('builtins.print')
    def test_was_created(self, mock_stdout):
        webpage = self.new_webpage()
        mock_stdout.assert_called_with(f"[DEBUG] Generated - {webpage.url}")
