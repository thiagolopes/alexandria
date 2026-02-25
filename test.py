import unittest
from pathlib import Path
from unittest import mock

from alexandria import URL, ExternalDependencyNotFound, URLInvalid

ENCODE = "utf-8"
HTML_CONTENT = "<html><head><title>Wikipedia - Python</title></head>\n"


class URLTest(unittest.TestCase):
    def test_url_not_url(self):
        with self.assertRaises(URLInvalid) as err:
            URL("ftp:192.182.0.1")
        self.assertIn("not HTTP", str(err.exception))

    def test_url_not_valid(self):
        with self.assertRaises(URLInvalid) as err:
            URL("192.182.0.1")
        self.assertIn("not valid URL", str(err.exception))


    def test_url(self):
        url = URL("https://github.com.br")

        self.assertEqual(url, URL("https://github.com.br"))
        self.assertEqual(url.__hash__(), URL("https://github.com.br").__hash__())
        # self.assertEqual(url.unique(), "")


if __name__ == "__main__":
    unittest.main()
