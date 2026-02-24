import unittest
from pathlib import Path
from unittest import mock

from alexandria import (URL, Chrome, ExternalDependency,
                        ExternalDependencyNotFound, InvalidURL)

ENCODE = "utf-8"
HTML_CONTENT = "<html><head><title>Wikipedia - Python</title></head>\n"


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

    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", lambda _: True)
    def test_basic_overwrite(self, mock_run):
        ls = self.LS()

        ls.run(["-a", "-b", "./"])
        mock_run.assert_called_with(["ls", "-a", "-b", "./"], check=False, stderr=None, stdout=None)

    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", lambda _: True)
    def test_basic_overwrite_merge(self, mock_run):
        ls = self.LS()

        ls.run(["-a", "-b", "./"], True)
        mock_run.assert_called_with(["ls", "-la", "-a", "-b", "./"], check=False, stderr=None, stdout=None)

    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", lambda _: True)
    def test_basic_merge(self, mock_run):
        ls = self.LS()

        ls.run(merge_args=True)
        mock_run.assert_called_with(["ls", "-la"], check=False, stderr=None, stdout=None)

    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", lambda _: True)
    def test_basic(self, mock_run):
        ls = self.LS()

        ls.run()
        self.assertEqual(ls.available_cmd(), "ls")
        mock_run.assert_called_with(["ls", "-la"], check=False, stderr=None, stdout=None)


    @mock.patch("shutil.which", lambda _: False)
    def test_available_cmd_not_exists(self):
        ls = self.LS()

        self.assertIsNone(ls.run())

        ls.raise_not_found = True
        with self.assertRaises(ExternalDependencyNotFound) as err:
            ls.run()
        self.assertEqual("ls is required dependency, please install it using your package manager",
                         str(err.exception))


class ChromeTest(unittest.TestCase):
    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", lambda _: True)
    def test_screenshot(self, mock_run):
        ss = Chrome(Path("~/doc"))
        ss.screenshot("url_test", "output")

        self.assertTrue(ss.quiet)
        self.assertEqual(ss.cmd, ["chromium", "chrome"])

        mock_run.assert_called_with([mock.ANY,
                                     '--run-all-compositor-stages-before-draw',
                                     '--disable-gpu', '--headless=new',
                                     '--virtual-time-budget=30000',
                                     '--hide-scrollbars', '--window-size=1920,4000',
                                     '--screenshot=~/doc/output.png', 'url_test'
                                     ], check=False, stderr=-3, stdout=-3)



# TODO Wget
# TODO Git

if __name__ == "__main__":
    unittest.main()
